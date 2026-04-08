from __future__ import annotations

import json

import anyio

from backend.escritorio._llm_utils import (
    coerce_to_long_text,
    make_json_response_config,
    parse_json_payload,
    unwrap_envelope,
)
from backend.escritorio.config import (
    DEFAULT_LLM_TIMEOUT_MS,
    DEFAULT_REASONING_FALLBACK_MODEL,
    DEFAULT_REASONING_MODEL,
)
from backend.escritorio.models import RatioEscritorioState
from backend.escritorio.verifier import CitationCandidate, canonicalize_candidate, extract_citation_candidates


def _format_teses_for_redaction_prompt(state: RatioEscritorioState) -> list[str]:
    if not state.teses:
        return ["- Sem teses estruturadas"]

    lines: list[str] = []
    for tese in state.teses:
        tipo = str(tese.tipo or "principal").strip()
        descricao = str(tese.descricao or "").strip() or "Tese sem descricao"
        resposta = str(tese.resposta_pesquisa or "").strip()
        lines.append(f"- [{tipo}] {descricao}")
        if resposta:
            lines.append(f"  Analise do Theo: {resposta}")
    return lines


def build_redaction_prompt(state: RatioEscritorioState) -> str:
    facts = (state.fatos_brutos or "").strip() or "Sem fatos informados."
    teses = _format_teses_for_redaction_prompt(state)
    jurisprudencia = [
        f"- {row.get('processo') or row.get('doc_id') or 'Documento sem id'}"
        for row in state.pesquisa_jurisprudencia[:10]
    ] or ["- Sem jurisprudencia curada"]
    legislacao = [
        f"- {row.get('diploma') or row.get('doc_id') or 'Norma sem id'}"
        for row in state.pesquisa_legislacao[:10]
    ] or ["- Sem legislacao curada"]

    return (
        "Voce e um advogado redator especialista em contencioso.\n"
        "Redija a peça com base APENAS nos fatos e fontes abaixo.\n"
        "Retorne SOMENTE um objeto JSON em que cada chave e uma secao da peça e cada valor e o texto da secao.\n"
        "Nao retorne markdown, explicacoes ou texto fora do JSON.\n\n"
        f"Tipo de peça: {state.tipo_peca}\n"
        f"Fatos:\n{facts}\n\n"
        "Teses:\n"
        + "\n".join(teses)
        + "\n\nJurisprudencia:\n"
        + "\n".join(jurisprudencia)
        + "\n\nLegislacao:\n"
        + "\n".join(legislacao)
    )


_SECTION_ENVELOPE_KEYS = ("peca_sections", "sections", "secoes", "peca", "data")


def parse_sections_payload(raw_payload: str) -> dict[str, str]:
    """Parse a sections dict, never dropping section text.

    Gemini sometimes returns:
      - ``{"peca_sections": {...}}`` instead of the bare object;
      - section values as nested dicts (``{"titulo":..., "conteudo":...}``);
      - section values as lists of paragraphs.

    We flatten everything via :func:`coerce_to_long_text`, joining lists with
    blank lines and dicts by their canonical content key, so the petition
    text is preserved.
    """
    data = parse_json_payload(raw_payload, expect="object")
    if not isinstance(data, dict):
        raise ValueError("Payload de redacao deve ser um objeto JSON.")
    data = unwrap_envelope(data, candidate_keys=_SECTION_ENVELOPE_KEYS)
    if not isinstance(data, dict):
        raise ValueError("Payload de redacao deve ser um objeto JSON.")
    parsed: dict[str, str] = {}
    for key, value in data.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        text = coerce_to_long_text(value)
        if not text:
            continue
        parsed[normalized_key] = text
    if not parsed:
        raise ValueError("Payload de redacao nao contem secoes validas.")
    return parsed


def build_revision_prompt(revision_payload: dict[str, object]) -> str:
    return (
        "Voce e um advogado redator especialista revisando uma peca processual.\n"
        "Retorne SOMENTE um objeto JSON com as secoes que precisam ser atualizadas.\n"
        "Respeite preserve_human_anchors quando verdadeiro.\n\n"
        + json.dumps(revision_payload, ensure_ascii=False, indent=2)
    )


def infer_section_provenance(sections: dict[str, str]) -> dict[str, list[str]]:
    provenance: dict[str, list[str]] = {}
    for section_name, content in sections.items():
        canonical_keys = []
        for candidate in extract_citation_candidates(content):
            if candidate.canonical_key:
                canonical_keys.append(candidate.canonical_key)
        if canonical_keys:
            provenance[section_name] = list(dict.fromkeys(canonical_keys))
    return provenance


def _candidate_from_research_row(row: dict[str, object]) -> list[CitationCandidate]:
    candidates: list[CitationCandidate] = []
    processo = str(row.get("processo") or "").strip()
    if processo:
        candidates.extend(extract_citation_candidates(processo))

    diploma = str(row.get("diploma") or "").strip()
    article = str(row.get("article") or "").strip()
    if diploma and article:
        candidates.append(
            canonicalize_candidate(
                CitationCandidate(
                    kind="legislacao",
                    raw_text=f"art. {article} {diploma}",
                    normalized_text=f"art {article} {diploma.lower()}",
                    article=article,
                    diploma=diploma.upper(),
                )
            )
        )
    return candidates


def build_section_evidence_pack(
    state: RatioEscritorioState,
    sections: dict[str, str],
) -> dict[str, list[str]]:
    pool_keys: list[str] = []
    for row in state.pesquisa_jurisprudencia:
        for candidate in _candidate_from_research_row(row):
            if candidate.canonical_key:
                pool_keys.append(candidate.canonical_key)
    for row in state.pesquisa_legislacao:
        for candidate in _candidate_from_research_row(row):
            if candidate.canonical_key:
                pool_keys.append(candidate.canonical_key)

    section_keys = infer_section_provenance(sections)
    evidence_pack: dict[str, list[str]] = {}
    merged_pool = list(dict.fromkeys(pool_keys))
    for section_name, keys in section_keys.items():
        merged = list(dict.fromkeys([*keys, *merged_pool]))
        evidence_pack[section_name] = merged
    return evidence_pack


def _is_retryable_generation_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return any(
        hint in message
        for hint in ("deadline_exceeded", "deadline expired", "504", "resource_exhausted", "429", "timeout")
    )


def _generate_json_with_fallback(*, prompt: str, client=None, model: str | None = None) -> str:
    active_client = client
    if active_client is None:
        from rag.query import get_gemini_client

        active_client = get_gemini_client()

    primary_model = (model or DEFAULT_REASONING_MODEL).strip()
    fallback_model = DEFAULT_REASONING_FALLBACK_MODEL.strip()
    config = make_json_response_config(timeout_ms=DEFAULT_LLM_TIMEOUT_MS)

    def _invoke_model(model_name: str) -> str:
        kwargs = {"model": model_name, "contents": prompt}
        if config is not None:
            kwargs["config"] = config
        response = active_client.models.generate_content(**kwargs)
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("Resposta vazia do modelo de redacao.")
        return text

    try:
        return _invoke_model(primary_model)
    except Exception as exc:
        if not fallback_model or fallback_model == primary_model or not _is_retryable_generation_error(exc):
            raise
        return _invoke_model(fallback_model)


async def generate_sections_with_gemini(
    state: RatioEscritorioState,
    *,
    client=None,
    model: str | None = None,
) -> dict[str, str]:
    prompt = build_redaction_prompt(state)
    configured_model = (model or DEFAULT_REASONING_MODEL).strip()

    def _invoke() -> dict[str, str]:
        text = _generate_json_with_fallback(prompt=prompt, client=client, model=configured_model)
        return parse_sections_payload(text)

    return await anyio.to_thread.run_sync(_invoke)


async def generate_revision_with_gemini(
    revision_payload: dict[str, object],
    *,
    client=None,
    model: str | None = None,
) -> dict[str, str]:
    prompt = build_revision_prompt(revision_payload)
    configured_model = (model or DEFAULT_REASONING_MODEL).strip()

    def _invoke() -> dict[str, str]:
        text = _generate_json_with_fallback(prompt=prompt, client=client, model=configured_model)
        return parse_sections_payload(text)

    return await anyio.to_thread.run_sync(_invoke)

from __future__ import annotations

import re
import asyncio
from typing import Any

import anyio

from backend.escritorio._llm_utils import (
    coerce_to_string,
    make_json_response_config,
    parse_json_payload,
)
from backend.escritorio.config import DEFAULT_LLM_TIMEOUT_MS, DEFAULT_REASONING_MODEL
from backend.escritorio.models import CriticaContraparte, RatioEscritorioState
from backend.escritorio.tools.ratio_tools import ratio_search

# Allowed values for CriticaContraparte.recomendacao (Literal in models.py).
_RECOMENDACAO_VALUES = {"aprovar", "revisar", "reestruturar"}
_RECOMENDACAO_ALIASES = {
    "aprovado": "aprovar",
    "approve": "aprovar",
    "ok": "aprovar",
    "revise": "revisar",
    "revisao": "revisar",
    "reestruturacao": "reestruturar",
    "reescrever": "reestruturar",
    "rewrite": "reestruturar",
}

# Field names whose values are list[FalhaCritica] in the schema.
_FALHA_LIST_FIELDS = ("falhas_processuais", "argumentos_materiais_fracos")
_JURIS_FALTANTE_FIELD = "jurisprudencia_faltante"


def build_contraparte_prompt(state: RatioEscritorioState) -> str:
    sections = [
        f"{titulo.upper().replace('_', ' ')}:\n{conteudo}"
        for titulo, conteudo in state.peca_sections.items()
    ] or ["SEM SECOES REDIGIDAS"]
    return (
        "Voce e um advogado senior da parte contraria, implacavel.\n"
        "Seu objetivo e atacar a peca abaixo e encontrar falhas processuais, materiais e de lastro.\n"
        "Retorne SOMENTE um objeto JSON com os campos: falhas_processuais, argumentos_materiais_fracos, "
        "jurisprudencia_faltante, score_de_risco, analise_contestacao, recomendacao.\n"
        "Para CADA falha, preencha obrigatoriamente: secao_afetada, descricao, argumento_contrario.\n"
        "Nao deixe secao_afetada ou argumento_contrario vazios. Se a critica for geral, use secao_afetada = 'geral'.\n\n"
        "Peca:\n"
        + "\n\n".join(sections)
    )


def _coerce_score(value: Any) -> int:
    """Extract an integer 0-100 from whatever the model returned."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        score = int(value)
    else:
        text = str(value or "").strip()
        if not text:
            return 0
        match = re.search(r"-?\d+", text)
        if not match:
            return 0
        score = int(match.group(0))
    return max(0, min(100, score))


def _coerce_recomendacao(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z]", "", text)
    if text in _RECOMENDACAO_VALUES:
        return text
    if text in _RECOMENDACAO_ALIASES:
        return _RECOMENDACAO_ALIASES[text]
    # Default to "revisar" so the pipeline keeps moving instead of crashing
    # when the model invents a synonym.
    return "revisar"


def _coerce_falha_item(item: Any) -> dict[str, Any]:
    """Normalize a falha entry into a dict accepted by FalhaCritica.

    The schema accepts extra keys but requires str fields. We never drop
    information: any unrecognized payload becomes the ``descricao`` text.
    """
    if isinstance(item, dict):
        result = dict(item)
        # Coerce known string fields so pydantic does not bail on dict values.
        for key in (
            "finding_id",
            "secao_afetada",
            "descricao",
            "argumento_contrario",
            "query_jurisprudencia_contraria",
        ):
            if key in result and not isinstance(result[key], str):
                result[key] = coerce_to_string(result[key])
        # Ensure descricao is non-empty: if missing, fold the rest of the dict.
        if not str(result.get("descricao") or "").strip():
            fallback = coerce_to_string(
                {k: v for k, v in item.items() if k not in {"finding_id", "secao_afetada"}}
            )
            if fallback:
                result["descricao"] = fallback
        descricao = str(result.get("descricao") or "").strip()
        if descricao and not str(result.get("secao_afetada") or "").strip():
            result["secao_afetada"] = "geral"
        if descricao and not str(result.get("argumento_contrario") or "").strip():
            result["argumento_contrario"] = descricao
        return result
    text = coerce_to_string(item)
    return {"descricao": text} if text else {"descricao": ""}


def parse_critique_payload(raw_payload: str) -> dict:
    data = parse_json_payload(raw_payload, expect="object")
    if not isinstance(data, dict):
        raise ValueError("Payload de critica deve ser um objeto JSON.")

    for field in _FALHA_LIST_FIELDS:
        raw_list = data.get(field)
        if raw_list is None:
            data[field] = []
            continue
        if not isinstance(raw_list, list):
            raw_list = [raw_list]
        coerced = [_coerce_falha_item(item) for item in raw_list]
        data[field] = [item for item in coerced if str(item.get("descricao") or "").strip()]

    raw_juris = data.get(_JURIS_FALTANTE_FIELD)
    if raw_juris is None:
        data[_JURIS_FALTANTE_FIELD] = []
    else:
        if not isinstance(raw_juris, list):
            raw_juris = [raw_juris]
        coerced_juris = [coerce_to_string(item) for item in raw_juris]
        data[_JURIS_FALTANTE_FIELD] = [s for s in coerced_juris if s]

    if "score_de_risco" in data:
        data["score_de_risco"] = _coerce_score(data["score_de_risco"])
    else:
        data["score_de_risco"] = 0

    if "analise_contestacao" in data and not isinstance(data["analise_contestacao"], str):
        data["analise_contestacao"] = coerce_to_string(data["analise_contestacao"])
    if not str(data.get("analise_contestacao") or "").strip():
        data["analise_contestacao"] = "Sem analise estruturada retornada pelo modelo."

    data["recomendacao"] = _coerce_recomendacao(data.get("recomendacao"))
    return data


async def generate_critique_with_gemini(
    state: RatioEscritorioState,
    *,
    client=None,
    model: str | None = None,
) -> dict:
    prompt = build_contraparte_prompt(state)
    configured_model = (model or DEFAULT_REASONING_MODEL).strip()

    def _invoke() -> dict:
        active_client = client
        if active_client is None:
            from rag.query import get_gemini_client

            active_client = get_gemini_client()

        config = make_json_response_config(timeout_ms=DEFAULT_LLM_TIMEOUT_MS)
        kwargs = {"model": configured_model, "contents": prompt}
        if config is not None:
            kwargs["config"] = config
        response = active_client.models.generate_content(**kwargs)
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("Resposta vazia na geracao de critica adversarial.")
        return parse_critique_payload(text)

    return await anyio.to_thread.run_sync(_invoke)


async def enrich_critique_with_contrary_jurisprudence(
    critique_payload: dict[str, Any],
    *,
    ratio_search_fn=ratio_search,
    limit: int = 3,
) -> dict[str, Any]:
    critique = CriticaContraparte.model_validate(critique_payload).model_copy(deep=True)
    findings = [*critique.falhas_processuais, *critique.argumentos_materiais_fracos]

    async def _enrich(item):
        query = str(item.query_jurisprudencia_contraria or "").strip()
        if not query:
            return item
        try:
            result = await ratio_search_fn(
                query,
                prefer_recent=True,
                persona="parecer",
                reranker_backend="gemini",
            )
            item.jurisprudencia_encontrada = list(result.get("docs", []))[:limit]
        except Exception:
            item.jurisprudencia_encontrada = []
        return item

    if findings:
        await asyncio.gather(*[_enrich(item) for item in findings])

    return critique.model_dump(mode="json")

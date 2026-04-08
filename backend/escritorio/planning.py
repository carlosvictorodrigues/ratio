from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

import anyio

from backend.escritorio._llm_utils import (
    coerce_to_string,
    extract_first_json_array,
    make_json_response_config,
    parse_json_payload,
    unwrap_envelope,
)
from backend.escritorio.config import DEFAULT_LLM_TIMEOUT_MS, DEFAULT_PESQUISADOR_MODEL
from backend.escritorio.costing import build_usage_entry
from backend.escritorio.models import RatioEscritorioState, TeseJuridica

_TIPO_VALUES = {"principal", "subsidiaria"}
_TIPO_ALIASES = {
    "principais": "principal",
    "primaria": "principal",
    "primary": "principal",
    "subsidiarias": "subsidiaria",
    "secundaria": "subsidiaria",
    "alternativa": "subsidiaria",
    "subsidiary": "subsidiaria",
}
_LEGISLATION_CATEGORIES = {"processual", "material", "pedidos"}


def build_case_decomposition_prompt(state: RatioEscritorioState) -> str:
    facts = (state.fatos_brutos or "").strip() or "Sem fatos informados."
    return (
        "Voce e um pesquisador juridico senior.\n"
        "Decomponha o caso abaixo em 3 a 5 teses juridicas objetivas.\n"
        "REGRA CRITICA: cada tese deve ser DISTINTA das demais — aborde angulos "
        "juridicos DIFERENTES (ex.: responsabilidade civil, dano moral, dano material, "
        "falha na prestacao do servico, direito do consumidor, etc.).\n"
        "NAO repita a mesma tese com redacao diferente.\n"
        "Retorne SOMENTE uma lista JSON de objetos com campos: id, descricao, tipo.\n"
        "Use tipo = principal ou subsidiaria.\n\n"
        f"Caso:\n{facts}"
    )


def build_legislation_query_prompt(state: RatioEscritorioState, teses: list[TeseJuridica]) -> str:
    facts = (state.fatos_brutos or "").strip() or "Sem fatos informados."
    teses_text = "\n".join(f"- [{t.tipo}] {t.descricao}" for t in teses) or "- Sem teses estruturadas"
    return (
        "Voce e um pesquisador juridico senior focado em fundamentos legais.\n"
        "Monte 3 a 5 consultas objetivas para pesquisar legislacao brasileira relevante ao caso.\n"
        "Cubra, quando pertinente, base processual, base material e pedidos/acessorios da peca.\n"
        "Retorne SOMENTE uma lista JSON de objetos com campos: categoria, consulta.\n"
        "categoria deve ser um de: processual, material, pedidos.\n"
        "NAO retorne artigos inventados; retorne apenas consultas de busca.\n\n"
        f"Tipo de peca: {state.tipo_peca}\n"
        f"Area do direito: {state.area_direito or 'nao informada'}\n"
        f"Fatos:\n{facts}\n\n"
        f"Teses:\n{teses_text}"
    )


def _coerce_tipo(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z]", "", text)
    if text in _TIPO_VALUES:
        return text
    if text in _TIPO_ALIASES:
        return _TIPO_ALIASES[text]
    return "principal"


def _coerce_tese_item(item: Any, index: int) -> dict[str, Any] | None:
    """Convert an arbitrary item into a TeseJuridica-compatible dict.

    Returns ``None`` only when no description can be derived (we never
    silently drop items that have content; we wrap them instead).
    """
    if isinstance(item, dict):
        result = dict(item)
        descricao = result.get("descricao")
        if not isinstance(descricao, str) or not descricao.strip():
            descricao = coerce_to_string(
                {k: v for k, v in item.items() if k not in {"id", "tipo", "confianca"}}
            )
        descricao = (descricao or "").strip()
        if not descricao:
            return None
        result["descricao"] = descricao
        raw_id = str(result.get("id") or "").strip()
        result["id"] = raw_id or f"t{index + 1}"
        result["tipo"] = _coerce_tipo(result.get("tipo"))
        return result
    text = coerce_to_string(item)
    if not text:
        return None
    return {"id": f"t{index + 1}", "descricao": text, "tipo": "principal"}


def _normalize_legislation_query_item(item: Any, index: int) -> dict[str, str] | None:
    if isinstance(item, dict):
        categoria = str(item.get("categoria") or "").strip().lower()
        if categoria not in _LEGISLATION_CATEGORIES:
            categoria = "material"
        consulta = coerce_to_string(item.get("consulta") or item.get("query") or item.get("descricao"))
    else:
        categoria = "material"
        consulta = coerce_to_string(item)

    consulta = " ".join(str(consulta or "").split()).strip()
    if not consulta:
        return None
    return {"id": f"q{index + 1}", "categoria": categoria, "consulta": consulta}


def parse_teses_payload(raw_payload: str) -> list[TeseJuridica]:
    """Parse a list of TeseJuridica from a Gemini response, tolerating envelopes."""
    text = str(raw_payload or "").strip()
    # Try array-first parsing; fall back to object-then-unwrap if the model
    # returned ``{"teses": [...]}`` instead of a bare list.
    try:
        data = parse_json_payload(text, expect="array")
    except (ValueError, Exception):
        try:
            wrapped = parse_json_payload(text, expect="object")
        except Exception:
            balanced = extract_first_json_array(text)
            if balanced is None:
                raise ValueError("Payload de teses deve ser uma lista JSON.")
            import json as _json

            data = _json.loads(balanced)
        else:
            data = unwrap_envelope(wrapped)

    if isinstance(data, dict):
        data = unwrap_envelope(data)
    if not isinstance(data, list):
        raise ValueError("Payload de teses deve ser uma lista JSON.")

    coerced: list[TeseJuridica] = []
    seen_descriptions: set[str] = set()
    for index, item in enumerate(data):
        normalized = _coerce_tese_item(item, index)
        if normalized is None:
            continue
        # Deduplicate by normalized description to avoid identical queries
        desc_key = re.sub(r"\s+", " ", (normalized.get("descricao") or "").strip().lower())
        if desc_key in seen_descriptions:
            log.warning("parse_teses_payload: tese duplicada descartada: %s", desc_key[:80])
            continue
        seen_descriptions.add(desc_key)
        coerced.append(TeseJuridica.model_validate(normalized))
    if not coerced:
        raise ValueError("Payload de teses nao contem teses validas.")
    return coerced


def parse_legislation_queries_payload(raw_payload: str) -> list[dict[str, str]]:
    text = str(raw_payload or "").strip()
    try:
        data = parse_json_payload(text, expect="array")
    except (ValueError, Exception):
        try:
            wrapped = parse_json_payload(text, expect="object")
        except Exception:
            balanced = extract_first_json_array(text)
            if balanced is None:
                raise ValueError("Payload de consultas legislativas deve ser uma lista JSON.")
            import json as _json

            data = _json.loads(balanced)
        else:
            data = unwrap_envelope(wrapped)

    if isinstance(data, dict):
        data = unwrap_envelope(data)
    if not isinstance(data, list):
        raise ValueError("Payload de consultas legislativas deve ser uma lista JSON.")

    queries: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(data):
        normalized = _normalize_legislation_query_item(item, index)
        if normalized is None:
            continue
        dedupe_key = f"{normalized['categoria']}::{normalized['consulta'].lower()}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        queries.append(normalized)
    if not queries:
        raise ValueError("Payload de consultas legislativas nao contem consultas validas.")
    return queries


def fallback_legislation_queries(state: RatioEscritorioState, teses: list[TeseJuridica]) -> list[dict[str, str]]:
    combined = " ".join(
        part for part in [
            state.tipo_peca,
            state.area_direito,
            state.fatos_brutos,
            *[t.descricao for t in teses],
        ]
        if part
    ).lower()

    queries: list[dict[str, str]] = []
    if state.tipo_peca == "peticao_inicial":
        queries.append({
            "id": "q1",
            "categoria": "processual",
            "consulta": "peticao inicial requisitos cpc art 319 art 320 valor da causa art 291",
        })
    if any(token in combined for token in ("gratuidade", "hipossuf", "justica gratuita")):
        queries.append({
            "id": f"q{len(queries) + 1}",
            "categoria": "processual",
            "consulta": "gratuidade de justica cpc art 98 art 99 declaracao de hipossuficiencia",
        })
    if any(token in combined for token in ("consumidor", "cdc", "fornecedor", "servico")):
        queries.append({
            "id": f"q{len(queries) + 1}",
            "categoria": "material",
            "consulta": "codigo de defesa do consumidor art 6 inciso viii art 14 responsabilidade pelo fato do servico",
        })
    if any(token in combined for token in ("responsabilidade", "danos", "dano moral", "dano material")):
        queries.append({
            "id": f"q{len(queries) + 1}",
            "categoria": "material",
            "consulta": "codigo civil art 186 art 187 art 927 responsabilidade civil danos materiais danos morais",
        })
    if not queries:
        queries.append({
            "id": "q1",
            "categoria": "material",
            "consulta": f"legislacao brasileira fundamentos legais {state.tipo_peca} {state.area_direito or 'caso concreto'}",
        })
    return queries[:5]


async def decompose_case_with_gemini(
    state: RatioEscritorioState,
    *,
    client=None,
    model: str | None = None,
    return_usage: bool = False,
) -> list[TeseJuridica]:
    prompt = build_case_decomposition_prompt(state)
    configured_model = (model or DEFAULT_PESQUISADOR_MODEL).strip()

    def _invoke():
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
            raise ValueError("Resposta vazia na decomposicao de teses.")
        parsed = parse_teses_payload(text)
        usage = build_usage_entry(model_name=configured_model, response=response, operation="decompose_teses")
        if return_usage:
            return parsed, usage
        return parsed

    return await anyio.to_thread.run_sync(_invoke)


async def plan_legislation_queries_with_gemini(
    state: RatioEscritorioState,
    teses: list[TeseJuridica],
    *,
    client=None,
    model: str | None = None,
    return_usage: bool = False,
) -> list[dict[str, str]]:
    prompt = build_legislation_query_prompt(state, teses)
    configured_model = (model or DEFAULT_PESQUISADOR_MODEL).strip()

    def _invoke():
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
            raise ValueError("Resposta vazia no planejamento de consultas legislativas.")
        parsed = parse_legislation_queries_payload(text)
        usage = build_usage_entry(model_name=configured_model, response=response, operation="plan_legislation_queries")
        if return_usage:
            return parsed, usage
        return parsed

    try:
        return await anyio.to_thread.run_sync(_invoke)
    except Exception:
        fallback = fallback_legislation_queries(state, teses)
        if return_usage:
            return fallback, None
        return fallback

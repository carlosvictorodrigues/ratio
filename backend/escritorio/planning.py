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


async def decompose_case_with_gemini(
    state: RatioEscritorioState,
    *,
    client=None,
    model: str | None = None,
) -> list[TeseJuridica]:
    prompt = build_case_decomposition_prompt(state)
    configured_model = (model or DEFAULT_PESQUISADOR_MODEL).strip()

    def _invoke() -> list[TeseJuridica]:
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
        return parse_teses_payload(text)

    return await anyio.to_thread.run_sync(_invoke)

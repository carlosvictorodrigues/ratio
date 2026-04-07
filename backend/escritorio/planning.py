from __future__ import annotations

import json

import anyio

from backend.escritorio.config import DEFAULT_PESQUISADOR_MODEL
from backend.escritorio.models import RatioEscritorioState, TeseJuridica


def build_case_decomposition_prompt(state: RatioEscritorioState) -> str:
    facts = (state.fatos_brutos or "").strip() or "Sem fatos informados."
    return (
        "Voce e um pesquisador juridico senior.\n"
        "Decomponha o caso abaixo em 3 a 5 teses juridicas objetivas.\n"
        "Retorne SOMENTE uma lista JSON de objetos com campos: id, descricao, tipo.\n"
        "Use tipo = principal ou subsidiaria.\n\n"
        f"Caso:\n{facts}"
    )


def parse_teses_payload(raw_payload: str) -> list[TeseJuridica]:
    data = json.loads(str(raw_payload or "").strip())
    if not isinstance(data, list):
        raise ValueError("Payload de teses deve ser uma lista JSON.")
    return [TeseJuridica.model_validate(item) for item in data]


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

        response = active_client.models.generate_content(
            model=configured_model,
            contents=prompt,
        )
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("Resposta vazia na decomposicao de teses.")
        return parse_teses_payload(text)

    return await anyio.to_thread.run_sync(_invoke)

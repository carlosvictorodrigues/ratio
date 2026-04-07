from __future__ import annotations

import json

import anyio

from backend.escritorio.config import DEFAULT_REASONING_MODEL
from backend.escritorio.models import RatioEscritorioState


def build_contraparte_prompt(state: RatioEscritorioState) -> str:
    sections = [
        f"{titulo.upper().replace('_', ' ')}:\n{conteudo}"
        for titulo, conteudo in state.peca_sections.items()
    ] or ["SEM SECOES REDIGIDAS"]
    return (
        "Voce e um advogado senior da parte contraria, implacavel.\n"
        "Seu objetivo e atacar a peca abaixo e encontrar falhas processuais, materiais e de lastro.\n"
        "Retorne SOMENTE um objeto JSON com os campos: falhas_processuais, argumentos_materiais_fracos, "
        "jurisprudencia_faltante, score_de_risco, analise_contestacao, recomendacao.\n\n"
        "Peca:\n"
        + "\n\n".join(sections)
    )


def parse_critique_payload(raw_payload: str) -> dict:
    data = json.loads(str(raw_payload or "").strip())
    if not isinstance(data, dict):
        raise ValueError("Payload de critica deve ser um objeto JSON.")
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

        response = active_client.models.generate_content(
            model=configured_model,
            contents=prompt,
        )
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("Resposta vazia na geracao de critica adversarial.")
        return parse_critique_payload(text)

    return await anyio.to_thread.run_sync(_invoke)

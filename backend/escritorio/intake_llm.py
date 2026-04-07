from __future__ import annotations

import json

import anyio

from backend.escritorio.config import DEFAULT_PESQUISADOR_MODEL
from backend.escritorio.models import RatioEscritorioState


def build_intake_prompt(state: RatioEscritorioState) -> str:
    facts = (state.fatos_brutos or "").strip() or "Sem fatos informados."
    return (
        "Voce e um advogado assistente em intake juridico.\n"
        "Estruture o caso abaixo e retorne SOMENTE um objeto JSON com os campos: "
        "fatos_estruturados, provas_disponiveis, pontos_atencao.\n\n"
        f"Caso:\n{facts}"
    )


def parse_intake_payload(raw_payload: str) -> dict:
    data = json.loads(str(raw_payload or "").strip())
    if not isinstance(data, dict):
        raise ValueError("Payload de intake deve ser um objeto JSON.")
    return data


async def generate_intake_with_gemini(
    state: RatioEscritorioState,
    *,
    client=None,
    model: str | None = None,
) -> dict:
    prompt = build_intake_prompt(state)
    configured_model = (model or DEFAULT_PESQUISADOR_MODEL).strip()

    def _invoke() -> dict:
        if client is not None:
            # Explicit client injected (e.g. in tests) — use it directly.
            response = client.models.generate_content(
                model=configured_model,
                contents=prompt,
            )
            text = getattr(response, "text", None)
            if not text:
                raise ValueError("Resposta vazia no intake.")
            return parse_intake_payload(text)

        from backend.escritorio.llm_provider import generate_text  # noqa: PLC0415

        return parse_intake_payload(generate_text(prompt, configured_model))

    return await anyio.to_thread.run_sync(_invoke)

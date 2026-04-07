from __future__ import annotations

import anyio

from backend.escritorio._llm_utils import (
    coerce_to_string,
    make_json_response_config,
    parse_json_payload,
)
from backend.escritorio.config import DEFAULT_LLM_TIMEOUT_MS, DEFAULT_PESQUISADOR_MODEL
from backend.escritorio.models import RatioEscritorioState


def build_intake_prompt(state: RatioEscritorioState) -> str:
    facts = (state.fatos_brutos or "").strip() or "Sem fatos informados."
    return (
        "Voce e um advogado assistente em intake juridico brasileiro.\n"
        "Estruture o caso abaixo e retorne SOMENTE um objeto JSON valido (sem markdown, sem comentarios) com EXATAMENTE estes campos:\n"
        '  - "fatos_estruturados": lista de STRINGS. Cada item deve ser UMA UNICA STRING narrando um fato relevante de forma objetiva.\n'
        '    NAO use objetos, NAO use chaves como "evento"/"data"/"descricao". Apenas uma frase em texto puro por item.\n'
        '  - "provas_disponiveis": lista de STRINGS, cada uma descrevendo um documento ou prova mencionada (texto puro).\n'
        '  - "pontos_atencao": lista de STRINGS com riscos, lacunas ou pontos que merecem cuidado (texto puro).\n\n'
        "Exemplo do formato esperado (apenas formato, ignore o conteudo):\n"
        '{"fatos_estruturados":["Em 21/09/2025 o autor compareceu ao exame.","O onibus apresentou pane mecanica em Mossoro/RN."],'
        '"provas_disponiveis":["Ordem de servico da agencia","Comprovante de pagamento Uber"],'
        '"pontos_atencao":["Necessario comprovar nexo entre dano e fraude"]}\n\n'
        f"Caso:\n{facts}"
    )


# Campos que aceitamos apenas como list[str] no estado do escritorio.
_STRING_LIST_FIELDS = ("fatos_estruturados", "provas_disponiveis", "pontos_atencao")


def parse_intake_payload(raw_payload: str) -> dict:
    data = parse_json_payload(raw_payload, expect="object")
    if not isinstance(data, dict):
        raise ValueError("Payload de intake deve ser um objeto JSON.")
    # Defensive coercion: the state schema requires list[str] for these fields,
    # but Gemini often returns dicts. Flatten everything to strings here so the
    # langgraph state validation downstream cannot fail because of shape drift.
    for field in _STRING_LIST_FIELDS:
        raw_list = data.get(field)
        if raw_list is None:
            continue
        if not isinstance(raw_list, list):
            raw_list = [raw_list]
        coerced = [coerce_to_string(item) for item in raw_list]
        data[field] = [s for s in coerced if s]
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
        active_client = client
        if active_client is None:
            from rag.query import get_gemini_client

            active_client = get_gemini_client()

        # Force JSON output via response_mime_type so the model never returns prose/markdown
        config = make_json_response_config(timeout_ms=DEFAULT_LLM_TIMEOUT_MS)
        kwargs = {"model": configured_model, "contents": prompt}
        if config is not None:
            kwargs["config"] = config
        response = active_client.models.generate_content(**kwargs)
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("Resposta vazia no intake.")
        return parse_intake_payload(text)

    return await anyio.to_thread.run_sync(_invoke)

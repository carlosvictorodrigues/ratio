from __future__ import annotations

import anyio

from backend.escritorio._llm_utils import (
    coerce_to_string,
    make_json_response_config,
    parse_json_payload,
)
from backend.escritorio.config import DEFAULT_LLM_TIMEOUT_MS, DEFAULT_PESQUISADOR_MODEL
from backend.escritorio.costing import build_usage_entry
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
        '  - "resposta_conversacional_clara": STRING curta, como se a Clara estivesse respondendo ao usuario em tom profissional.\n'
        '  - "perguntas_pendentes": lista de STRINGS com 1 a 3 perguntas-chave objetivas sobre as lacunas restantes.\n'
        '  - "triagem_suficiente": BOOLEAN indicando se ja existe material minimo razoavel para o usuario prosseguir assim mesmo.\n\n'
        "A Clara deve soar como uma analista juridica conversando com o usuario.\n"
        "Nao faca interrogatorio longo. Pergunte apenas o que realmente muda a peca.\n"
        "Sempre deixe claro que o usuario pode complementar ou prosseguir assim mesmo.\n\n"
        "Exemplo do formato esperado (apenas formato, ignore o conteudo):\n"
        '{"fatos_estruturados":["Em 21/09/2025 o autor compareceu ao exame.","O onibus apresentou pane mecanica em Mossoro/RN."],'
        '"provas_disponiveis":["Ordem de servico da agencia","Comprovante de pagamento Uber"],'
        '"pontos_atencao":["Necessario comprovar nexo entre dano e fraude"],'
        '"resposta_conversacional_clara":"Entendi o nucleo do caso. Antes de fechar a triagem, preciso confirmar dois pontos.",'
        '"perguntas_pendentes":["Quem e exatamente o reu?","Quais documentos ja estao em maos?"],'
        '"triagem_suficiente":true}\n\n'
        f"Caso:\n{facts}"
    )


# Campos que aceitamos apenas como list[str] no estado do escritorio.
_STRING_LIST_FIELDS = ("fatos_estruturados", "provas_disponiveis", "pontos_atencao")


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "sim", "yes"}


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
    data["resposta_conversacional_clara"] = coerce_to_string(data.get("resposta_conversacional_clara"))
    raw_questions = data.get("perguntas_pendentes")
    if raw_questions is None:
        raw_questions = []
    if not isinstance(raw_questions, list):
        raw_questions = [raw_questions]
    data["perguntas_pendentes"] = [s for s in (coerce_to_string(item) for item in raw_questions) if s]
    data["triagem_suficiente"] = _coerce_bool(data.get("triagem_suficiente"))
    return data


async def generate_intake_with_gemini(
    state: RatioEscritorioState,
    *,
    client=None,
    model: str | None = None,
    return_usage: bool = False,
) -> dict:
    prompt = build_intake_prompt(state)
    configured_model = (model or DEFAULT_PESQUISADOR_MODEL).strip()

    def _invoke():
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
        parsed = parse_intake_payload(text)
        usage = build_usage_entry(model_name=configured_model, response=response, operation="intake")
        if return_usage:
            return parsed, usage
        return parsed

    return await anyio.to_thread.run_sync(_invoke)

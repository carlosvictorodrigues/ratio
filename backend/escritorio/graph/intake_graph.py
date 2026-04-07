from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from backend.escritorio.intake_llm import generate_intake_with_gemini
from backend.escritorio.models import RatioEscritorioState

log = logging.getLogger(__name__)


async def intake_node(state: RatioEscritorioState) -> dict[str, Any]:
    log.info("intake_node: chamando Gemini para analise de intake...")
    try:
        parsed = await generate_intake_with_gemini(state)
    except Exception:
        log.exception("intake_node: falha ao gerar intake com Gemini")
        parsed = {}

    log.info("intake_node: resposta Gemini recebida. Processando...")
    fatos = list(parsed.get("fatos_estruturados") or [])
    provas = list(parsed.get("provas_disponiveis") or [])
    pontos = list(parsed.get("pontos_atencao") or [])

    has_structured_data = len(fatos) > 0
    status = "gate1" if has_structured_data else "intake"
    log.info("intake_node: concluido — status=%s (fatos=%d)", status, len(fatos))
    return {
        "fatos_estruturados": fatos,
        "provas_disponiveis": provas,
        "pontos_atencao": pontos,
        "status": status,
        "workflow_stage": status,
    }


def gate1_node(state: RatioEscritorioState) -> dict[str, Any]:
    return {
        "status": "gate1",
        "workflow_stage": "gate1",
    }


def gate1_router(state: RatioEscritorioState) -> str:
    return "drafting" if state.gate1_aprovado else "intake"


def build_intake_graph(
    *,
    intake_fn: Callable[[RatioEscritorioState], dict[str, Any]] | None = None,
    gate1_router_fn: Callable[[RatioEscritorioState], str] | None = None,
    enable_interrupts: bool = True,
):
    graph = StateGraph(RatioEscritorioState)
    graph.add_node("intake", intake_fn or intake_node)
    graph.add_node("gate1", gate1_node)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "gate1")
    graph.add_conditional_edges(
        "gate1",
        gate1_router_fn or gate1_router,
        {"intake": "intake", "drafting": END},
    )
    interrupt_before = ["gate1"] if enable_interrupts else []
    return graph.compile(interrupt_before=interrupt_before)

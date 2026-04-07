from __future__ import annotations

import anyio
import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from backend.escritorio.intake import compute_checklist
from backend.escritorio.intake_llm import generate_intake_with_gemini
from backend.escritorio.models import RatioEscritorioState

log = logging.getLogger(__name__)


def intake_node(state: RatioEscritorioState) -> dict[str, Any]:
    log.info("intake_node: chamando Gemini para analise de intake...")
    try:
        parsed = anyio.run(generate_intake_with_gemini, state)
    except Exception:
        log.exception("intake_node: falha ao gerar intake com Gemini")
        parsed = {}

    log.info("intake_node: resposta Gemini recebida. Processando...")
    draft_state = state.model_copy(deep=True)
    if parsed.get("fatos_estruturados"):
        draft_state.fatos_estruturados = list(parsed["fatos_estruturados"])
    if parsed.get("provas_disponiveis"):
        draft_state.provas_disponiveis = list(parsed["provas_disponiveis"])
    if parsed.get("pontos_atencao"):
        draft_state.pontos_atencao = list(parsed["pontos_atencao"])

    checklist = compute_checklist(draft_state)
    status = "gate1" if checklist.fatos_principais_cobertos else "intake"
    log.info("intake_node: concluido — status=%s", status)
    return {
        "fatos_estruturados": draft_state.fatos_estruturados,
        "provas_disponiveis": draft_state.provas_disponiveis,
        "pontos_atencao": draft_state.pontos_atencao,
        "intake_checklist": checklist.model_dump(),
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

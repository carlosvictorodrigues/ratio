from __future__ import annotations

import logging
from pathlib import Path
import os
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

log = logging.getLogger(__name__)

from backend.escritorio.contraparte import (
    enrich_critique_with_contrary_jurisprudence,
    generate_critique_with_gemini,
)
from backend.escritorio.formatter import FormatadorPeticao
from backend.escritorio.models import RatioEscritorioState
from backend.escritorio.tools.lancedb_access import LanceDBReadonlyRegistry
from backend.escritorio.redaction import generate_revision_with_gemini
from backend.escritorio.state import build_redator_revision_payload
from backend.escritorio.store import slugify_case_id
from backend.escritorio.verifier import verify_sections


async def contraparte_node(state: RatioEscritorioState) -> dict[str, Any]:
    critique = await generate_critique_with_gemini(state)
    critique = await enrich_critique_with_contrary_jurisprudence(critique)
    return {
        "status": "adversarial",
        "workflow_stage": "adversarial",
        "critica_atual": critique,
    }


def anti_sycophancy_node(state: RatioEscritorioState) -> dict[str, Any]:
    critique = state.critica_atual
    invalid = critique is None or (
        critique.score_de_risco == 0
        and not critique.falhas_processuais
        and not critique.argumentos_materiais_fracos
        and not critique.jurisprudencia_faltante
    )
    return {
        "status": "adversarial",
        "workflow_stage": "adversarial",
        "contraparte_retries": state.contraparte_retries + 1 if invalid else 0,
    }


def sycophancy_router(state: RatioEscritorioState) -> str:
    critique = state.critica_atual
    if critique is None:
        if state.contraparte_retries >= 2:
            return "aceita"
        return "rejeita"
    if (
        critique.score_de_risco == 0
        and not critique.falhas_processuais
        and not critique.argumentos_materiais_fracos
        and not critique.jurisprudencia_faltante
    ):
        if state.contraparte_retries >= 2:
            return "aceita"
        return "rejeita"
    return "aceita"


def pausa_humana_node(state: RatioEscritorioState) -> dict[str, Any]:
    return {
        "status": "revisao_humana",
        "workflow_stage": "revisao_humana",
    }


def decisao_advogado_router(state: RatioEscritorioState) -> str:
    return "finalizar" if state.usuario_finaliza else "mais_rodada"


async def redator_revisao_node(state: RatioEscritorioState) -> dict[str, Any]:
    current_round = state.rodadas[-1] if state.rodadas else None
    revision_payload = build_redator_revision_payload(
        state,
        preserve_human_anchors=True,
        human_notes=current_round.apontamentos_humanos if current_round else None,
        edited_sections=current_round.secoes_revisadas if current_round else None,
    )
    revised_sections = await generate_revision_with_gemini(revision_payload)
    merged_sections = dict(state.peca_sections)
    merged_sections.update(revised_sections)
    return {
        "peca_sections": merged_sections,
        "status": "adversarial",
        "workflow_stage": "adversarial",
    }


def verificador_node(state: RatioEscritorioState) -> dict[str, Any]:
    try:
        from rag.query import LANCE_DIR
        registry = LanceDBReadonlyRegistry()
        verificacoes = verify_sections(
            state,
            registry=registry,
            lance_dir=LANCE_DIR,
        )
    except Exception:
        log.exception("verificador_node: falha ao verificar secoes")
        verificacoes = []
    return {
        "status": "verificacao",
        "workflow_stage": "verificacao",
        "verificacoes": verificacoes,
    }


def formatador_node(state: RatioEscritorioState) -> dict[str, Any]:
    root_dir = Path(
        (os.getenv("RATIO_ESCRITORIO_ROOT") or "").strip()
        or (Path(__file__).resolve().parents[3] / "logs" / "runtime" / "ratio_escritorio")
    ).expanduser()
    case_dir = root_dir / "casos" / slugify_case_id(state.caso_id)
    output_dir = case_dir / "output"
    formatter = FormatadorPeticao(output_dir=output_dir)
    output_path = formatter.gerar(state, state.verificacoes)
    return {
        "status": "entrega",
        "workflow_stage": "entrega",
        "output_docx_path": output_path,
    }


def build_adversarial_graph(
    *,
    contraparte_fn: Callable[[RatioEscritorioState], dict[str, Any]] | None = None,
    anti_sycophancy_fn: Callable[[RatioEscritorioState], dict[str, Any]] | None = None,
    redator_revisao_fn: Callable[[RatioEscritorioState], dict[str, Any]] | None = None,
    verificador_fn: Callable[[RatioEscritorioState], dict[str, Any]] | None = None,
    formatador_fn: Callable[[RatioEscritorioState], dict[str, Any]] | None = None,
    sycophancy_router_fn: Callable[[RatioEscritorioState], str] | None = None,
    decisao_fn: Callable[[RatioEscritorioState], str] | None = None,
    enable_interrupts: bool = True,
):
    graph = StateGraph(RatioEscritorioState)
    graph.add_node("contraparte", contraparte_fn or contraparte_node)
    graph.add_node("anti_sycophancy", anti_sycophancy_fn or anti_sycophancy_node)
    graph.add_node("pausa_humana", pausa_humana_node)
    graph.add_node("redator_revisao", redator_revisao_fn or redator_revisao_node)
    graph.add_node("verificador", verificador_fn or verificador_node)
    graph.add_node("formatador", formatador_fn or formatador_node)

    graph.add_edge(START, "contraparte")
    graph.add_edge("contraparte", "anti_sycophancy")
    graph.add_conditional_edges(
        "anti_sycophancy",
        sycophancy_router_fn or sycophancy_router,
        {
            "aceita": "pausa_humana",
            "rejeita": "contraparte",
        },
    )
    graph.add_conditional_edges(
        "pausa_humana",
        decisao_fn or decisao_advogado_router,
        {"mais_rodada": "redator_revisao", "finalizar": "verificador"},
    )
    graph.add_edge("redator_revisao", "contraparte")
    graph.add_edge("verificador", "formatador")
    graph.add_edge("formatador", END)

    interrupt_before = ["pausa_humana"] if enable_interrupts else []
    return graph.compile(interrupt_before=interrupt_before)

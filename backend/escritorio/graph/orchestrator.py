from __future__ import annotations

import inspect
import logging
from typing import Any

from backend.escritorio.models import RatioEscritorioState

log = logging.getLogger(__name__)


def _apply_delta(state: RatioEscritorioState, delta: dict[str, Any] | RatioEscritorioState | None) -> RatioEscritorioState:
    if delta is None:
        return state
    if isinstance(delta, RatioEscritorioState):
        return delta
    if not isinstance(delta, dict) or not delta:
        return state
    merged = state.model_dump()
    merged.update(delta)
    return RatioEscritorioState.model_validate(merged)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def run_intake_graph(state: RatioEscritorioState, store) -> RatioEscritorioState:
    """Run intake analysis once and stop at the triage confirmation."""
    from backend.escritorio.graph.intake_graph import build_intake_graph

    log.info("orchestrator: running intake graph for caso=%s", state.caso_id)
    result = RatioEscritorioState.model_validate(
        await build_intake_graph(
            enable_interrupts=False,
            gate1_router_fn=lambda _: "drafting",
        ).ainvoke(state)
    )
    store.save_snapshot(result, stage=result.status)
    log.info("orchestrator: intake complete - status=%s", result.status)
    return result


async def run_drafting_graph(state: RatioEscritorioState, store) -> RatioEscritorioState:
    """Run drafting nodes sequentially with snapshots between steps.

    This replaces the previous single ``ainvoke`` call so that:
      * the frontend (polling the snapshot) can see partial progress;
      * a failure in the redator does not discard the research work.
    """
    from backend.escritorio.graph.drafting_graph import (
        curadoria_node,
        pesquisador_node,
        redator_node,
    )

    log.info("orchestrator: running drafting graph for caso=%s", state.caso_id)

    # 1. Pesquisa (slow — multiple searches per tese)
    delta = await _maybe_await(pesquisador_node(state))
    state = _apply_delta(state, delta)
    store.save_snapshot(state, stage="pesquisa")
    log.info("orchestrator: pesquisador done - %d teses, %d juris, %d leis",
             len(state.teses or []),
             len(state.pesquisa_jurisprudencia or []),
             len(state.pesquisa_legislacao or []))

    # 2. Curadoria (dedup)
    delta = await _maybe_await(curadoria_node(state))
    state = _apply_delta(state, delta)
    store.save_snapshot(state, stage="curadoria")

    # 3. Auto-approve gate2 in non-interactive pipeline (mirrors previous router)
    state = state.model_copy(update={
        "gate2_aprovado": True,
        "status": "redacao",
        "workflow_stage": "redacao",
    })
    store.save_snapshot(state, stage="redacao")

    # 4. Redator (slow — LLM generation per section)
    delta = await _maybe_await(redator_node(state))
    state = _apply_delta(state, delta)
    store.save_snapshot(state, stage=state.status)
    log.info("orchestrator: drafting complete - status=%s", state.status)
    return state


async def run_adversarial_graph(state: RatioEscritorioState, store) -> RatioEscritorioState:
    """Run one critique/verificacao/finalizacao pass with snapshots per node."""
    from backend.escritorio.graph.adversarial_graph import (
        anti_sycophancy_node,
        contraparte_node,
        formatador_node,
        sycophancy_router,
        verificador_node,
    )

    log.info("orchestrator: running adversarial graph for caso=%s", state.caso_id)

    # Critique loop — matches the graph's contraparte/anti_sycophancy cycle,
    # but bounded to a small number of retries so we never spin forever.
    max_critique_attempts = 3
    for attempt in range(max_critique_attempts):
        delta = await _maybe_await(contraparte_node(state))
        state = _apply_delta(state, delta)
        store.save_snapshot(state, stage="adversarial")

        delta = await _maybe_await(anti_sycophancy_node(state))
        state = _apply_delta(state, delta)
        store.save_snapshot(state, stage="adversarial")

        decision = sycophancy_router(state)
        log.info("orchestrator: sycophancy_router attempt=%d decision=%s", attempt + 1, decision)
        if decision == "aceita":
            break

    # Verificacao
    delta = await _maybe_await(verificador_node(state))
    state = _apply_delta(state, delta)
    store.save_snapshot(state, stage="verificacao")

    # Formatacao (gera DOCX final)
    delta = await _maybe_await(formatador_node(state))
    state = _apply_delta(state, delta)
    store.save_snapshot(state, stage=state.status)
    log.info("orchestrator: adversarial complete - status=%s", state.status)
    return state


async def run_escritorio_pipeline(
    *,
    store,
    run_intake_graph_fn=run_intake_graph,
    run_drafting_graph_fn=run_drafting_graph,
    run_adversarial_graph_fn=run_adversarial_graph,
) -> RatioEscritorioState:
    async def _invoke_stage(fn, state: RatioEscritorioState):
        result = fn(state, store)
        if inspect.isawaitable(result):
            return await result
        return result

    def _append_event(event_type: str, payload: dict) -> None:
        append = getattr(store, "append_event", None)
        if callable(append):
            append(event_type, payload)

    state = store.load_latest_state()
    if state is None:
        raise ValueError("Store sem state inicial carregado.")

    try:
        if not state.gate1_aprovado:
            _append_event(
                "pipeline.stage_started",
                {"stage": "intake", "workflow_stage": state.workflow_stage, "status": state.status},
            )
            state = await _invoke_stage(run_intake_graph_fn, state)
            _append_event(
                "pipeline.stage_completed",
                {"stage": "intake", "workflow_stage": state.workflow_stage, "status": state.status},
            )

        if state.gate1_aprovado and not state.gate2_aprovado:
            _append_event(
                "pipeline.stage_started",
                {"stage": "drafting", "workflow_stage": state.workflow_stage, "status": state.status},
            )
            state = await _invoke_stage(run_drafting_graph_fn, state)
            _append_event(
                "pipeline.stage_completed",
                {"stage": "drafting", "workflow_stage": state.workflow_stage, "status": state.status},
            )

        if state.gate2_aprovado and not state.peca_sections:
            _append_event(
                "pipeline.stage_started",
                {"stage": "redaction", "workflow_stage": state.workflow_stage, "status": state.status},
            )
            state = await _invoke_stage(run_drafting_graph_fn, state)
            _append_event(
                "pipeline.stage_completed",
                {"stage": "redaction", "workflow_stage": state.workflow_stage, "status": state.status},
            )

        if state.gate2_aprovado and state.peca_sections and not state.usuario_finaliza:
            _append_event(
                "pipeline.stage_started",
                {"stage": "adversarial", "workflow_stage": state.workflow_stage, "status": state.status},
            )
            state = await _invoke_stage(run_adversarial_graph_fn, state)
            _append_event(
                "pipeline.stage_completed",
                {"stage": "adversarial", "workflow_stage": state.workflow_stage, "status": state.status},
            )
    except Exception as exc:
        _append_event(
            "pipeline.error",
            {"error_type": type(exc).__name__, "message": str(exc)},
        )
        raise

    return state

from __future__ import annotations

import inspect
import logging

from backend.escritorio.models import RatioEscritorioState

log = logging.getLogger(__name__)


async def run_intake_graph(state: RatioEscritorioState, store) -> RatioEscritorioState:
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
    from backend.escritorio.graph.drafting_graph import build_drafting_graph

    log.info("orchestrator: running drafting graph for caso=%s", state.caso_id)
    result = RatioEscritorioState.model_validate(
        await build_drafting_graph(
            enable_interrupts=False,
            gate2_router_fn=lambda _: "redigir",
        ).ainvoke(state)
    )
    store.save_snapshot(result, stage=result.status)
    log.info("orchestrator: drafting complete - status=%s", result.status)
    return result


async def run_adversarial_graph(state: RatioEscritorioState, store) -> RatioEscritorioState:
    from backend.escritorio.graph.adversarial_graph import build_adversarial_graph

    log.info("orchestrator: running adversarial graph for caso=%s", state.caso_id)
    result = RatioEscritorioState.model_validate(
        await build_adversarial_graph(
            enable_interrupts=False,
            decisao_fn=lambda _: "finalizar",
        ).ainvoke(state)
    )
    store.save_snapshot(result, stage=result.status)
    log.info("orchestrator: adversarial complete - status=%s", result.status)
    return result


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
            state = await _invoke_stage(run_intake_graph_fn, state)
            _append_event(
                "pipeline.stage_completed",
                {"stage": "intake", "workflow_stage": state.workflow_stage, "status": state.status},
            )

        if state.gate1_aprovado and not state.gate2_aprovado:
            state = await _invoke_stage(run_drafting_graph_fn, state)
            _append_event(
                "pipeline.stage_completed",
                {"stage": "drafting", "workflow_stage": state.workflow_stage, "status": state.status},
            )

        if state.gate2_aprovado and not state.usuario_finaliza:
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

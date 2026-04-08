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
    """Pesquisa + curadoria only. Stops at gate2 for human review.

    The redator runs separately in run_redacao_graph, after the user
    approves the research results via the gate2 UI.
    """
    from backend.escritorio.graph.drafting_graph import (
        curadoria_node,
        pesquisar_teses,
    )

    def _evt(event_type: str, payload: dict) -> None:
        append = getattr(store, "append_event", None)
        if callable(append):
            append(event_type, payload)

    log.info("orchestrator: run_drafting_graph (pesquisa) for caso=%s", state.caso_id)

    # -- Theo starts
    _evt("pesquisador.started", {
        "agent": "pesquisador",
        "text": "Iniciando pesquisa jurisprudencial...",
    })

    # 1. Pesquisa (slow — multiple searches per tese)
    working_state = state

    async def _on_tese_result(partial_delta: dict[str, Any]) -> None:
        nonlocal working_state
        working_state = _apply_delta(working_state, partial_delta)
        store.save_snapshot(working_state, stage="pesquisa")

        latest_tese = (partial_delta.get("teses") or [])[-1] if partial_delta.get("teses") else None
        if isinstance(latest_tese, dict):
            _evt("pesquisador.tese_pronta", {
                "agent": "pesquisador",
                "text": f"Tese pronta: {latest_tese.get('descricao', 'tese')}",
                "tese_id": latest_tese.get("id"),
                "tipo": latest_tese.get("tipo"),
                "resposta_pesquisa": latest_tese.get("resposta_pesquisa", ""),
            })

    delta = await pesquisar_teses(working_state, on_tese_result=_on_tese_result)
    state = _apply_delta(working_state, delta)
    store.save_snapshot(state, stage="pesquisa")

    n_teses = len(state.teses or [])
    n_juris = len(state.pesquisa_jurisprudencia or [])
    n_leis  = len(state.pesquisa_legislacao or [])
    log.info("orchestrator: pesquisador done - %d teses, %d juris, %d leis", n_teses, n_juris, n_leis)
    _evt("pesquisador.search_done", {
        "agent": "pesquisador",
        "text": f"{n_teses} teses · {n_juris} precedentes · {n_leis} dispositivos legais",
        "teses_count": n_teses,
        "juris_count": n_juris,
        "leis_count": n_leis,
    })

    # 2. Curadoria (dedup + rerank)
    delta = await _maybe_await(curadoria_node(state))
    state = _apply_delta(state, delta)
    store.save_snapshot(state, stage="curadoria")

    # 3. Signal gate2 — wait for human approval (frontend detects status="gate2")
    _evt("pesquisador.gate2_ready", {
        "agent": "pesquisador",
        "text": "Pesquisa concluída. Aguardando revisão.",
    })
    log.info("orchestrator: pesquisa done — status=%s (aguardando gate2)", state.status)
    return state


async def run_redacao_graph(state: RatioEscritorioState, store) -> RatioEscritorioState:
    """Redação only. Runs after gate2 is approved by the user."""
    from backend.escritorio.graph.drafting_graph import redator_node

    def _evt(event_type: str, payload: dict) -> None:
        append = getattr(store, "append_event", None)
        if callable(append):
            append(event_type, payload)

    log.info("orchestrator: run_redacao_graph for caso=%s", state.caso_id)
    _evt("redator.started", {
        "agent": "redator",
        "text": "Iniciando redação da peça...",
    })

    delta = await _maybe_await(redator_node(state))
    state = _apply_delta(state, delta)
    store.save_snapshot(state, stage=state.status)

    _evt("redator.done", {
        "agent": "redator",
        "text": f"Peça redigida — {len(state.peca_sections or {})} seções.",
    })
    log.info("orchestrator: redação complete - status=%s", state.status)
    return state


async def run_adversarial_graph(state: RatioEscritorioState, store) -> RatioEscritorioState:
    """Run one adversarial step.

    When ``usuario_finaliza`` is false, generate/register critique and stop for
    human review. After the user finalizes, rerun this stage to execute
    verificacao + formatacao only.
    """
    from backend.escritorio.graph.adversarial_graph import (
        anti_sycophancy_node,
        contraparte_node,
        formatador_node,
        sycophancy_router,
        verificador_node,
    )
    from backend.escritorio.adversarial import register_critique_round

    log.info("orchestrator: running adversarial graph for caso=%s", state.caso_id)

    if state.usuario_finaliza:
        delta = await _maybe_await(verificador_node(state))
        state = _apply_delta(state, delta)
        store.save_snapshot(state, stage="verificacao")

        delta = await _maybe_await(formatador_node(state))
        state = _apply_delta(state, delta)
        store.save_snapshot(state, stage=state.status)
        log.info("orchestrator: adversarial finalization complete - status=%s", state.status)
        return state

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
            if state.critica_atual is not None:
                payload = (
                    state.critica_atual.model_dump(mode="json")
                    if hasattr(state.critica_atual, "model_dump")
                    else state.critica_atual
                )
                state = register_critique_round(state, critique_payload=payload)
            state = state.model_copy(update={
                "status": "revisao_humana",
                "workflow_stage": "revisao_humana",
            })
            store.save_snapshot(state, stage="revisao_humana")
            log.info("orchestrator: adversarial critique complete - aguardando revisao humana")
            return state

    state = state.model_copy(update={
        "status": "revisao_humana",
        "workflow_stage": "revisao_humana",
    })
    store.save_snapshot(state, stage="revisao_humana")
    log.info("orchestrator: adversarial ended sem critica valida - aguardando revisao humana")
    return state


async def run_escritorio_pipeline(
    *,
    store,
    run_intake_graph_fn=run_intake_graph,
    run_drafting_graph_fn=run_drafting_graph,
    run_redacao_graph_fn=run_redacao_graph,
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

        # Pesquisa: runs until gate2 and stops for human review
        if state.gate1_aprovado and not state.gate2_aprovado:
            _append_event(
                "pipeline.stage_started",
                {"stage": "pesquisa", "workflow_stage": state.workflow_stage, "status": state.status},
            )
            state = await _invoke_stage(run_drafting_graph_fn, state)
            _append_event(
                "pipeline.stage_completed",
                {"stage": "pesquisa", "workflow_stage": state.workflow_stage, "status": state.status},
            )

        # Redação: only after user approves gate2
        if state.gate2_aprovado and not state.peca_sections:
            _append_event(
                "pipeline.stage_started",
                {"stage": "redacao", "workflow_stage": state.workflow_stage, "status": state.status},
            )
            state = await _invoke_stage(run_redacao_graph_fn, state)
            _append_event(
                "pipeline.stage_completed",
                {"stage": "redacao", "workflow_stage": state.workflow_stage, "status": state.status},
            )
            return state

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
            return state

        if state.gate2_aprovado and state.peca_sections and state.usuario_finaliza:
            _append_event(
                "pipeline.stage_started",
                {"stage": "entrega", "workflow_stage": state.workflow_stage, "status": state.status},
            )
            state = await _invoke_stage(run_adversarial_graph_fn, state)
            _append_event(
                "pipeline.stage_completed",
                {"stage": "entrega", "workflow_stage": state.workflow_stage, "status": state.status},
            )
            return state
    except Exception as exc:
        _append_event(
            "pipeline.error",
            {"error_type": type(exc).__name__, "message": str(exc)},
        )
        raise

    return state

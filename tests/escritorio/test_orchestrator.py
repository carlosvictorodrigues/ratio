import pytest

from backend.escritorio.graph.orchestrator import run_escritorio_pipeline
from backend.escritorio.models import RatioEscritorioState


class _FakeStore:
    def __init__(self, state: RatioEscritorioState):
        self._state = state
        self.saved = []
        self.events = []

    def load_latest_state(self):
        return self._state

    def save_snapshot(self, state: RatioEscritorioState, *, stage: str):
        self._state = state
        self.saved.append((stage, state.workflow_stage))

    def append_event(self, event_type: str, payload: dict):
        self.events.append((event_type, payload))


@pytest.mark.anyio
async def test_orchestrator_runs_intake_when_gate1_not_approved():
    initial = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")
    store = _FakeStore(initial)

    async def fake_run_intake_graph(state, store):  # noqa: ARG001
        updated = state.model_copy(deep=True)
        updated.gate1_aprovado = True
        updated.status = "pesquisa"
        updated.workflow_stage = "pesquisa"
        return updated

    result = await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=fake_run_intake_graph,
        run_drafting_graph_fn=lambda state, store: state,
        run_adversarial_graph_fn=lambda state, store: state,
    )

    assert result.gate1_aprovado is True
    assert result.workflow_stage == "pesquisa"


@pytest.mark.anyio
async def test_orchestrator_runs_drafting_and_adversarial_when_gates_allow():
    initial = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        gate2_aprovado=True,
        status="redacao",
        workflow_stage="redacao",
    )
    store = _FakeStore(initial)

    async def fake_drafting(state, store):  # noqa: ARG001
        updated = state.model_copy(deep=True)
        updated.peca_sections = {"dos_fatos": "texto"}
        updated.workflow_stage = "redacao"
        updated.status = "redacao"
        return updated

    async def fake_adversarial(state, store):  # noqa: ARG001
        updated = state.model_copy(deep=True)
        updated.usuario_finaliza = True
        updated.workflow_stage = "entrega"
        updated.status = "entrega"
        return updated

    result = await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=lambda state, store: state,
        run_drafting_graph_fn=fake_drafting,
        run_adversarial_graph_fn=fake_adversarial,
    )

    assert result.workflow_stage == "entrega"
    assert result.usuario_finaliza is True


@pytest.mark.anyio
async def test_orchestrator_stops_at_research_confirmation_before_redaction():
    initial = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        gate2_aprovado=False,
        status="pesquisa",
        workflow_stage="pesquisa",
    )
    store = _FakeStore(initial)

    async def fake_drafting(state, store):  # noqa: ARG001
        updated = state.model_copy(deep=True)
        updated.status = "gate2"
        updated.workflow_stage = "gate2"
        return updated

    adversarial_called = {"value": False}

    async def fake_adversarial(state, store):  # noqa: ARG001
        adversarial_called["value"] = True
        return state

    result = await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=lambda state, store: state,
        run_drafting_graph_fn=fake_drafting,
        run_adversarial_graph_fn=fake_adversarial,
    )

    assert result.workflow_stage == "gate2"
    assert adversarial_called["value"] is False


@pytest.mark.anyio
async def test_orchestrator_records_stage_completion_events():
    initial = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        gate2_aprovado=True,
        status="redacao",
        workflow_stage="redacao",
    )
    store = _FakeStore(initial)

    async def fake_drafting(state, store):  # noqa: ARG001
        updated = state.model_copy(deep=True)
        updated.workflow_stage = "redacao"
        updated.status = "redacao"
        return updated

    async def fake_adversarial(state, store):  # noqa: ARG001
        updated = state.model_copy(deep=True)
        updated.usuario_finaliza = True
        updated.workflow_stage = "entrega"
        updated.status = "entrega"
        return updated

    await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=lambda state, store: state,
        run_drafting_graph_fn=fake_drafting,
        run_adversarial_graph_fn=fake_adversarial,
    )

    event_types = [event_type for event_type, _payload in store.events]
    assert "pipeline.stage_completed" in event_types


@pytest.mark.anyio
async def test_orchestrator_records_stage_started_before_long_running_step():
    initial = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        gate2_aprovado=False,
        status="pesquisa",
        workflow_stage="pesquisa",
    )
    store = _FakeStore(initial)

    async def fake_drafting(state, store):  # noqa: ARG001
        updated = state.model_copy(deep=True)
        updated.workflow_stage = "gate2"
        updated.status = "gate2"
        return updated

    await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=lambda state, store: state,
        run_drafting_graph_fn=fake_drafting,
        run_adversarial_graph_fn=lambda state, store: state,
    )

    assert store.events[0][0] == "pipeline.stage_started"
    assert store.events[0][1]["stage"] == "drafting"
    assert store.events[1][0] == "pipeline.stage_completed"

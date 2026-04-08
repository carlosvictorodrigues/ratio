import pytest

from backend.escritorio.graph.orchestrator import (
    run_adversarial_graph,
    run_drafting_graph,
    run_escritorio_pipeline,
)
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
async def test_orchestrator_runs_redacao_only_and_stops_before_adversarial():
    initial = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        gate2_aprovado=True,
        status="redacao",
        workflow_stage="redacao",
    )
    store = _FakeStore(initial)

    async def fake_redacao(state, store):  # noqa: ARG001
        updated = state.model_copy(deep=True)
        updated.peca_sections = {"dos_fatos": "texto"}
        updated.workflow_stage = "redacao"
        updated.status = "redacao"
        return updated

    adversarial_called = {"value": False}

    async def fake_adversarial(state, store):  # noqa: ARG001
        adversarial_called["value"] = True
        return state

    result = await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=lambda state, store: state,
        run_drafting_graph_fn=lambda state, store: state,
        run_redacao_graph_fn=fake_redacao,
        run_adversarial_graph_fn=fake_adversarial,
    )

    assert result.workflow_stage == "redacao"
    assert result.peca_sections == {"dos_fatos": "texto"}
    assert adversarial_called["value"] is False


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
        run_redacao_graph_fn=fake_drafting,
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
        run_redacao_graph_fn=fake_drafting,
        run_adversarial_graph_fn=fake_adversarial,
    )

    event_types = [event_type for event_type, _payload in store.events]
    assert "pipeline.stage_completed" in event_types


@pytest.mark.anyio
async def test_orchestrator_runs_verification_after_user_finalizes_revision():
    initial = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        gate2_aprovado=True,
        usuario_finaliza=True,
        peca_sections={"dos_fatos": "texto"},
        status="verificacao",
        workflow_stage="verificacao",
    )
    store = _FakeStore(initial)
    calls = {"count": 0}

    async def fake_adversarial(state, store):  # noqa: ARG001
        calls["count"] += 1
        updated = state.model_copy(deep=True)
        updated.output_docx_path = "casos/caso-1/output/peticao_final.docx"
        updated.status = "entrega"
        updated.workflow_stage = "entrega"
        return updated

    result = await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=lambda state, store: state,
        run_drafting_graph_fn=lambda state, store: state,
        run_redacao_graph_fn=lambda state, store: state,
        run_adversarial_graph_fn=fake_adversarial,
    )

    assert calls["count"] == 1
    assert result.workflow_stage == "entrega"
    assert result.output_docx_path.endswith("peticao_final.docx")


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
    assert store.events[0][1]["stage"] == "pesquisa"
    assert store.events[1][0] == "pipeline.stage_completed"


@pytest.mark.anyio
async def test_run_drafting_graph_saves_snapshot_after_each_completed_tese(monkeypatch):
    initial = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        status="pesquisa",
        workflow_stage="pesquisa",
        teses=[
            {"id": "t1", "descricao": "CDC", "tipo": "principal"},
            {"id": "t2", "descricao": "Dano moral", "tipo": "subsidiaria"},
        ],
    )
    store = _FakeStore(initial)

    async def fake_pesquisar_teses(state, **kwargs):  # noqa: ARG001
        on_tese_result = kwargs["on_tese_result"]
        await on_tese_result(
            {
                "teses": [
                    {
                        "id": "t1",
                        "descricao": "CDC",
                        "tipo": "principal",
                        "resposta_pesquisa": "Texto CDC",
                        "jurisprudencia_favoravel": [],
                        "jurisprudencia_contraria": [],
                        "legislacao": [],
                    }
                ],
                "pesquisa_jurisprudencia": [],
                "pesquisa_legislacao": [],
                "status": "pesquisa",
                "workflow_stage": "pesquisa",
            }
        )
        await on_tese_result(
            {
                "teses": [
                    {
                        "id": "t1",
                        "descricao": "CDC",
                        "tipo": "principal",
                        "resposta_pesquisa": "Texto CDC",
                        "jurisprudencia_favoravel": [],
                        "jurisprudencia_contraria": [],
                        "legislacao": [],
                    },
                    {
                        "id": "t2",
                        "descricao": "Dano moral",
                        "tipo": "subsidiaria",
                        "resposta_pesquisa": "Texto Dano moral",
                        "jurisprudencia_favoravel": [],
                        "jurisprudencia_contraria": [],
                        "legislacao": [],
                    },
                ],
                "pesquisa_jurisprudencia": [],
                "pesquisa_legislacao": [],
                "status": "pesquisa",
                "workflow_stage": "pesquisa",
            }
        )
        return {
            "teses": [
                {
                    "id": "t1",
                    "descricao": "CDC",
                    "tipo": "principal",
                    "resposta_pesquisa": "Texto CDC",
                    "jurisprudencia_favoravel": [],
                    "jurisprudencia_contraria": [],
                    "legislacao": [],
                },
                {
                    "id": "t2",
                    "descricao": "Dano moral",
                    "tipo": "subsidiaria",
                    "resposta_pesquisa": "Texto Dano moral",
                    "jurisprudencia_favoravel": [],
                    "jurisprudencia_contraria": [],
                    "legislacao": [],
                },
            ],
            "pesquisa_jurisprudencia": [],
            "pesquisa_legislacao": [],
            "status": "pesquisa",
            "workflow_stage": "pesquisa",
        }

    monkeypatch.setattr(
        "backend.escritorio.graph.drafting_graph.pesquisar_teses",
        fake_pesquisar_teses,
    )

    result = await run_drafting_graph(initial, store)

    pesquisa_snapshots = [item for item in store.saved if item[0] == "pesquisa"]
    assert len(pesquisa_snapshots) >= 2
    assert result.workflow_stage == "gate2"
    assert result.teses[0].resposta_pesquisa == "Texto CDC"
    assert result.teses[1].resposta_pesquisa == "Texto Dano moral"


@pytest.mark.anyio
async def test_run_adversarial_graph_registers_round_and_stops_for_human_review(monkeypatch):
    initial = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        gate2_aprovado=True,
        peca_sections={"dos_fatos": "texto"},
        status="redacao",
        workflow_stage="redacao",
    )
    store = _FakeStore(initial)

    async def fake_contraparte_node(state):  # noqa: ARG001
        return {
            "status": "adversarial",
            "workflow_stage": "adversarial",
            "critica_atual": {
                "falhas_processuais": [
                    {
                        "descricao": "falta data",
                        "argumento_contrario": "ataque",
                        "secao_afetada": "dos_fatos",
                    }
                ],
                "argumentos_materiais_fracos": [],
                "jurisprudencia_faltante": [],
                "score_de_risco": 40,
                "analise_contestacao": "ha problema",
                "recomendacao": "revisar",
            },
        }

    monkeypatch.setattr(
        "backend.escritorio.graph.adversarial_graph.contraparte_node",
        fake_contraparte_node,
    )
    monkeypatch.setattr(
        "backend.escritorio.graph.adversarial_graph.anti_sycophancy_node",
        lambda state: {"status": "adversarial", "workflow_stage": "adversarial", "contraparte_retries": 0},
    )
    monkeypatch.setattr(
        "backend.escritorio.graph.adversarial_graph.sycophancy_router",
        lambda state: "aceita",
    )

    result = await run_adversarial_graph(initial, store)

    assert result.workflow_stage == "revisao_humana"
    assert result.rodada_atual == 1
    assert len(result.rodadas) == 1
    assert result.critica_atual is not None


@pytest.mark.anyio
async def test_run_adversarial_graph_appends_new_round_after_human_review(monkeypatch):
    previous_round = {
        "numero": 1,
        "resumo_rodada": "primeira rodada",
        "critica_contraparte": {
            "falhas_processuais": [],
            "argumentos_materiais_fracos": [
                {
                    "finding_id": "r1-argumentos_materiais_fracos-1",
                    "descricao": "fragilidade inicial",
                    "argumento_contrario": "ataque inicial",
                    "secao_afetada": "dos_fatos",
                }
            ],
            "jurisprudencia_faltante": [],
            "score_de_risco": 55,
            "analise_contestacao": "ha problema",
            "recomendacao": "revisar",
        },
        "secoes_revisadas": ["dos_fatos"],
        "edicoes_humanas": {"dos_fatos": "texto revisado"},
    }
    initial = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        gate2_aprovado=True,
        peca_sections={"dos_fatos": "texto revisado"},
        rodada_atual=1,
        rodadas=[previous_round],
        critica_atual=previous_round["critica_contraparte"],
        status="revisao_humana",
        workflow_stage="revisao_humana",
        usuario_finaliza=False,
    )
    store = _FakeStore(initial)

    async def fake_contraparte_node(state):  # noqa: ARG001
        return {
            "status": "adversarial",
            "workflow_stage": "adversarial",
            "critica_atual": {
                "falhas_processuais": [],
                "argumentos_materiais_fracos": [
                    {
                        "descricao": "nova fragilidade",
                        "argumento_contrario": "novo ataque",
                        "secao_afetada": "do_direito",
                    }
                ],
                "jurisprudencia_faltante": [],
                "score_de_risco": 25,
                "analise_contestacao": "melhorou, mas ainda ha risco",
                "recomendacao": "revisar",
            },
        }

    monkeypatch.setattr(
        "backend.escritorio.graph.adversarial_graph.contraparte_node",
        fake_contraparte_node,
    )
    monkeypatch.setattr(
        "backend.escritorio.graph.adversarial_graph.anti_sycophancy_node",
        lambda state: {"status": "adversarial", "workflow_stage": "adversarial", "contraparte_retries": 0},
    )
    monkeypatch.setattr(
        "backend.escritorio.graph.adversarial_graph.sycophancy_router",
        lambda state: "aceita",
    )

    result = await run_adversarial_graph(initial, store)

    assert result.workflow_stage == "revisao_humana"
    assert result.rodada_atual == 2
    assert len(result.rodadas) == 2
    assert result.rodadas[0].numero == 1
    assert result.rodadas[1].numero == 2
    assert result.rodadas[1].critica_contraparte.argumentos_materiais_fracos[0].descricao == "nova fragilidade"

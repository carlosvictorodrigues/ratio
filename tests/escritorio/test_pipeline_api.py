from pathlib import Path

from fastapi.testclient import TestClient

from backend.escritorio.store import CaseIndex, CaseStore
from backend.main import app


def test_pipeline_run_endpoint_executes_orchestrator_and_returns_pipeline_status(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_ROOT", str(tmp_path / "ratio_escritorio"))
    client = TestClient(app)

    client.post(
        "/api/escritorio/cases",
        json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"},
    )

    async def fake_run_pipeline(*, store, run_intake_graph_fn=None, run_drafting_graph_fn=None, run_adversarial_graph_fn=None):  # noqa: ARG001
        state = store.load_latest_state()
        updated = state.model_copy(deep=True)
        updated.gate1_aprovado = True
        updated.status = "pesquisa"
        updated.workflow_stage = "pesquisa"
        store.save_snapshot(updated, stage=updated.status)
        return updated

    monkeypatch.setattr(
        "backend.escritorio.api.run_escritorio_pipeline",
        fake_run_pipeline,
    )

    response = client.post("/api/escritorio/cases/caso-1/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"]["workflow_stage"] == "pesquisa"
    assert payload["pipeline"]["workflow_stage"] == "pesquisa"
    assert payload["pipeline"]["gate1_aprovado"] is True


def test_pipeline_status_endpoint_returns_current_stage(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_ROOT", str(tmp_path / "ratio_escritorio"))
    client = TestClient(app)

    client.post(
        "/api/escritorio/cases",
        json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"},
    )

    response = client.get("/api/escritorio/cases/caso-1/pipeline")

    assert response.status_code == 200
    assert response.json()["pipeline"]["workflow_stage"] == "intake"


def test_case_history_endpoints_return_events_and_snapshots(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_ROOT", str(tmp_path / "ratio_escritorio"))
    client = TestClient(app)

    client.post(
        "/api/escritorio/cases",
        json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"},
    )

    events = client.get("/api/escritorio/cases/caso-1/events")
    snapshots = client.get("/api/escritorio/cases/caso-1/snapshots")

    assert events.status_code == 200
    assert snapshots.status_code == 200
    assert events.json()["events"][0]["event_type"] == "case.created"
    assert snapshots.json()["snapshots"][0]["stage"] == "intake"


def test_case_history_events_are_enriched_for_frontend_runtime(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_ROOT", str(tmp_path / "ratio_escritorio"))
    client = TestClient(app)

    client.post(
        "/api/escritorio/cases",
        json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"},
    )
    client.post(
        "/api/escritorio/cases/caso-1/gates/gate1",
        json={"approved": True},
    )

    events = client.get("/api/escritorio/cases/caso-1/events")

    assert events.status_code == 200
    payload = events.json()["events"][-1]
    assert payload["event_type"] == "gate1.decision"
    assert payload["type_name"] == "gate1.decision"
    assert payload["agent"] == "intake"
    assert "Triagem" in payload["text"]
    assert payload["data"]["approved"] is True


def test_case_history_events_preserve_custom_agent_payload_text(monkeypatch, tmp_path: Path):
    root = tmp_path / "ratio_escritorio"
    monkeypatch.setenv("RATIO_ESCRITORIO_ROOT", str(root))
    client = TestClient(app)

    client.post(
        "/api/escritorio/cases",
        json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"},
    )

    index = CaseIndex(root)
    store = CaseStore(index.resolve_case_dir("caso-1"))
    store.append_event(
        "pesquisador.started",
        {
            "agent": "pesquisador",
            "text": "Iniciando pesquisa jurisprudencial...",
        },
    )

    events = client.get("/api/escritorio/cases/caso-1/events")

    assert events.status_code == 200
    payload = events.json()["events"][-1]
    assert payload["event_type"] == "pesquisador.started"
    assert payload["agent"] == "pesquisador"
    assert payload["text"] == "Iniciando pesquisa jurisprudencial..."
    assert payload["data"]["agent"] == "pesquisador"


def test_case_download_endpoint_returns_generated_docx(monkeypatch, tmp_path: Path):
    root = tmp_path / "ratio_escritorio"
    monkeypatch.setenv("RATIO_ESCRITORIO_ROOT", str(root))
    client = TestClient(app)

    client.post(
        "/api/escritorio/cases",
        json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"},
    )

    index = CaseIndex(root)
    store = CaseStore(index.resolve_case_dir("caso-1"))
    output_path = store.output_dir / "peticao_final.docx"
    output_path.write_bytes(b"docx-bytes")
    state = store.load_latest_state().model_copy(
        update={"output_docx_path": str(output_path), "status": "entrega", "workflow_stage": "entrega"}
    )
    store.save_snapshot(state, stage="entrega")

    response = client.get("/api/escritorio/cases/caso-1/download")

    assert response.status_code == 200
    assert response.content == b"docx-bytes"

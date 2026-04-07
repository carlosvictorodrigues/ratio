from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


def test_case_cycle_can_create_case_progress_intake_and_approve_gate(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_DB_PATH", str(tmp_path / "escritorio_cases.db"))
    client = TestClient(app)

    created = client.post(
        "/api/escritorio/cases",
        json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"},
    )
    assert created.status_code == 201

    intake = client.post(
        "/api/escritorio/cases/caso-1/intake",
        json={"message": "Sou autora e tenho contrato, boletos e historico da cobranca indevida."},
    )
    assert intake.status_code == 200
    assert intake.json()["state"]["status"] in {"intake", "gate1"}

    gate = client.post(
        "/api/escritorio/cases/caso-1/gates/gate1",
        json={"approved": True},
    )
    assert gate.status_code == 200
    assert gate.json()["state"]["gate1_aprovado"] is True
    assert gate.json()["state"]["status"] == "pesquisa"

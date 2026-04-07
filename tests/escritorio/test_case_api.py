from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


def test_case_api_creates_case_and_returns_summary(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_DB_PATH", str(tmp_path / "escritorio_cases.db"))
    client = TestClient(app)

    response = client.post(
        "/api/escritorio/cases",
        json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial", "area_direito": "Civil"},
    )

    assert response.status_code == 201
    assert response.json()["caso_id"] == "caso-1"


def test_case_api_uses_root_directory_with_one_db_per_case(monkeypatch, tmp_path: Path):
    root_dir = tmp_path / "ratio_escritorio"
    monkeypatch.delenv("RATIO_ESCRITORIO_DB_PATH", raising=False)
    monkeypatch.setenv("RATIO_ESCRITORIO_ROOT", str(root_dir))
    client = TestClient(app)

    response = client.post(
        "/api/escritorio/cases",
        json={"caso_id": "Caso 1", "tipo_peca": "peticao_inicial", "area_direito": "Civil"},
    )

    assert response.status_code == 201
    assert (root_dir / "index.db").exists()
    assert (root_dir / "casos" / "caso_1" / "caso.db").exists()

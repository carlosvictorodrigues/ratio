from fastapi.testclient import TestClient

from backend.main import app


def test_escritorio_health_endpoint_is_available():
    client = TestClient(app)
    response = client.get("/api/escritorio/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

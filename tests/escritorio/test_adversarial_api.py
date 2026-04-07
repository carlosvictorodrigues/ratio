from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


def test_adversarial_api_can_register_critique_and_dismiss_finding(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_DB_PATH", str(tmp_path / "escritorio_cases.db"))
    client = TestClient(app)

    client.post("/api/escritorio/cases", json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"})
    client.post("/api/escritorio/cases/caso-1/draft", json={"sections": {"fatos": "rascunho"}})

    critique = client.post(
        "/api/escritorio/cases/caso-1/adversarial/critique",
        json={
            "falhas_processuais": [
                {
                    "secao_afetada": "fatos",
                    "descricao": "falta data",
                    "argumento_contrario": "ataque",
                    "query_jurisprudencia_contraria": "falta data peticao",
                }
            ],
            "argumentos_materiais_fracos": [],
            "jurisprudencia_faltante": [],
            "score_de_risco": 40,
            "analise_contestacao": "ha problema",
            "recomendacao": "revisar",
        },
    )
    assert critique.status_code == 200

    finding_id = critique.json()["state"]["critica_atual"]["falhas_processuais"][0]["finding_id"]
    dismissed = client.post(
        "/api/escritorio/cases/caso-1/adversarial/dismiss",
        json={"finding_ids": [finding_id], "reason": "descartado pelo advogado"},
    )

    assert dismissed.status_code == 200
    assert dismissed.json()["state"]["rodadas"][-1]["dismissed_findings"][0]["finding_id"] == finding_id

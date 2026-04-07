from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


def test_adversarial_cycle_can_revise_sections_after_human_dismiss(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_DB_PATH", str(tmp_path / "escritorio_cases.db"))
    client = TestClient(app)

    client.post("/api/escritorio/cases", json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"})
    client.post("/api/escritorio/cases/caso-1/draft", json={"sections": {"fatos": "texto inicial"}})

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
    finding_id = critique.json()["state"]["critica_atual"]["falhas_processuais"][0]["finding_id"]

    client.post(
        "/api/escritorio/cases/caso-1/adversarial/dismiss",
        json={"finding_ids": [finding_id], "reason": "nao usar"},
    )

    revise = client.post(
        "/api/escritorio/cases/caso-1/adversarial/revise",
        json={
            "section_updates": {"fatos": "texto revisado"},
            "notes": "preservar meu estilo",
            "finalize": False,
        },
    )

    assert revise.status_code == 200
    assert revise.json()["revision_payload"]["preserve_human_anchors"] is True
    assert revise.json()["state"]["peca_sections"]["fatos"] == "texto revisado"
    assert revise.json()["revision_payload"]["current_critique"]["falhas_processuais"] == []

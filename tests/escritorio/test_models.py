from backend.escritorio.models import RatioEscritorioState
from backend.escritorio.state import build_redator_revision_payload


def test_redator_revision_payload_trims_historical_rounds():
    state = RatioEscritorioState.model_validate(
        {
            "caso_id": "caso-1",
            "tipo_peca": "peticao_inicial",
            "peca_sections": {"fatos": "texto atual"},
            "rodadas": [
                {"numero": 1, "resumo_rodada": "resumo 1"},
                {"numero": 2, "resumo_rodada": "resumo 2"},
                {"numero": 3, "resumo_rodada": "resumo 3"},
            ],
            "critica_atual": {
                "falhas_processuais": [],
                "argumentos_materiais_fracos": [],
                "jurisprudencia_faltante": [],
                "score_de_risco": 35,
                "analise_contestacao": "critica da rodada 3",
                "recomendacao": "revisar",
            },
        }
    )

    payload = build_redator_revision_payload(state, max_round_summaries=2)

    assert payload["current_sections"] == {"fatos": "texto atual"}
    assert payload["current_critique"]["score_de_risco"] == 35
    assert payload["historical_round_summaries"] == ["resumo 2", "resumo 3"]

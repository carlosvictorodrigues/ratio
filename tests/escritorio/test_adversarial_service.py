import pytest

from backend.escritorio.adversarial import register_critique_round
from backend.escritorio.models import RatioEscritorioState


def test_register_critique_round_rejects_empty_sycophantic_result():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    with pytest.raises(ValueError):
        register_critique_round(
            state,
            critique_payload={
                "falhas_processuais": [],
                "argumentos_materiais_fracos": [],
                "jurisprudencia_faltante": [],
                "score_de_risco": 0,
                "analise_contestacao": "nenhum problema",
                "recomendacao": "aprovar",
            },
        )

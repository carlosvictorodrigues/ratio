import pytest

from backend.escritorio.graph.drafting_graph import pesquisar_teses
from backend.escritorio.models import RatioEscritorioState, TeseJuridica


@pytest.mark.anyio
async def test_pesquisar_teses_executes_legislation_operation():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        teses=[TeseJuridica(id="t1", descricao="Responsabilidade civil por anulacao de concurso", tipo="principal")],
    )

    async def fake_search_bundle(*, favoravel_query: str, contraria_query: str | None, legislacao_operation, ratio_search_fn=None):  # noqa: ARG001
        assert contraria_query is None
        leis = await legislacao_operation()
        return {
            "jurisprudencia_favoravel": {"docs": []},
            "jurisprudencia_contraria": {"docs": []},
            "legislacao": leis,
        }

    async def fake_legislacao_search(_descricao: str):
        return [{"doc_id": "lei-1", "diploma": "CDC", "article": "14"}]

    result = await pesquisar_teses(
        state,
        search_bundle_fn=fake_search_bundle,
        legislation_search_fn=fake_legislacao_search,
    )

    assert result["pesquisa_legislacao"] == [{"doc_id": "lei-1", "diploma": "CDC", "article": "14"}]
    assert result["teses"][0]["legislacao"] == [{"doc_id": "lei-1", "diploma": "CDC", "article": "14"}]

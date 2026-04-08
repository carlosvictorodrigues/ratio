import pytest

from backend.escritorio.graph.drafting_graph import _search_legislation, pesquisar_teses
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
        legislation_query_plan_fn=lambda _state, _teses: [],
    )

    assert result["pesquisa_legislacao"] == [{"doc_id": "lei-1", "diploma": "CDC", "article": "14"}]
    assert result["teses"][0]["legislacao"] == [{"doc_id": "lei-1", "diploma": "CDC", "article": "14"}]


@pytest.mark.anyio
async def test_default_search_legislation_uses_anyio_thread_bridge(monkeypatch):
    monkeypatch.setattr(
        "backend.escritorio.graph.drafting_graph.search_google_legislation",
        lambda query, limit=10: [{"doc_id": f"lei-{query}", "limit": limit}],
    )

    result = await _search_legislation("cdc")

    assert result == [{"doc_id": "lei-cdc", "limit": 10}]


@pytest.mark.anyio
async def test_pesquisar_teses_adds_complementary_legislation_from_additional_queries():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        area_direito="consumidor",
        fatos_brutos="Autor pede gratuidade de justica e inversao do onus da prova.",
        gate1_aprovado=True,
        teses=[TeseJuridica(id="t1", descricao="Responsabilidade civil do fornecedor", tipo="principal")],
    )

    async def fake_search_bundle(*, favoravel_query: str, contraria_query: str | None, legislacao_operation, ratio_search_fn=None):  # noqa: ARG001
        leis = await legislacao_operation()
        return {
            "jurisprudencia_favoravel": {"docs": []},
            "jurisprudencia_contraria": {"docs": []},
            "legislacao": leis,
        }

    captured_queries = []

    async def fake_legislacao_search(query: str):
        captured_queries.append(query)
        return [{"doc_id": f"lei-{len(captured_queries)}", "diploma": "CPC", "article": "98"}]

    async def fake_legislation_query_plan(_state, _teses):
        return [
            {"categoria": "processual", "consulta": "gratuidade de justica CPC art 98 art 99 peticao inicial"},
            {"categoria": "material", "consulta": "onus da prova CDC art 6 VIII consumidor"},
        ]

    result = await pesquisar_teses(
        state,
        search_bundle_fn=fake_search_bundle,
        legislation_search_fn=fake_legislacao_search,
        legislation_query_plan_fn=fake_legislation_query_plan,
    )

    assert captured_queries == [
        "Responsabilidade civil do fornecedor",
        "gratuidade de justica CPC art 98 art 99 peticao inicial",
        "onus da prova CDC art 6 VIII consumidor",
    ]
    assert len(result["pesquisa_legislacao_complementar"]) == 2
    assert result["pesquisa_legislacao_complementar"][0]["categoria"] == "processual"
    assert result["pesquisa_legislacao_complementar"][1]["categoria"] == "material"
    assert len(result["pesquisa_legislacao"]) == 3

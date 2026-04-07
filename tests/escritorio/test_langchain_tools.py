import pytest

from backend.escritorio.tools.langchain_tools import (
    TOOLS_CONTRAPARTE,
    TOOLS_PESQUISADOR,
    buscar_jurisprudencia_favoravel,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_busca_favoravel_tool_returns_docs_from_ratio_adapter(monkeypatch):
    async def fake_ratio_search(query: str, **kwargs):
        assert "cdc" in query.lower()
        assert kwargs["prefer_recent"] is True
        return {
            "docs": [
                {"doc_id": "doc-1", "processo": "REsp 123"},
                {"doc_id": "doc-2", "processo": "REsp 456"},
            ]
        }

    monkeypatch.setattr(
        "backend.escritorio.tools.langchain_tools.ratio_tools.ratio_search",
        fake_ratio_search,
    )

    result = await buscar_jurisprudencia_favoravel.ainvoke(
        {"query": "cobranca indevida", "tese": "CDC", "limite": 1}
    )

    assert result == [{"doc_id": "doc-1", "processo": "REsp 123"}]


def test_langchain_tool_groups_are_exposed():
    pesquisador_names = {tool.name for tool in TOOLS_PESQUISADOR}
    contraparte_names = {tool.name for tool in TOOLS_CONTRAPARTE}

    assert "buscar_jurisprudencia_favoravel" in pesquisador_names
    assert "buscar_jurisprudencia_contraria" in pesquisador_names
    assert "buscar_legislacao" in pesquisador_names
    assert "buscar_jurisprudencia_contraria" in contraparte_names

import pytest

from backend.escritorio.graph.drafting_graph import (
    build_drafting_graph,
    curadoria_node,
    pesquisar_teses,
)
from backend.escritorio.models import RatioEscritorioState, TeseJuridica


def test_curadoria_node_deduplicates_and_ranks_research_results():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        status="pesquisa",
        pesquisa_jurisprudencia=[
            {"doc_id": "dup", "_final_score": 0.8, "data_julgamento": "2023-01-01"},
            {"doc_id": "dup", "_final_score": 0.9, "data_julgamento": "2024-01-01"},
            {"doc_id": "other", "_final_score": 0.7, "data_julgamento": "2022-01-01"},
        ],
        pesquisa_legislacao=[
            {"doc_id": "lei-1", "_final_score": 0.4, "data_julgamento": "2020-01-01"},
            {"doc_id": "lei-1", "_final_score": 0.6, "data_julgamento": "2021-01-01"},
        ],
    )

    result = curadoria_node(state)

    assert result["status"] == "gate2"
    assert result["workflow_stage"] == "gate2"
    assert [row["doc_id"] for row in result["pesquisa_jurisprudencia"]] == ["dup", "other"]
    assert [row["doc_id"] for row in result["pesquisa_legislacao"]] == ["lei-1"]


def test_drafting_graph_runs_research_curation_and_redaction():
    def fake_pesquisador(state: RatioEscritorioState):
        return {
            "teses": [{"id": "t1", "descricao": "CDC", "tipo": "principal"}],
            "pesquisa_jurisprudencia": [
                {"doc_id": "doc-1", "_final_score": 0.8, "data_julgamento": "2024-01-01"}
            ],
            "pesquisa_legislacao": [
                {"doc_id": "lei-1", "_final_score": 0.5, "data_julgamento": "2020-01-01"}
            ],
            "status": "pesquisa",
            "workflow_stage": "pesquisa",
        }

    def fake_redator(state: RatioEscritorioState):
        return {
            "peca_sections": {"dos_fatos": "texto redigido"},
            "status": "redacao",
            "workflow_stage": "redacao",
        }

    workflow = build_drafting_graph(
        pesquisador_fn=fake_pesquisador,
        redator_fn=fake_redator,
        enable_interrupts=False,
    )
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        gate2_aprovado=True,
    )

    result = workflow.invoke(state)

    assert result["workflow_stage"] == "redacao"
    assert result["status"] == "redacao"
    assert result["peca_sections"]["dos_fatos"] == "texto redigido"


def test_drafting_graph_compiles_with_gate2_interrupt():
    workflow = build_drafting_graph()

    assert "gate2" in workflow.builder.nodes
    assert workflow.interrupt_before_nodes == ["gate2"]


def test_default_redator_node_uses_real_redaction_layer(monkeypatch):
    captured = {}

    async def fake_generate_sections(current_state: RatioEscritorioState):
        captured["caso_id"] = current_state.caso_id
        return {"dos_fatos": "Conforme REsp 1.234.567/SP, texto redigido"}

    monkeypatch.setattr(
        "backend.escritorio.graph.drafting_graph.generate_sections_with_gemini",
        fake_generate_sections,
    )

    from backend.escritorio.graph.drafting_graph import redator_node

    result = redator_node(
        RatioEscritorioState(
            caso_id="caso-1",
            tipo_peca="peticao_inicial",
            pesquisa_jurisprudencia=[{"processo": "REsp 1.234.567/SP", "doc_id": "doc-1"}],
            pesquisa_legislacao=[{"doc_id": "lei-1", "diploma": "CC", "article": "186"}],
        )
    )

    assert captured["caso_id"] == "caso-1"
    assert result["peca_sections"]["dos_fatos"] == "Conforme REsp 1.234.567/SP, texto redigido"
    assert "resp_1234567" in result["proveniencia"]["dos_fatos"]
    assert "resp_1234567" in result["evidence_pack"]["dos_fatos"]
    assert result["workflow_stage"] == "redacao"


def test_drafting_graph_default_pesquisador_uses_real_decomposition_and_search(monkeypatch):
    async def fake_decompose_case_with_gemini(state: RatioEscritorioState):
        return [TeseJuridica(id="t1", descricao="CDC", tipo="principal")]

    async def fake_search_tese_bundle(*, favoravel_query: str, contraria_query: str, legislacao_operation, ratio_search_fn=None):  # noqa: ARG001
        assert favoravel_query == "CDC"
        assert contraria_query == "CDC"
        return {
            "jurisprudencia_favoravel": {
                "docs": [{"doc_id": "doc-1", "_final_score": 0.8, "data_julgamento": "2024-01-01"}]
            },
            "jurisprudencia_contraria": {
                "docs": [{"doc_id": "doc-2", "_final_score": 0.7, "data_julgamento": "2023-01-01"}]
            },
            "legislacao": [{"doc_id": "lei-1", "_final_score": 0.5, "data_julgamento": "2020-01-01"}],
        }

    def fake_redator(state: RatioEscritorioState):
        assert state.teses[0].descricao == "CDC"
        assert len(state.pesquisa_jurisprudencia) == 2
        assert len(state.pesquisa_legislacao) == 1
        return {
            "peca_sections": {"dos_fatos": "texto redigido"},
            "status": "redacao",
            "workflow_stage": "redacao",
        }

    monkeypatch.setattr(
        "backend.escritorio.graph.drafting_graph.decompose_case_with_gemini",
        fake_decompose_case_with_gemini,
    )
    monkeypatch.setattr(
        "backend.escritorio.graph.drafting_graph.search_tese_bundle",
        fake_search_tese_bundle,
    )

    workflow = build_drafting_graph(
        redator_fn=fake_redator,
        enable_interrupts=False,
        gate2_router_fn=lambda state: "redigir",
    )
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        fatos_brutos="Cobranca indevida em contrato bancario.",
        gate2_aprovado=True,
    )

    result = workflow.invoke(state)

    assert result["workflow_stage"] == "redacao"
    assert result["peca_sections"]["dos_fatos"] == "texto redigido"


@pytest.mark.anyio
async def test_pesquisar_teses_aggregates_bundle_results_into_state():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        teses=[
            TeseJuridica(id="t1", descricao="CDC", tipo="principal"),
            TeseJuridica(id="t2", descricao="Dano moral", tipo="subsidiaria"),
        ],
    )

    async def fake_search_bundle(*, favoravel_query: str, contraria_query: str, legislacao_operation, ratio_search_fn=None):  # noqa: ARG001
        return {
            "jurisprudencia_favoravel": {
                "docs": [{"doc_id": f"fav-{favoravel_query}", "_final_score": 0.9, "data_julgamento": "2024-01-01"}]
            },
            "jurisprudencia_contraria": {
                "docs": [{"doc_id": f"con-{contraria_query}", "_final_score": 0.7, "data_julgamento": "2023-01-01"}]
            },
            "legislacao": [{"doc_id": "lei-1", "_final_score": 0.5, "data_julgamento": "2020-01-01"}],
        }

    result = await pesquisar_teses(state, search_bundle_fn=fake_search_bundle)

    assert len(result["teses"]) == 2
    assert len(result["pesquisa_jurisprudencia"]) == 4
    assert len(result["pesquisa_legislacao"]) == 2
    assert result["teses"][0]["jurisprudencia_favoravel"][0]["doc_id"].startswith("fav-")


@pytest.mark.anyio
async def test_pesquisar_teses_uses_explicit_case_decomposition_before_fallback():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        fatos_brutos="Cliente relata cobranças indevidas e negativação.",
    )

    async def fake_decompose_case(current_state: RatioEscritorioState):
        assert "negativação" in current_state.fatos_brutos
        return [
            TeseJuridica(id="t1", descricao="Cobranca indevida", tipo="principal"),
            TeseJuridica(id="t2", descricao="Dano moral por negativacao", tipo="subsidiaria"),
        ]

    async def fake_search_bundle(*, favoravel_query: str, contraria_query: str, legislacao_operation, ratio_search_fn=None):  # noqa: ARG001
        return {
            "jurisprudencia_favoravel": {"docs": [{"doc_id": f"fav-{favoravel_query}", "_final_score": 0.9}]},
            "jurisprudencia_contraria": {"docs": [{"doc_id": f"con-{contraria_query}", "_final_score": 0.7}]},
            "legislacao": [],
        }

    result = await pesquisar_teses(
        state,
        decompose_case_fn=fake_decompose_case,
        search_bundle_fn=fake_search_bundle,
    )

    descricoes = [tese["descricao"] for tese in result["teses"]]
    assert descricoes == ["Cobranca indevida", "Dano moral por negativacao"]


@pytest.mark.anyio
async def test_decompose_case_into_teses_uses_default_gemini_path_when_available(monkeypatch):
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente relata cobranças indevidas e negativação.",
    )

    async def fake_gemini_decompose(current_state: RatioEscritorioState):
        assert "negativação" in current_state.fatos_brutos
        return [TeseJuridica(id="t1", descricao="Cobranca indevida", tipo="principal")]

    monkeypatch.setattr(
        "backend.escritorio.graph.drafting_graph.decompose_case_with_gemini",
        fake_gemini_decompose,
    )

    from backend.escritorio.graph.drafting_graph import decompose_case_into_teses

    teses = await decompose_case_into_teses(state)

    assert [t.id for t in teses] == ["t1"]

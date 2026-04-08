import pytest

from backend.escritorio.graph.adversarial_graph import build_adversarial_graph
from backend.escritorio.models import RatioEscritorioState


def test_adversarial_graph_compiles_with_pause_interrupt():
    workflow = build_adversarial_graph()

    assert "pausa_humana" in workflow.builder.nodes
    assert workflow.interrupt_before_nodes == ["pausa_humana"]


def test_adversarial_graph_can_finalize_after_single_critique_cycle():
    def fake_contraparte(state: RatioEscritorioState):
        return {
            "status": "adversarial",
            "workflow_stage": "adversarial",
            "critica_atual": {
                "falhas_processuais": [],
                "argumentos_materiais_fracos": [
                    {
                        "secao_afetada": "fatos",
                        "descricao": "falta robustez",
                        "argumento_contrario": "ataque",
                        "query_jurisprudencia_contraria": "falta robustez",
                    }
                ],
                "jurisprudencia_faltante": [],
                "score_de_risco": 30,
                "analise_contestacao": "ha risco",
                "recomendacao": "revisar",
            },
        }

    def fake_redator_revisao(state: RatioEscritorioState):
        return {
            "peca_sections": {"fatos": "texto revisado"},
            "status": "adversarial",
            "workflow_stage": "adversarial",
        }

    def fake_verificador(state: RatioEscritorioState):
        return {
            "status": "verificacao",
            "workflow_stage": "verificacao",
            "verificacoes": [{"referencia": "REsp 1", "level": "exact_match"}],
        }

    def fake_formatador(state: RatioEscritorioState):
        return {
            "status": "entrega",
            "workflow_stage": "entrega",
            "output_docx_path": "casos/caso-1/output/peticao.docx",
        }

    workflow = build_adversarial_graph(
        contraparte_fn=fake_contraparte,
        redator_revisao_fn=fake_redator_revisao,
        verificador_fn=fake_verificador,
        formatador_fn=fake_formatador,
        decisao_fn=lambda state: "finalizar",
        enable_interrupts=False,
    )
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    result = workflow.invoke(state)

    assert result["workflow_stage"] == "entrega"
    assert result["status"] == "entrega"
    assert result["output_docx_path"].endswith("peticao.docx")


def test_default_formatador_node_generates_docx(monkeypatch, tmp_path):
    monkeypatch.setenv("RATIO_ESCRITORIO_ROOT", str(tmp_path / "ratio_escritorio"))

    from backend.escritorio.graph.adversarial_graph import formatador_node

    result = formatador_node(
        RatioEscritorioState(
            caso_id="caso-1",
            tipo_peca="peticao_inicial",
            peca_sections={"dos_fatos": "Texto dos fatos."},
            verificacoes=[{"referencia": "REsp 1.234.567", "level": "exact_match"}],
        )
    )

    assert result["workflow_stage"] == "entrega"
    assert result["status"] == "entrega"
    assert result["output_docx_path"].endswith("peticao_final.docx")


def test_formatador_node_keeps_generating_delivery_even_when_verification_is_unverified(monkeypatch, tmp_path):
    monkeypatch.setenv("RATIO_ESCRITORIO_ROOT", str(tmp_path / "ratio_escritorio"))

    from backend.escritorio.graph.adversarial_graph import formatador_node

    result = formatador_node(
        RatioEscritorioState(
            caso_id="caso-1",
            tipo_peca="peticao_inicial",
            peca_sections={"dos_fatos": "Texto dos fatos."},
            verificacoes=[{"referencia": "Tema 512 [VERIFICAR]", "level": "unverified", "blocking": True}],
        )
    )

    assert result["workflow_stage"] == "entrega"
    assert result["status"] == "entrega"
    assert result["output_docx_path"].endswith(".docx")


def test_sycophancy_router_accepts_after_retry_limit_for_missing_critique():
    from backend.escritorio.graph.adversarial_graph import anti_sycophancy_node, sycophancy_router

    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    first_pass = state.model_copy(update=anti_sycophancy_node(state))
    assert sycophancy_router(first_pass) == "rejeita"

    second_state = first_pass.model_copy(update=anti_sycophancy_node(first_pass))
    third_state = second_state.model_copy(update=anti_sycophancy_node(second_state))

    assert third_state.contraparte_retries >= 2
    assert sycophancy_router(third_state) == "aceita"


@pytest.mark.anyio
async def test_default_contraparte_node_uses_real_contraparte_layer(monkeypatch):
    captured = {}

    async def fake_generate_critique(current_state: RatioEscritorioState):
        captured["sections"] = dict(current_state.peca_sections)
        return {
            "falhas_processuais": [],
            "argumentos_materiais_fracos": [],
            "jurisprudencia_faltante": [],
            "score_de_risco": 15,
            "analise_contestacao": "ha risco",
            "recomendacao": "revisar",
        }

    monkeypatch.setattr(
        "backend.escritorio.graph.adversarial_graph.generate_critique_with_gemini",
        fake_generate_critique,
    )

    from backend.escritorio.graph.adversarial_graph import contraparte_node

    result = await contraparte_node(
        RatioEscritorioState(
            caso_id="caso-1",
            tipo_peca="peticao_inicial",
            peca_sections={"dos_fatos": "Texto dos fatos."},
        )
    )

    assert captured["sections"]["dos_fatos"] == "Texto dos fatos."
    assert result["critica_atual"]["score_de_risco"] == 15
    assert result["workflow_stage"] == "adversarial"


@pytest.mark.anyio
async def test_default_redator_revisao_node_uses_real_revision_layer(monkeypatch):
    captured = {}

    async def fake_generate_revision(payload):
        captured["payload"] = payload
        return {"dos_fatos": "Texto revisado."}

    monkeypatch.setattr(
        "backend.escritorio.graph.adversarial_graph.generate_revision_with_gemini",
        fake_generate_revision,
    )

    from backend.escritorio.graph.adversarial_graph import redator_revisao_node

    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        peca_sections={"dos_fatos": "Texto original."},
        critica_atual={
            "falhas_processuais": [],
            "argumentos_materiais_fracos": [],
            "jurisprudencia_faltante": [],
            "score_de_risco": 30,
            "analise_contestacao": "ha risco",
            "recomendacao": "revisar",
        },
    )

    result = await redator_revisao_node(state)

    assert captured["payload"]["preserve_human_anchors"] is True
    assert result["peca_sections"]["dos_fatos"] == "Texto revisado."
    assert result["workflow_stage"] == "adversarial"


def test_default_verificador_node_uses_real_verifier_layer(monkeypatch):
    captured = {}

    def fake_verify_sections(state, *, registry, lance_dir, table_name="jurisprudencia"):  # noqa: ARG001
        captured["sections"] = dict(state.peca_sections)
        return [{"section": "do_direito", "level": "exact_match", "provenance_ok": True}]

    monkeypatch.setattr(
        "backend.escritorio.graph.adversarial_graph.verify_sections",
        fake_verify_sections,
    )

    from backend.escritorio.graph.adversarial_graph import verificador_node

    result = verificador_node(
        RatioEscritorioState(
            caso_id="caso-1",
            tipo_peca="peticao_inicial",
            peca_sections={"do_direito": "Conforme REsp 1.234.567/SP."},
        )
    )

    assert captured["sections"]["do_direito"] == "Conforme REsp 1.234.567/SP."
    assert result["verificacoes"][0]["level"] == "exact_match"
    assert result["workflow_stage"] == "verificacao"

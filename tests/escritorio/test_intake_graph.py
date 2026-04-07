import pytest

from backend.escritorio.graph.intake_graph import build_intake_graph
from backend.escritorio.models import RatioEscritorioState


def test_intake_graph_compiles_with_gate1_interrupt():
    workflow = build_intake_graph()

    assert "gate1" in workflow.builder.nodes
    assert workflow.interrupt_before_nodes == ["gate1"]


def test_intake_graph_can_advance_to_gate1_when_gate_is_approved():
    def fake_intake(state: RatioEscritorioState):
        return {
            "fatos_estruturados": ["fato 1"],
            "provas_disponiveis": ["contrato"],
            "pontos_atencao": [],
            "status": "gate1",
            "workflow_stage": "gate1",
        }

    workflow = build_intake_graph(
        intake_fn=fake_intake,
        gate1_router_fn=lambda state: "drafting",
        enable_interrupts=False,
    )
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        gate1_aprovado=True,
        fatos_brutos="Cliente relata cobrança indevida.",
    )

    result = workflow.invoke(state)

    assert result["workflow_stage"] == "gate1"
    assert result["status"] == "gate1"


def test_default_intake_node_uses_real_llm_layer(monkeypatch):
    captured = {}

    async def fake_generate_intake(current_state: RatioEscritorioState):
        captured["fatos"] = current_state.fatos_brutos
        return {
            "fatos_estruturados": ["fato llm"],
            "provas_disponiveis": ["boleto"],
            "pontos_atencao": ["prazo"],
        }

    monkeypatch.setattr(
        "backend.escritorio.graph.intake_graph.generate_intake_with_gemini",
        fake_generate_intake,
    )

    from backend.escritorio.graph.intake_graph import intake_node

    result = intake_node(
        RatioEscritorioState(
            caso_id="caso-1",
            tipo_peca="peticao_inicial",
            fatos_brutos="Cliente relata cobrança indevida.",
        )
    )

    assert captured["fatos"] == "Cliente relata cobrança indevida."
    assert result["fatos_estruturados"] == ["fato llm"]

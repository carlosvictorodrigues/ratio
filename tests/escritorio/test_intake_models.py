from backend.escritorio.models import RatioEscritorioState


def test_state_tracks_intake_history_and_gate_flags():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    assert state.intake_history == []
    assert state.resposta_conversacional_clara == ""
    assert state.perguntas_pendentes == []
    assert state.triagem_suficiente is False
    assert state.gate1_aprovado is False
    assert state.gate2_aprovado is False
    assert state.status == "intake"

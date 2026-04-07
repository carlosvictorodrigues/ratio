from backend.escritorio.models import RatioEscritorioState


def test_state_tracks_intake_history_and_gate_flags():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    assert state.intake_history == []
    assert state.gate1_aprovado is False
    assert state.gate2_aprovado is False
    assert state.status == "intake"

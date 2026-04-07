from backend.escritorio.models import RatioEscritorioState


def test_state_tracks_round_counter_and_dismissed_findings():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    assert state.rodada_atual == 0
    assert state.usuario_finaliza is False
    assert state.rodadas == []

from backend.escritorio.intake import process_intake_message
from backend.escritorio.models import RatioEscritorioState


def test_process_intake_message_updates_history_and_stays_in_intake():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    updated = process_intake_message(
        state,
        user_message="Cliente Joao relata cobranca indevida. Tenho contrato e boletos.",
    )

    assert updated.intake_history[-1].role == "user"
    assert updated.status == "intake"
    assert "cobranca indevida" in updated.fatos_brutos

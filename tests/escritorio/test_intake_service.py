from backend.escritorio.intake import process_intake_message
from backend.escritorio.models import RatioEscritorioState


def test_process_intake_message_updates_history_and_stays_intake():
    """process_intake_message never promotes to gate1 — that's intake_graph's job."""
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    updated = process_intake_message(
        state,
        user_message="Cliente Joao relata cobranca indevida. Tenho contrato e boletos.",
    )

    assert updated.intake_history[-1].role == "user"
    assert updated.intake_checklist.documentos_listados is True
    assert updated.status == "intake"  # Never gate1 — only intake_graph sets that

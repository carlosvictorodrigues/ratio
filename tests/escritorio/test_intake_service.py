from backend.escritorio.intake import process_intake_message
from backend.escritorio.models import RatioEscritorioState


def test_process_intake_message_updates_history_and_promotes_gate_when_checklist_complete():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    updated = process_intake_message(
        state,
        user_message="Cliente Joao relata cobranca indevida. Tenho contrato e boletos.",
    )

    assert updated.intake_history[-1].role == "user"
    assert updated.intake_checklist.documentos_listados is True
    assert updated.status in {"intake", "gate1"}

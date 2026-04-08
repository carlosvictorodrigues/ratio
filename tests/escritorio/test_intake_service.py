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


def test_process_intake_message_invalidates_previous_clara_analysis():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Relato inicial.",
        fatos_estruturados=["fato antigo"],
        provas_disponiveis=["contrato"],
        pontos_atencao=["confirmar reu"],
        resposta_conversacional_clara="Preciso confirmar o reu.",
        perguntas_pendentes=["Quem e o reu?"],
        triagem_suficiente=True,
        status="gate1",
        workflow_stage="gate1",
    )

    updated = process_intake_message(
        state,
        user_message="O reu e o Banco X e tambem tenho os boletos.",
    )

    assert updated.status == "intake"
    assert updated.workflow_stage == "intake"
    assert updated.fatos_estruturados == []
    assert updated.provas_disponiveis == []
    assert updated.pontos_atencao == []
    assert updated.resposta_conversacional_clara == ""
    assert updated.perguntas_pendentes == []
    assert updated.triagem_suficiente is False
    assert "Banco X" in updated.fatos_brutos

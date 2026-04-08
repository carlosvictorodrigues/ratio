from __future__ import annotations

from backend.escritorio.models import IntakeMessage, RatioEscritorioState


def process_intake_message(
    state: RatioEscritorioState,
    *,
    user_message: str,
) -> RatioEscritorioState:
    updated = state.model_copy(deep=True)
    clean_message = str(user_message or "").strip()
    if not clean_message:
        return updated

    updated.intake_history.append(IntakeMessage(role="user", content=clean_message))
    updated.fatos_brutos = "\n".join(
        part for part in [updated.fatos_brutos, clean_message] if part
    ).strip()
    updated.fatos_estruturados = []
    updated.provas_disponiveis = []
    updated.pontos_atencao = []
    updated.resposta_conversacional_clara = ""
    updated.perguntas_pendentes = []
    updated.triagem_suficiente = False
    updated.gate1_aprovado = False
    updated.status = "intake"
    updated.workflow_stage = "intake"
    return updated

from __future__ import annotations

from backend.escritorio.models import IntakeChecklist, IntakeMessage, RatioEscritorioState

_PARTY_HINTS = (
    "cliente",
    "autor",
    "autora",
    "reu",
    "re",
    "réu",
    "ré",
    "empresa",
    "banco",
)
_DOCUMENT_HINTS = (
    "contrato",
    "boleto",
    "boletos",
    "documento",
    "documentos",
    "pdf",
    "anexo",
    "anexos",
    "prova",
    "provas",
    "laudo",
)


def compute_checklist(state: RatioEscritorioState) -> IntakeChecklist:
    corpus = "\n".join(
        [state.fatos_brutos] + [message.content for message in state.intake_history]
    ).lower()
    stripped = corpus.strip()

    return IntakeChecklist(
        partes_identificadas=any(token in stripped for token in _PARTY_HINTS),
        fatos_principais_cobertos=len(stripped) >= 40,
        documentos_listados=any(token in stripped for token in _DOCUMENT_HINTS),
    )


def checklist_ready(checklist: IntakeChecklist) -> bool:
    return (
        checklist.partes_identificadas
        and checklist.fatos_principais_cobertos
        and checklist.documentos_listados
    )


def build_next_question(state: RatioEscritorioState) -> str:
    checklist = state.intake_checklist
    if not checklist.partes_identificadas:
        return "Quem sao as partes envolvidas e qual o papel de cada uma no caso?"
    if not checklist.fatos_principais_cobertos:
        return "Descreva a sequencia dos fatos com datas, valores e o que exatamente aconteceu."
    if not checklist.documentos_listados:
        return "Quais documentos, contratos, comprovantes ou anexos voce ja possui para sustentar o caso?"
    return (
        "Detectamos as partes envolvidas, o relato dos fatos e a documentacao. "
        "Quando quiser, pode pedir para a Clara analisar o caso."
    )


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
    updated.intake_checklist = compute_checklist(updated)
    updated.status = "gate1" if checklist_ready(updated.intake_checklist) else "intake"
    updated.workflow_stage = updated.status
    return updated

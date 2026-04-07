from __future__ import annotations

from typing import Any

from backend.escritorio.models import RatioEscritorioState


def build_redator_revision_payload(
    state: RatioEscritorioState,
    *,
    max_round_summaries: int = 2,
    current_critique: dict[str, Any] | None = None,
    preserve_human_anchors: bool = False,
    human_notes: str | None = None,
    edited_sections: list[str] | None = None,
) -> dict[str, Any]:
    historical_round_summaries = [
        rodada.resumo_rodada
        for rodada in state.rodadas
        if rodada.resumo_rodada
    ][-max_round_summaries:]

    payload = {
        "caso_id": state.caso_id,
        "tipo_peca": state.tipo_peca,
        "current_sections": dict(state.peca_sections),
        "current_critique": current_critique if current_critique is not None else (
            state.critica_atual.model_dump(exclude_none=True)
            if state.critica_atual is not None
            else None
        ),
        "historical_round_summaries": historical_round_summaries,
    }
    if preserve_human_anchors:
        payload["preserve_human_anchors"] = True
    if human_notes:
        payload["human_notes"] = human_notes
    if edited_sections:
        payload["edited_sections"] = list(edited_sections)
    return payload

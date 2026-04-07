from __future__ import annotations

from typing import Any

from backend.escritorio.models import (
    CriticaContraparte,
    DismissedFinding,
    RatioEscritorioState,
    RodadaAdversarial,
)
from backend.escritorio.state import build_redator_revision_payload


def _assign_finding_ids(critique: CriticaContraparte, round_number: int) -> CriticaContraparte:
    normalized = critique.model_copy(deep=True)

    for bucket_name in ("falhas_processuais", "argumentos_materiais_fracos"):
        bucket = getattr(normalized, bucket_name)
        for index, item in enumerate(bucket, start=1):
            if not item.finding_id:
                item.finding_id = f"r{round_number}-{bucket_name}-{index}"
    return normalized


def _is_empty_sycophantic_critique(critique: CriticaContraparte) -> bool:
    return (
        critique.score_de_risco == 0
        and not critique.falhas_processuais
        and not critique.argumentos_materiais_fracos
        and not critique.jurisprudencia_faltante
    )


def register_critique_round(
    state: RatioEscritorioState,
    *,
    critique_payload: dict[str, Any],
) -> RatioEscritorioState:
    critique = CriticaContraparte.model_validate(critique_payload)
    if _is_empty_sycophantic_critique(critique):
        raise ValueError("Critica vazia rejeitada por anti-sycophancy.")

    updated = state.model_copy(deep=True)
    round_number = updated.rodada_atual + 1
    normalized_critique = _assign_finding_ids(critique, round_number)

    updated.critica_atual = normalized_critique
    updated.rodada_atual = round_number
    updated.rodadas.append(
        RodadaAdversarial(
            numero=round_number,
            critica_contraparte=normalized_critique,
            resumo_rodada=normalized_critique.analise_contestacao,
        )
    )
    updated.status = "adversarial"
    updated.workflow_stage = "adversarial"
    return updated


def _current_round_or_raise(state: RatioEscritorioState) -> RodadaAdversarial:
    if not state.rodadas:
        raise ValueError("Nenhuma rodada adversarial registrada.")
    return state.rodadas[-1]


def _dismissed_ids(state: RatioEscritorioState) -> set[str]:
    current_round = _current_round_or_raise(state)
    return {item.finding_id for item in current_round.dismissed_findings}


def _filter_critique_by_dismissed(
    critique: CriticaContraparte | None,
    dismissed_ids: set[str],
) -> CriticaContraparte | None:
    if critique is None:
        return None
    normalized = critique.model_copy(deep=True)
    normalized.falhas_processuais = [
        item for item in normalized.falhas_processuais if item.finding_id not in dismissed_ids
    ]
    normalized.argumentos_materiais_fracos = [
        item for item in normalized.argumentos_materiais_fracos if item.finding_id not in dismissed_ids
    ]
    return normalized


def dismiss_findings(
    state: RatioEscritorioState,
    *,
    finding_ids: list[str],
    reason: str = "",
) -> RatioEscritorioState:
    updated = state.model_copy(deep=True)
    current_round = _current_round_or_raise(updated)
    existing_ids = {item.finding_id for item in current_round.dismissed_findings}

    for finding_id in finding_ids:
        if finding_id and finding_id not in existing_ids:
            current_round.dismissed_findings.append(
                DismissedFinding(finding_id=finding_id, reason=reason)
            )
            existing_ids.add(finding_id)

    updated.status = "revisao_humana"
    updated.workflow_stage = "revisao_humana"
    return updated


def apply_human_revision(
    state: RatioEscritorioState,
    *,
    section_updates: dict[str, str],
    notes: str = "",
    finalize: bool = False,
) -> RatioEscritorioState:
    updated = state.model_copy(deep=True)
    current_round = _current_round_or_raise(updated)

    if section_updates:
        merged_sections = dict(updated.peca_sections)
        merged_sections.update(section_updates)
        updated.peca_sections = merged_sections
        current_round.edicoes_humanas = {
            **(current_round.edicoes_humanas or {}),
            **section_updates,
        }
        current_round.secoes_revisadas = list(dict.fromkeys([
            *current_round.secoes_revisadas,
            *section_updates.keys(),
        ]))

    if notes:
        current_round.apontamentos_humanos = notes

    updated.usuario_finaliza = bool(finalize)
    updated.status = "verificacao" if finalize else "revisao_humana"
    updated.workflow_stage = updated.status
    updated.critica_atual = _filter_critique_by_dismissed(
        updated.critica_atual,
        _dismissed_ids(updated),
    )
    return updated


def submit_human_revision(
    state: RatioEscritorioState,
    *,
    section_updates: dict[str, str],
    notes: str = "",
    finalize: bool = False,
) -> dict[str, Any]:
    updated = apply_human_revision(
        state,
        section_updates=section_updates,
        notes=notes,
        finalize=finalize,
    )
    return build_redator_revision_payload(
        updated,
        current_critique=updated.critica_atual.model_dump(exclude_none=True) if updated.critica_atual else None,
        preserve_human_anchors=True,
        human_notes=notes,
        edited_sections=list(section_updates.keys()),
    )

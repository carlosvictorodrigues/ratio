from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.escritorio.adversarial import (
    apply_human_revision,
    dismiss_findings,
    register_critique_round,
    submit_human_revision,
)
from backend.escritorio.graph.orchestrator import run_escritorio_pipeline
from backend.escritorio.intake import build_next_question, process_intake_message
from backend.escritorio.store import CaseIndex, CaseStore


def _resolve_escritorio_root() -> Path:
    raw_root = (os.getenv("RATIO_ESCRITORIO_ROOT") or "").strip()
    if raw_root:
        return Path(raw_root).expanduser()

    raw = (os.getenv("RATIO_ESCRITORIO_DB_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().parent
    return Path(__file__).resolve().parents[2] / "logs" / "runtime" / "ratio_escritorio"


def _get_case_index() -> CaseIndex:
    return CaseIndex(_resolve_escritorio_root())


def _get_case_store(caso_id: str, *, index: CaseIndex | None = None) -> CaseStore:
    case_index = index or _get_case_index()
    return CaseStore(case_index.resolve_case_dir(caso_id))


class CreateCaseRequest(BaseModel):
    caso_id: str = Field(min_length=1, max_length=120)
    tipo_peca: Literal["peticao_inicial", "contestacao"]
    area_direito: str = Field(default="", max_length=120)


class IntakeTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)


class GateDecisionRequest(BaseModel):
    approved: bool


class DraftSectionsRequest(BaseModel):
    sections: dict[str, str] = Field(default_factory=dict)


class DismissFindingsRequest(BaseModel):
    finding_ids: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=1000)


class RevisionRequest(BaseModel):
    section_updates: dict[str, str] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=4000)
    finalize: bool = False


def _load_case_or_404(index: CaseIndex, caso_id: str):
    case_summary = index.get_case(caso_id)
    state = _get_case_store(caso_id, index=index).load_latest_state()
    if case_summary is None or state is None:
        raise HTTPException(status_code=404, detail={"code": "case_not_found", "caso_id": caso_id})
    return case_summary, state


def _pipeline_payload(state) -> dict[str, Any]:
    return {
        "workflow_stage": state.workflow_stage,
        "status": state.status,
        "gate1_aprovado": bool(state.gate1_aprovado),
        "gate2_aprovado": bool(state.gate2_aprovado),
        "usuario_finaliza": bool(state.usuario_finaliza),
        "rodada_atual": int(state.rodada_atual),
    }


def build_escritorio_router() -> APIRouter:
    router = APIRouter(prefix="/api/escritorio", tags=["escritorio"])

    @router.get("/health")
    def escritorio_health() -> dict[str, str]:
        return {"status": "ok", "module": "escritorio"}

    @router.post("/cases", status_code=201)
    def create_case(payload: CreateCaseRequest) -> dict[str, Any]:
        index = _get_case_index()
        case_store = _get_case_store(payload.caso_id.strip(), index=index)
        try:
            created = case_store.create_case(
                caso_id=payload.caso_id.strip(),
                tipo_peca=payload.tipo_peca,
                area_direito=payload.area_direito.strip(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "case_already_exists", "message": str(exc)}) from exc
        index.upsert_case(
            caso_id=created["caso_id"],
            tipo_peca=created["tipo_peca"],
            area_direito=created["area_direito"],
            status=created["status"],
            case_dir=case_store.case_dir,
        )
        return created

    @router.get("/cases")
    def list_cases() -> list[dict[str, Any]]:
        return _get_case_index().list_cases()

    @router.get("/cases/{caso_id}")
    def get_case(caso_id: str) -> dict[str, Any]:
        index = _get_case_index()
        summary, state = _load_case_or_404(index, caso_id)
        return {"summary": summary, "state": state.model_dump(mode="json")}

    @router.get("/cases/{caso_id}/pipeline")
    def get_pipeline_status(caso_id: str) -> dict[str, Any]:
        index = _get_case_index()
        summary, state = _load_case_or_404(index, caso_id)
        return {
            "summary": summary,
            "state": state.model_dump(mode="json"),
            "pipeline": _pipeline_payload(state),
        }

    @router.get("/cases/{caso_id}/events")
    def get_case_events(caso_id: str) -> dict[str, Any]:
        index = _get_case_index()
        summary, _state = _load_case_or_404(index, caso_id)
        store = _get_case_store(caso_id, index=index)
        return {
            "summary": summary,
            "events": store.list_events(),
        }

    @router.get("/cases/{caso_id}/snapshots")
    def get_case_snapshots(caso_id: str) -> dict[str, Any]:
        index = _get_case_index()
        summary, _state = _load_case_or_404(index, caso_id)
        store = _get_case_store(caso_id, index=index)
        return {
            "summary": summary,
            "snapshots": store.list_snapshots(),
        }

    @router.post("/cases/{caso_id}/run")
    async def run_case_pipeline(caso_id: str) -> dict[str, Any]:
        index = _get_case_index()
        store = _get_case_store(caso_id, index=index)
        summary, _state = _load_case_or_404(index, caso_id)
        updated = await run_escritorio_pipeline(store=store)
        index.upsert_case(
            caso_id=updated.caso_id,
            tipo_peca=updated.tipo_peca,
            area_direito=updated.area_direito,
            status=updated.status,
            case_dir=store.case_dir,
        )
        refreshed_summary = index.get_case(caso_id) or {**summary, "status": updated.status}
        return {
            "summary": refreshed_summary,
            "state": updated.model_dump(mode="json"),
            "pipeline": _pipeline_payload(updated),
        }

    @router.post("/cases/{caso_id}/intake")
    def post_intake_turn(caso_id: str, payload: IntakeTurnRequest) -> dict[str, Any]:
        index = _get_case_index()
        store = _get_case_store(caso_id, index=index)
        summary, state = _load_case_or_404(index, caso_id)
        updated = process_intake_message(state, user_message=payload.message)
        store.save_snapshot(updated, stage=updated.status)
        index.upsert_case(
            caso_id=updated.caso_id,
            tipo_peca=updated.tipo_peca,
            area_direito=updated.area_direito,
            status=updated.status,
            case_dir=store.case_dir,
        )
        store.append_event(
            "intake.turn",
            {
                "message": payload.message,
                "status": updated.status,
            },
        )
        return {
            "summary": {**summary, "status": updated.status},
            "state": updated.model_dump(mode="json"),
            "next_question": build_next_question(updated),
        }

    @router.post("/cases/{caso_id}/gates/{gate_name}")
    def decide_gate(caso_id: str, gate_name: str, payload: GateDecisionRequest) -> dict[str, Any]:
        normalized_gate = gate_name.strip().lower()
        if normalized_gate not in {"gate1", "gate2"}:
            raise HTTPException(status_code=400, detail={"code": "invalid_gate", "gate_name": gate_name})

        index = _get_case_index()
        store = _get_case_store(caso_id, index=index)
        summary, state = _load_case_or_404(index, caso_id)
        updated = state.model_copy(deep=True)

        if normalized_gate == "gate1":
            updated.gate1_aprovado = bool(payload.approved)
            updated.status = "pesquisa" if payload.approved else "intake"
        else:
            updated.gate2_aprovado = bool(payload.approved)
            updated.status = "redacao" if payload.approved else "pesquisa"

        updated.workflow_stage = updated.status
        store.save_snapshot(updated, stage=updated.status)
        index.upsert_case(
            caso_id=updated.caso_id,
            tipo_peca=updated.tipo_peca,
            area_direito=updated.area_direito,
            status=updated.status,
            case_dir=store.case_dir,
        )
        store.append_event(
            f"{normalized_gate}.decision",
            {"approved": bool(payload.approved), "status": updated.status},
        )

        return {
            "summary": {**summary, "status": updated.status},
            "state": updated.model_dump(mode="json"),
        }

    @router.post("/cases/{caso_id}/draft")
    def upsert_draft(caso_id: str, payload: DraftSectionsRequest) -> dict[str, Any]:
        index = _get_case_index()
        store = _get_case_store(caso_id, index=index)
        summary, state = _load_case_or_404(index, caso_id)
        updated = state.model_copy(deep=True)
        updated.peca_sections = dict(payload.sections)
        updated.status = "redacao"
        updated.workflow_stage = "redacao"
        store.save_snapshot(updated, stage=updated.status)
        index.upsert_case(
            caso_id=updated.caso_id,
            tipo_peca=updated.tipo_peca,
            area_direito=updated.area_direito,
            status=updated.status,
            case_dir=store.case_dir,
        )
        store.append_event(
            "draft.updated",
            {"sections": list(payload.sections.keys())},
        )
        return {
            "summary": {**summary, "status": updated.status},
            "state": updated.model_dump(mode="json"),
        }

    @router.post("/cases/{caso_id}/adversarial/critique")
    def register_adversarial_critique(caso_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        index = _get_case_index()
        store = _get_case_store(caso_id, index=index)
        summary, state = _load_case_or_404(index, caso_id)
        try:
            updated = register_critique_round(state, critique_payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_critique", "message": str(exc)}) from exc
        store.save_snapshot(updated, stage=updated.status)
        index.upsert_case(
            caso_id=updated.caso_id,
            tipo_peca=updated.tipo_peca,
            area_direito=updated.area_direito,
            status=updated.status,
            case_dir=store.case_dir,
        )
        store.append_event(
            "adversarial.critique_registered",
            {"rodada_atual": updated.rodada_atual},
        )
        return {
            "summary": {**summary, "status": updated.status},
            "state": updated.model_dump(mode="json"),
        }

    @router.post("/cases/{caso_id}/adversarial/dismiss")
    def dismiss_adversarial_findings(caso_id: str, payload: DismissFindingsRequest) -> dict[str, Any]:
        index = _get_case_index()
        store = _get_case_store(caso_id, index=index)
        summary, state = _load_case_or_404(index, caso_id)
        try:
            updated = dismiss_findings(
                state,
                finding_ids=payload.finding_ids,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "adversarial_state_invalid", "message": str(exc)}) from exc
        store.save_snapshot(updated, stage=updated.status)
        index.upsert_case(
            caso_id=updated.caso_id,
            tipo_peca=updated.tipo_peca,
            area_direito=updated.area_direito,
            status=updated.status,
            case_dir=store.case_dir,
        )
        store.append_event(
            "adversarial.findings_dismissed",
            {"finding_ids": payload.finding_ids, "reason": payload.reason},
        )
        return {
            "summary": {**summary, "status": updated.status},
            "state": updated.model_dump(mode="json"),
        }

    @router.post("/cases/{caso_id}/adversarial/revise")
    def submit_adversarial_revision(caso_id: str, payload: RevisionRequest) -> dict[str, Any]:
        index = _get_case_index()
        store = _get_case_store(caso_id, index=index)
        summary, state = _load_case_or_404(index, caso_id)
        try:
            updated = apply_human_revision(
                state,
                section_updates=payload.section_updates,
                notes=payload.notes,
                finalize=payload.finalize,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "adversarial_state_invalid", "message": str(exc)}) from exc
        revision_payload = submit_human_revision(
            state,
            section_updates=payload.section_updates,
            notes=payload.notes,
            finalize=payload.finalize,
        )
        store.save_snapshot(updated, stage=updated.status)
        index.upsert_case(
            caso_id=updated.caso_id,
            tipo_peca=updated.tipo_peca,
            area_direito=updated.area_direito,
            status=updated.status,
            case_dir=store.case_dir,
        )
        store.append_event(
            "adversarial.revision_submitted",
            {
                "sections": list(payload.section_updates.keys()),
                "finalize": payload.finalize,
            },
        )
        return {
            "summary": {**summary, "status": updated.status},
            "state": updated.model_dump(mode="json"),
            "revision_payload": revision_payload,
        }

    return router

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.escritorio.adversarial import (
    apply_human_revision,
    dismiss_findings,
    register_critique_round,
    submit_human_revision,
)
from backend.escritorio.graph.orchestrator import run_escritorio_pipeline
from backend.escritorio.intake import process_intake_message
from backend.escritorio.models import RatioEscritorioState
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


class ArchiveCaseRequest(BaseModel):
    archived: bool = True


class RenameCaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RestoreSnapshotRequest(BaseModel):
    snapshot_id: int = Field(gt=0)


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


_STAGE_AGENT_MAP = {
    "intake": "intake",
    "drafting": "pesquisador",
    "pesquisa": "pesquisador",
    "research": "pesquisador",
    "curadoria": "pesquisador",
    "gate2": "pesquisador",
    "redacao": "redator",
    "redaction": "redator",
    "adversarial": "contraparte",
    "revisao_humana": "contraparte",
    "verificacao": "auditor",
    "verification": "auditor",
    "entrega": "formatador",
    "delivery": "formatador",
    "finalizado": "formatador",
}


def _agent_for_stage(stage_name: str) -> str | None:
    return _STAGE_AGENT_MAP.get(str(stage_name or "").strip().lower())


def _describe_event(event_type: str, data: dict[str, Any]) -> tuple[str | None, str]:
    approved = bool(data.get("approved"))
    if event_type == "case.created":
        return "intake", "Caso criado"
    if event_type == "intake.turn":
        return "intake", "Nova mensagem na triagem"
    if event_type == "gate1.decision":
        return "intake", "Triagem aprovada" if approved else "Triagem devolvida"
    if event_type == "gate2.decision":
        return "pesquisador", "Pesquisa aprovada para redação" if approved else "Pesquisa devolvida"
    if event_type == "draft.updated":
        return "redator", "Minuta atualizada"
    if event_type == "adversarial.critique_registered":
        rodada = int(data.get("rodada_atual") or 0)
        return "contraparte", f"Crítica registrada na rodada {rodada}" if rodada else "Crítica registrada"
    if event_type == "pipeline.error":
        message = str(data.get("message") or "").strip()
        return _agent_for_stage(data.get("stage") or data.get("workflow_stage") or data.get("status")), (
            f"Falha no pipeline: {message}" if message else "Falha no pipeline"
        )
    if event_type in {"pipeline.stage_started", "pipeline.stage_completed"}:
        stage = str(data.get("stage") or data.get("workflow_stage") or data.get("status") or "").strip().lower()
        started = event_type.endswith("started")
        labels = {
            "intake": "Triagem",
            "drafting": "Pesquisa",
            "pesquisa": "Pesquisa",
            "research": "Pesquisa",
            "curadoria": "Curadoria",
            "gate2": "Confirmação da pesquisa",
            "redacao": "Redação",
            "redaction": "Redação",
            "adversarial": "Revisão",
            "revisao_humana": "Revisão humana",
            "verificacao": "Verificação",
            "verification": "Verificação",
            "entrega": "Entrega",
            "delivery": "Entrega",
            "finalizado": "Entrega",
        }
        label = labels.get(stage, stage or "Pipeline")
        suffix = "iniciada" if started else "concluída"
        return _agent_for_stage(stage), f"{label} {suffix}"
    return _agent_for_stage(event_type.split(".", 1)[0]), event_type


def _serialize_event_for_frontend(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("payload")
    if not isinstance(data, dict):
        data = {}
    agent, text = _describe_event(str(event.get("event_type") or ""), data)
    payload_agent = str(data.get("agent") or "").strip()
    payload_text = str(data.get("text") or "").strip()
    if payload_agent:
        agent = payload_agent
    if payload_text:
        text = payload_text
    return {
        **event,
        "type_name": event.get("event_type"),
        "agent": agent,
        "text": text,
        "data": data,
    }


def _summarize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    state = snapshot.get("state") or {}
    stage = str(snapshot.get("stage") or state.get("status") or "").strip()
    stage_lower = stage.lower()

    if stage_lower in {"intake", "gate1"}:
        summary = f"{len(state.get('fatos_estruturados') or [])} fatos estruturados"
    elif stage_lower in {"pesquisa", "gate2", "curadoria"}:
        summary = f"{len(state.get('teses') or [])} teses pesquisadas"
    elif stage_lower == "redacao":
        summary = f"{len((state.get('peca_sections') or {}).keys())} secoes redigidas"
    elif stage_lower in {"adversarial", "revisao_humana"}:
        summary = f"Rodada {int(state.get('rodada_atual') or 0)} de revisao"
    elif stage_lower in {"verificacao", "entrega", "finalizado"}:
        summary = f"{len(state.get('verificacoes') or [])} verificacoes"
    else:
        summary = stage or "Snapshot"

    return {
        "snapshot_id": snapshot.get("id"),
        "stage": stage,
        "created_at": snapshot.get("created_at"),
        "status": state.get("status"),
        "workflow_stage": state.get("workflow_stage"),
        "summary": summary,
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

    @router.post("/cases/{caso_id}/archive")
    def archive_case(caso_id: str, payload: ArchiveCaseRequest) -> dict[str, Any]:
        index = _get_case_index()
        if not index.set_archived(caso_id, archived=bool(payload.archived)):
            raise HTTPException(status_code=404, detail={"code": "case_not_found", "caso_id": caso_id})
        entry = index.get_case(caso_id) or {}
        return {"summary": entry}

    @router.post("/cases/{caso_id}/rename")
    def rename_case(caso_id: str, payload: RenameCaseRequest) -> dict[str, Any]:
        index = _get_case_index()
        if not index.rename_case(caso_id, new_name=payload.name):
            raise HTTPException(status_code=404, detail={"code": "case_not_found", "caso_id": caso_id})
        entry = index.get_case(caso_id) or {}
        return {"summary": entry}

    @router.delete("/cases/{caso_id}")
    def delete_case(caso_id: str) -> dict[str, Any]:
        index = _get_case_index()
        entry = index.get_case(caso_id)
        if entry is None:
            raise HTTPException(status_code=404, detail={"code": "case_not_found", "caso_id": caso_id})
        index.delete_case(caso_id)
        return {"deleted": True, "caso_id": caso_id}

    @router.get("/cases/{caso_id}/folder")
    def get_case_folder(caso_id: str) -> dict[str, Any]:
        index = _get_case_index()
        entry = index.get_case(caso_id)
        if entry is None:
            raise HTTPException(status_code=404, detail={"code": "case_not_found", "caso_id": caso_id})
        return {"path": entry.get("path", "")}

    @router.post("/cases/{caso_id}/open-folder")
    def open_case_folder(caso_id: str) -> dict[str, Any]:
        import os, subprocess, sys
        index = _get_case_index()
        entry = index.get_case(caso_id)
        if entry is None:
            raise HTTPException(status_code=404, detail={"code": "case_not_found", "caso_id": caso_id})
        path = entry.get("path", "")
        if not path or not os.path.exists(path):
            raise HTTPException(status_code=404, detail={"code": "folder_not_found", "path": path})
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            raise HTTPException(status_code=500, detail={"code": "open_failed", "error": str(exc)})
        return {"opened": True, "path": path}

    @router.get("/cases/{caso_id}/download")
    def download_case_docx(caso_id: str):
        index = _get_case_index()
        _summary, state = _load_case_or_404(index, caso_id)
        output_path = Path(str(state.output_docx_path or "")).expanduser()
        if not output_path.is_file():
            raise HTTPException(status_code=404, detail={"code": "docx_not_found", "path": str(output_path)})
        return FileResponse(
            str(output_path),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=output_path.name,
        )

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
            "events": [_serialize_event_for_frontend(event) for event in store.list_events()],
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

    @router.get("/cases/{caso_id}/history")
    def get_case_history(caso_id: str) -> dict[str, Any]:
        index = _get_case_index()
        summary, _state = _load_case_or_404(index, caso_id)
        store = _get_case_store(caso_id, index=index)
        return {
            "summary": summary,
            "history": [_summarize_snapshot(snapshot) for snapshot in store.list_snapshots()],
        }

    @router.post("/cases/{caso_id}/restore")
    def restore_case_snapshot(caso_id: str, payload: RestoreSnapshotRequest) -> dict[str, Any]:
        index = _get_case_index()
        store = _get_case_store(caso_id, index=index)
        summary, _state = _load_case_or_404(index, caso_id)
        snapshot = store.load_snapshot(payload.snapshot_id)
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "snapshot_not_found", "snapshot_id": payload.snapshot_id},
            )

        restored = RatioEscritorioState.model_validate(snapshot["state"])

        store.save_snapshot(restored, stage=restored.status)
        index.upsert_case(
            caso_id=restored.caso_id,
            tipo_peca=restored.tipo_peca,
            area_direito=restored.area_direito,
            status=restored.status,
            case_dir=store.case_dir,
        )
        store.append_event(
            "case.restored",
            {
                "snapshot_id": payload.snapshot_id,
                "stage": restored.status,
                "workflow_stage": restored.workflow_stage,
                "status": restored.status,
            },
        )
        refreshed_summary = index.get_case(caso_id) or {**summary, "status": restored.status}
        return {
            "summary": refreshed_summary,
            "state": restored.model_dump(mode="json"),
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

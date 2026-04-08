from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from backend.escritorio.models import RatioEscritorioState


def slugify_case_id(caso_id: str) -> str:
    text = str(caso_id or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "caso"


class CaseStore:
    """Persistencia isolada por caso."""

    def __init__(self, case_dir: str | Path):
        self.case_dir = Path(case_dir).expanduser()
        self.db_path = self.case_dir / "caso.db"
        self.docs_dir = self.case_dir / "docs"
        self.output_dir = self.case_dir / "output"
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS case_metadata (
                    caso_id TEXT PRIMARY KEY,
                    tipo_peca TEXT NOT NULL,
                    area_direito TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'intake',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS case_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stage TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS case_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def create_case(
        self,
        *,
        caso_id: str,
        tipo_peca: str,
        area_direito: str = "",
    ) -> dict[str, Any]:
        initial_state = RatioEscritorioState(
            caso_id=caso_id,
            tipo_peca=tipo_peca,
            area_direito=area_direito,
        )

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT caso_id FROM case_metadata WHERE caso_id = ?",
                (caso_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError(f"Caso '{caso_id}' ja existe.")

            conn.execute(
                """
                INSERT INTO case_metadata (caso_id, tipo_peca, area_direito, status)
                VALUES (?, ?, ?, ?)
                """,
                (caso_id, tipo_peca, area_direito, initial_state.status),
            )
            conn.execute(
                """
                INSERT INTO case_snapshots (stage, state_json)
                VALUES (?, ?)
                """,
                (
                    initial_state.status,
                    json.dumps(initial_state.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
            conn.execute(
                """
                INSERT INTO case_events (event_type, payload_json)
                VALUES (?, ?)
                """,
                (
                    "case.created",
                    json.dumps(
                        {
                            "caso_id": caso_id,
                            "tipo_peca": tipo_peca,
                            "area_direito": area_direito,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

        return self.get_case() or {
            "caso_id": caso_id,
            "tipo_peca": tipo_peca,
            "area_direito": area_direito,
            "status": initial_state.status,
            "path": str(self.case_dir),
        }

    def get_case(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT caso_id, tipo_peca, area_direito, status, created_at, updated_at
                FROM case_metadata
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            return None

        return {
            "caso_id": row["caso_id"],
            "tipo_peca": row["tipo_peca"],
            "area_direito": row["area_direito"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "path": str(self.case_dir),
        }

    def append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO case_events (event_type, payload_json)
                VALUES (?, ?)
                """,
                (event_type, json.dumps(payload, ensure_ascii=False)),
            )

    def save_snapshot(self, state: RatioEscritorioState, *, stage: str) -> None:
        payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO case_snapshots (stage, state_json)
                VALUES (?, ?)
                """,
                (stage, payload),
            )
            conn.execute(
                """
                UPDATE case_metadata
                SET area_direito = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE caso_id = ?
                """,
                (state.area_direito, stage, state.caso_id),
            )

    def load_latest_snapshot(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT stage, state_json, created_at
                FROM case_snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            return None

        return {
            "stage": row["stage"],
            "state": json.loads(row["state_json"]),
            "created_at": row["created_at"],
        }

    def list_snapshots(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, stage, state_json, created_at
                FROM case_snapshots
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "stage": row["stage"],
                "state": json.loads(row["state_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def load_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, stage, state_json, created_at
                FROM case_snapshots
                WHERE id = ?
                LIMIT 1
                """,
                (snapshot_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "stage": row["stage"],
            "state": json.loads(row["state_json"]),
            "created_at": row["created_at"],
        }

    def load_latest_state(self) -> RatioEscritorioState | None:
        snapshot = self.load_latest_snapshot()
        if snapshot is None:
            return None
        return RatioEscritorioState.model_validate(snapshot["state"])

    def list_events(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, event_type, payload_json, created_at
                FROM case_events
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


class CaseIndex:
    """Indice global leve para listagem e resolucao de casos."""

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir).expanduser()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root_dir / "index.db"
        self.cases_root = self.root_dir / "casos"
        self.cases_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cases_index (
                    caso_id TEXT PRIMARY KEY,
                    tipo_peca TEXT NOT NULL,
                    area_direito TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Lightweight migration: add `archived` column for older databases.
            existing_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(cases_index)").fetchall()
            }
            if "archived" not in existing_cols:
                conn.execute(
                    "ALTER TABLE cases_index ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
                )

    def resolve_case_dir(self, caso_id: str) -> Path:
        entry = self.get_case(caso_id)
        if entry is not None:
            return Path(str(entry["path"]))
        return self.cases_root / slugify_case_id(caso_id)

    def upsert_case(
        self,
        *,
        caso_id: str,
        tipo_peca: str,
        area_direito: str,
        status: str,
        case_dir: str | Path,
    ) -> None:
        resolved_case_dir = str(Path(case_dir).expanduser())
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT caso_id FROM cases_index WHERE caso_id = ?",
                (caso_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO cases_index (caso_id, tipo_peca, area_direito, status, path)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (caso_id, tipo_peca, area_direito, status, resolved_case_dir),
                )
            else:
                conn.execute(
                    """
                    UPDATE cases_index
                    SET tipo_peca = ?, area_direito = ?, status = ?, path = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE caso_id = ?
                    """,
                    (tipo_peca, area_direito, status, resolved_case_dir, caso_id),
                )

    def get_case(self, caso_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT caso_id, tipo_peca, area_direito, status, path, created_at, updated_at, archived
                FROM cases_index
                WHERE caso_id = ?
                """,
                (caso_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "caso_id": row["caso_id"],
            "tipo_peca": row["tipo_peca"],
            "area_direito": row["area_direito"],
            "status": row["status"],
            "path": row["path"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived": bool(row["archived"]),
        }

    def list_cases(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT caso_id, tipo_peca, area_direito, status, path, created_at, updated_at, archived
                FROM cases_index
                ORDER BY updated_at DESC, caso_id ASC
                """
            ).fetchall()
        return [
            {
                "caso_id": row["caso_id"],
                "tipo_peca": row["tipo_peca"],
                "area_direito": row["area_direito"],
                "status": row["status"],
                "path": row["path"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "archived": bool(row["archived"]),
            }
            for row in rows
        ]

    def set_archived(self, caso_id: str, *, archived: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE cases_index
                SET archived = ?, updated_at = CURRENT_TIMESTAMP
                WHERE caso_id = ?
                """,
                (1 if archived else 0, caso_id),
            )
            return cur.rowcount > 0

    def rename_case(self, caso_id: str, *, new_name: str) -> bool:
        """Update the display name (area_direito) of a case. Returns False if not found."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE cases_index
                SET area_direito = ?, updated_at = CURRENT_TIMESTAMP
                WHERE caso_id = ?
                """,
                (new_name.strip(), caso_id),
            )
            return cur.rowcount > 0

    def delete_case(self, caso_id: str) -> bool:
        """Remove a case from the index. Returns False if not found."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM cases_index WHERE caso_id = ?",
                (caso_id,),
            )
            return cur.rowcount > 0


class EscritorioStore:
    """Wrapper de compatibilidade durante a migracao para CaseStore + CaseIndex."""

    def __init__(self, root_path: str | Path):
        raw_path = Path(root_path).expanduser()
        self.root_dir = raw_path.parent if raw_path.suffix.lower() == ".db" else raw_path
        self.index = CaseIndex(self.root_dir)

    def _case_store_for(self, caso_id: str) -> CaseStore:
        return CaseStore(self.index.resolve_case_dir(caso_id))

    def create_case(
        self,
        *,
        caso_id: str,
        tipo_peca: str,
        area_direito: str = "",
    ) -> dict[str, Any]:
        case_store = self._case_store_for(caso_id)
        created = case_store.create_case(
            caso_id=caso_id,
            tipo_peca=tipo_peca,
            area_direito=area_direito,
        )
        self.index.upsert_case(
            caso_id=caso_id,
            tipo_peca=tipo_peca,
            area_direito=area_direito,
            status=created["status"],
            case_dir=case_store.case_dir,
        )
        return created

    def list_cases(self) -> list[dict[str, Any]]:
        return self.index.list_cases()

    def append_event(self, caso_id: str, event_type: str, payload: dict[str, Any]) -> None:
        case_store = self._case_store_for(caso_id)
        case_store.append_event(event_type, payload)

    def save_snapshot(self, state: RatioEscritorioState, *, stage: str) -> None:
        case_store = self._case_store_for(state.caso_id)
        case_store.save_snapshot(state, stage=stage)
        current = case_store.get_case()
        self.index.upsert_case(
            caso_id=state.caso_id,
            tipo_peca=state.tipo_peca,
            area_direito=state.area_direito,
            status=stage,
            case_dir=case_store.case_dir,
        )
        if current is None:
            return

    def load_latest_snapshot(self, caso_id: str) -> dict[str, Any] | None:
        return self._case_store_for(caso_id).load_latest_snapshot()

    def load_latest_state(self, caso_id: str) -> RatioEscritorioState | None:
        return self._case_store_for(caso_id).load_latest_state()

    def get_case(self, caso_id: str) -> dict[str, Any] | None:
        entry = self.index.get_case(caso_id)
        if entry is None:
            return None
        case = self._case_store_for(caso_id).get_case()
        return case or entry

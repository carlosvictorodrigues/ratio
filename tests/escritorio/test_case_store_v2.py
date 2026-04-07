from pathlib import Path

from backend.escritorio.store import CaseIndex, CaseStore


def test_case_store_uses_one_sqlite_per_case_and_updates_global_index(tmp_path: Path):
    root_dir = tmp_path / "ratio_escritorio"
    case_dir = root_dir / "casos" / "caso_1"

    case_store = CaseStore(case_dir)
    created = case_store.create_case(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        area_direito="Civil",
    )

    index = CaseIndex(root_dir)
    index.upsert_case(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        area_direito="Civil",
        status=created["status"],
        case_dir=case_dir,
    )

    assert case_store.db_path == case_dir / "caso.db"
    assert (case_dir / "docs").is_dir()
    assert (case_dir / "output").is_dir()
    assert (root_dir / "index.db").exists()
    assert index.list_cases()[0]["path"] == str(case_dir)


def test_case_store_lists_events_and_snapshots(tmp_path: Path):
    case_dir = tmp_path / "ratio_escritorio" / "casos" / "caso_1"
    case_store = CaseStore(case_dir)
    created = case_store.create_case(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        area_direito="Civil",
    )

    case_store.append_event("pipeline.stage_completed", {"stage": "intake"})
    case = case_store.get_case()
    snapshots = case_store.list_snapshots()
    events = case_store.list_events()

    assert created["status"] == "intake"
    assert case is not None
    assert len(snapshots) == 1
    assert snapshots[0]["stage"] == "intake"
    assert events[-1]["event_type"] == "pipeline.stage_completed"

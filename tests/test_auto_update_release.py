from __future__ import annotations

from pathlib import Path

import backend.auto_update as auto_update
from installer import generate_manifest


def test_auto_update_rollback_restores_existing_files_and_removes_new_files(tmp_path: Path) -> None:
    existing_target = tmp_path / "backend" / "main.py"
    existing_target.parent.mkdir(parents=True, exist_ok=True)
    existing_target.write_text("new", encoding="utf-8")

    backup_target = existing_target.with_suffix(existing_target.suffix + ".bak")
    backup_target.write_text("old", encoding="utf-8")

    new_target = tmp_path / "lancedb_store" / "tjsp_jurisprudencia.lance" / "data" / "part.lance"
    new_target.parent.mkdir(parents=True, exist_ok=True)
    new_target.write_text("partial", encoding="utf-8")

    auto_update._rollback_swapped_files(
        [
            (existing_target, backup_target),
            (new_target, None),
        ]
    )

    assert existing_target.read_text(encoding="utf-8") == "old"
    assert not backup_target.exists()
    assert not new_target.exists()


def test_generate_manifest_collects_runtime_paths_explicitly(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "version.json").write_text('{"version":"2026.03.20","build":9}\n', encoding="utf-8")

    runtime_dir = tmp_path / "lancedb_store" / "tjsp_jurisprudencia.lance"
    (runtime_dir / "data").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "data" / "chunk.lance").write_bytes(b"abc")
    (runtime_dir / "_versions").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "_versions" / "1.manifest").write_bytes(b"def")

    files = generate_manifest.collect_files(
        tmp_path,
        runtime_paths=["lancedb_store/tjsp_jurisprudencia.lance"],
    )
    paths = {entry["path"] for entry in files}

    assert "backend/main.py" in paths
    assert "version.json" in paths
    assert "lancedb_store/tjsp_jurisprudencia.lance/data/chunk.lance" in paths
    assert "lancedb_store/tjsp_jurisprudencia.lance/_versions/1.manifest" in paths

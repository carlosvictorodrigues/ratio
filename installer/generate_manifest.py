#!/usr/bin/env python3
"""Generate update-manifest.json for the Ratio delta-update system.

Scans backend/, rag/, frontend/, and root-level config files, computes
SHA-256 hashes, and produces a manifest that auto_update.py consumes.

Important release policy:
the delta manifest must reflect the real end-user update path used by the
frontend auto-update flow. If a change depends on runtime assets outside the
current scan set (for example, new LanceDB tables under lancedb_store/), the
release is not safely deliverable to existing users until those assets are
included here or the release is flagged as requiring a full installer.

Usage:
    python installer/generate_manifest.py --tag v2026.03.18

The --tag is required and determines the GitHub Release URL prefix
for file downloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

GITHUB_REPO = "carlosvictorodrigues/ratio"

# Directories and files to include in delta updates.
# These are the patchable source files — NOT binaries or data.
SCAN_DIRS = ["backend", "rag", "frontend"]
SCAN_ROOT_FILES = ["version.json"]
SCAN_EXTENSIONS = {".py", ".js", ".html", ".css", ".json"}
CANONICAL_TEXT_EXTENSIONS = {".py", ".js", ".html", ".css", ".json", ".md", ".yml", ".yaml"}

# Files/patterns to always exclude
EXCLUDE_PATTERNS = {
    "__pycache__",
    ".pyc",
    ".bak",
    "node_modules",
    ".env",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_canonical(path: Path) -> str:
    if path.suffix.lower() not in CANONICAL_TEXT_EXTENSIONS:
        return sha256(path)
    raw = path.read_bytes()
    normalized = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def should_include(path: Path) -> bool:
    parts = path.as_posix()
    for pattern in EXCLUDE_PATTERNS:
        if pattern in parts:
            return False
    return path.suffix in SCAN_EXTENSIONS


def _add_file_entry(files: list[dict], seen: set[str], project_root: Path, file_path: Path) -> None:
    if not file_path.is_file():
        return
    rel = file_path.relative_to(project_root).as_posix()
    if rel in seen:
        return
    seen.add(rel)
    files.append({
        "path": rel,
        "sha256": sha256_canonical(file_path),
        "size": file_path.stat().st_size,
    })


def collect_files(project_root: Path, runtime_paths: list[str] | None = None) -> list[dict]:
    files = []
    seen: set[str] = set()

    for dir_name in SCAN_DIRS:
        scan_dir = project_root / dir_name
        if not scan_dir.is_dir():
            continue
        for file_path in sorted(scan_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if not should_include(file_path):
                continue
            _add_file_entry(files, seen, project_root, file_path)

    for fname in SCAN_ROOT_FILES:
        fpath = project_root / fname
        if fpath.is_file():
            _add_file_entry(files, seen, project_root, fpath)

    for rel_path in runtime_paths or []:
        runtime_root = project_root / rel_path
        if runtime_root.is_file():
            _add_file_entry(files, seen, project_root, runtime_root)
            continue
        if not runtime_root.is_dir():
            continue
        for file_path in sorted(runtime_root.rglob("*")):
            if not file_path.is_file():
                continue
            _add_file_entry(files, seen, project_root, file_path)

    return files


def build_manifest(
    project_root: Path,
    tag: str,
    needs_full_installer: bool = False,
    installer_url: str = "",
    notes: str = "",
    runtime_paths: list[str] | None = None,
) -> dict:
    version_file = project_root / "version.json"
    if version_file.exists():
        vdata = json.loads(version_file.read_text(encoding="utf-8"))
        version = vdata.get("version", "unknown")
        build = int(vdata.get("build", 0))
    else:
        version = "unknown"
        build = 0

    files = collect_files(project_root, runtime_paths=runtime_paths)

    # Add download URLs pointing to GitHub Release assets
    base_url = f"https://github.com/{GITHUB_REPO}/releases/download/{tag}"
    for f in files:
        # GitHub Release assets use flat names, so we replace / with --
        asset_name = f["path"].replace("/", "--")
        f["url"] = f"{base_url}/{asset_name}"

    manifest = {
        "version": version,
        "build": build,
        "released_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": notes,
        "needs_full_installer": needs_full_installer,
        "installer_url": installer_url,
        "files": files,
    }

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Ratio update manifest")
    parser.add_argument("--tag", required=True, help="GitHub Release tag (e.g. v2026.03.18)")
    parser.add_argument("--notes", default="", help="Release notes text")
    parser.add_argument("--needs-full-installer", action="store_true",
                        help="Flag that this release requires the full installer")
    parser.add_argument("--installer-url", default="", help="URL to the full installer download")
    parser.add_argument(
        "--include-runtime-path",
        action="append",
        default=[],
        help="Additional runtime path to ship in the delta release (file or directory). Repeat as needed.",
    )
    parser.add_argument("--output", default="update-manifest.json", help="Output file path")

    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent.parent

    manifest = build_manifest(
        project_root,
        tag=args.tag,
        needs_full_installer=args.needs_full_installer,
        installer_url=args.installer_url,
        notes=args.notes,
        runtime_paths=[str(item).strip() for item in (args.include_runtime_path or []) if str(item).strip()],
    )

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Manifest generated: {output_path}")
    print(f"  Version: {manifest['version']} (build {manifest['build']})")
    print(f"  Files:   {len(manifest['files'])}")
    total_size = sum(f["size"] for f in manifest["files"])
    print(f"  Total:   {total_size / 1024:.1f} KB")

    return 0


if __name__ == "__main__":
    sys.exit(main())

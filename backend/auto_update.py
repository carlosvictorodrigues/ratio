"""Lightweight auto-update system for Ratio.

Checks GitHub Releases for a newer version manifest, downloads only the
changed files, and atomically swaps them into place.  The user restarts
the app to activate the new code — no exe rebuild needed because
desktop_launcher.py loads .py files from disk at runtime.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

GITHUB_REPO = "carlosvictorodrigues/ratio"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
MANIFEST_ASSET_NAME = "update-manifest.json"
CHECK_COOLDOWN_S = 3600  # 1 hour


# ── Helpers ──────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_target(project_root: Path, rel_path: str) -> Path:
    """Resolve the actual target path, handling _internal/ for dist builds."""
    direct = project_root / rel_path
    if direct.exists():
        return direct
    # dist layout: frontend/ lives inside _internal/
    internal = project_root / "_internal" / rel_path
    if internal.exists():
        return internal
    # New file — prefer direct path, create dirs as needed
    return direct


def _check_disk_space(project_root: Path, required_mb: float = 100) -> bool:
    """Return True if there is enough free space on the target drive."""
    try:
        usage = shutil.disk_usage(str(project_root))
        free_mb = usage.free / (1024 * 1024)
        return free_mb >= required_mb
    except Exception:
        return True  # assume OK if we can't check


def _write_version_json(project_root: Path, version: str, build: int) -> None:
    """Persist the new version after a successful update."""
    vf = project_root / "version.json"
    data = {"version": version, "build": build}
    vf.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("version.json updated to %s (build %d)", version, build)


def _rollback_swapped_files(swapped: list[tuple[Path, Path | None]]) -> None:
    for target, backup in reversed(swapped):
        try:
            if target.exists():
                target.unlink()
            if backup is not None and backup.exists():
                backup.rename(target)
        except Exception:
            pass


# ── Public API ───────────────────────────────────────────────────────

def load_local_version(project_root: Path) -> dict[str, Any]:
    vf = project_root / "version.json"
    if not vf.exists():
        return {"version": "unknown", "build": 0}
    try:
        data = json.loads(vf.read_text(encoding="utf-8"))
        return {
            "version": str(data.get("version", "unknown")),
            "build": int(data.get("build", 0)),
        }
    except Exception:
        return {"version": "unknown", "build": 0}


def check_for_update(
    project_root: Path,
    last_check_ts: float,
) -> dict[str, Any]:
    """Check GitHub Releases for a newer version. Safe to call often — respects cooldown."""
    now = time.time()
    if last_check_ts and (now - last_check_ts) < CHECK_COOLDOWN_S:
        return {"available": False, "reason": "cooldown"}

    local = load_local_version(project_root)

    try:
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            resp = client.get(
                GITHUB_API_LATEST,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "Ratio-AutoUpdate/1.0",
                },
            )
            if resp.status_code == 404:
                return {"available": False, "reason": "no_releases", **local}
            resp.raise_for_status()
            release = resp.json()

            # Find manifest asset
            manifest_url = ""
            for asset in release.get("assets") or []:
                if asset.get("name") == MANIFEST_ASSET_NAME:
                    manifest_url = asset.get("browser_download_url", "")
                    break

            if not manifest_url:
                return {"available": False, "reason": "no_manifest", **local}

            # Download manifest
            mresp = client.get(manifest_url)
            mresp.raise_for_status()
            manifest = mresp.json()

        remote_build = int(manifest.get("build", 0))
        local_build = local["build"]
        available = remote_build > local_build

        # If the manifest flags binary-level changes (exe, _internal/),
        # the delta system can't handle it — user needs the full installer.
        needs_full_installer = bool(manifest.get("needs_full_installer", False))
        installer_url = str(manifest.get("installer_url", ""))

        return {
            "available": available,
            "local_version": local["version"],
            "local_build": local_build,
            "remote_version": str(manifest.get("version", "")),
            "remote_build": remote_build,
            "notes": str(manifest.get("notes", "")),
            "released_at": str(manifest.get("released_at", "")),
            "files_count": len(manifest.get("files") or []),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "manifest": manifest if available else None,
            "needs_full_installer": needs_full_installer,
            "installer_url": installer_url,
        }
    except Exception as exc:
        log.warning("Auto-update check failed: %s", exc)
        return {
            "available": False,
            "reason": "offline",
            "error": str(exc),
            **local,
        }


def apply_update(
    project_root: Path,
    manifest: dict[str, Any],
    progress_cb: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Download files from manifest and atomically swap into place."""
    files = manifest.get("files") or []
    if not files:
        return {"status": "no_files", "updated_files": []}

    # Pre-flight: disk space check
    if not _check_disk_space(project_root, required_mb=50):
        raise RuntimeError(
            "Espaco em disco insuficiente. Libere pelo menos 50 MB e tente novamente."
        )

    def _emit(stage: str, msg: str, **kw: Any) -> None:
        if progress_cb:
            progress_cb(stage, msg, kw)

    # Phase 1: Download to temp dir (same partition to allow os.rename)
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="ratio_update_", dir=str(logs_dir)))

    try:
        total = len(files)
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            for i, entry in enumerate(files):
                rel_path = entry["path"]
                url = entry["url"]
                expected_sha = entry.get("sha256", "")

                _emit("downloading", f"Baixando {rel_path}...", index=i, total=total)

                dl_target = tmp_dir / rel_path
                dl_target.parent.mkdir(parents=True, exist_ok=True)

                resp = client.get(url)
                resp.raise_for_status()
                dl_target.write_bytes(resp.content)

                if expected_sha:
                    actual_sha = _sha256(dl_target)
                    if actual_sha != expected_sha:
                        raise RuntimeError(
                            f"Checksum mismatch for {rel_path}: "
                            f"expected {expected_sha[:12]}..., got {actual_sha[:12]}..."
                        )

        # Phase 2: Atomic swap with backup
        swapped: list[tuple[Path, Path | None]] = []  # (target, backup)
        try:
            for entry in files:
                rel_path = entry["path"]
                src = tmp_dir / rel_path
                target = _resolve_target(project_root, rel_path)
                backup: Path | None = target.with_suffix(target.suffix + ".bak") if target.exists() else None

                target.parent.mkdir(parents=True, exist_ok=True)

                if target.exists():
                    if backup is not None and backup.exists():
                        backup.unlink()
                    target.rename(backup)
                    swapped.append((target, backup))
                else:
                    swapped.append((target, None))

                src.rename(target)
                _emit("applying", f"Aplicando {rel_path}...", file=rel_path)

        except Exception:
            _rollback_swapped_files(swapped)
            raise

        # Phase 3: Cleanup
        for target, backup in swapped:
            try:
                if backup is not None and backup.exists():
                    backup.unlink()
            except Exception:
                pass

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Phase 4: Persist new version so the app reports the correct build
    new_version = str(manifest.get("version", ""))
    new_build = int(manifest.get("build", 0))
    if new_version and new_build:
        try:
            _write_version_json(project_root, new_version, new_build)
        except Exception as exc:
            log.warning("Failed to write version.json after update: %s", exc)

    updated = [e["path"] for e in files]
    return {
        "status": "done",
        "updated_files": updated,
        "version": new_version,
        "build": new_build,
    }


def schedule_restart(project_root: Path, delay_s: float = 1.5) -> dict[str, Any]:
    """Schedule an app restart by spawning a new Ratio.exe and exiting.

    Works on Windows by launching a detached process that waits briefly
    for the current process to exit, then starts Ratio.exe again.
    """
    exe = project_root / "Ratio.exe"
    if not exe.exists():
        return {"status": "error", "detail": "Ratio.exe nao encontrado."}

    # On Windows: use a small cmd script that waits, then re-launches.
    # On other platforms (dev): use a direct subprocess.
    if sys.platform == "win32":
        restart_bat = project_root / "logs" / "_restart.bat"
        restart_bat.parent.mkdir(exist_ok=True)
        script = (
            f'@echo off\n'
            f'timeout /t {int(delay_s + 1)} /nobreak >nul\n'
            f'start "" "{exe}"\n'
            f'del "%~f0"\n'
        )
        restart_bat.write_text(script, encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", str(restart_bat)],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    else:
        subprocess.Popen(
            [str(exe)],
            start_new_session=True,
            close_fds=True,
        )

    log.info("Restart scheduled in %.1fs", delay_s)
    return {"status": "restarting", "delay_s": delay_s}

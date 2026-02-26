from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_backend_and_rag_support_project_root_override_for_exe_mode():
    backend_py = _read("backend/main.py")
    rag_query_py = _read("rag/query.py")

    assert "RATIO_PROJECT_ROOT" in backend_py
    assert "RATIO_PROJECT_ROOT" in rag_query_py


def test_desktop_launcher_starts_backend_and_frontend_servers():
    launcher_py = _read("desktop_launcher.py")

    assert "ThreadingHTTPServer" in launcher_py
    assert "uvicorn" in launcher_py
    assert "webbrowser.open" in launcher_py
    assert "RATIO_PROJECT_ROOT" in launcher_py
    # Avoid string-based uvicorn import target ("backend.main:app"), which
    # PyInstaller may not collect in frozen mode.
    assert "from backend.main import app as backend_app" in launcher_py
    assert "app=backend_app" in launcher_py
    assert "lancedb_store" in launcher_py


def test_readme_documents_windows_exe_distribution_flow():
    readme = _read("README.md")

    assert "Build executavel .exe (Windows)" in readme
    assert "dist\\Ratio\\Ratio.exe" in readme
    assert "nao precisa de Python" in readme


def test_build_script_hardens_lancedb_distribution():
    build_bat = _read("build_windows_exe.bat")

    assert "DB_BACKUP_ROOT" in build_bat
    assert "robocopy \"%DIST_DB%\" \"!DB_BACKUP_DIR!\"" in build_bat
    assert "robocopy \"%DB_SOURCE%\" \"%DIST_DB%\"" in build_bat
    assert "if not exist \"%DB_SOURCE_TABLE%\"" in build_bat
    assert "if not exist \"%DIST_DB_TABLE%\"" in build_bat


def test_build_script_collects_pymupdf_for_meu_acervo_indexing():
    build_bat = _read("build_windows_exe.bat")

    assert "--collect-all \"pymupdf\"" in build_bat
    assert "--hidden-import \"fitz\"" in build_bat
    assert "pip install --upgrade pyinstaller pymupdf" in build_bat

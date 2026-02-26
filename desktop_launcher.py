from __future__ import annotations

import contextlib
import os
import socket
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_HOST = "127.0.0.1"
FRONTEND_PORT = 5500
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
FRONTEND_URL = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}"


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _runtime_root()
os.environ["RATIO_PROJECT_ROOT"] = str(PROJECT_ROOT)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app as backend_app


def _is_port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _wait_port(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _is_port_busy(host, port):
            return True
        time.sleep(0.15)
    return _is_port_busy(host, port)


def _start_frontend_server(frontend_dir: Path) -> ThreadingHTTPServer:
    handler = partial(SimpleHTTPRequestHandler, directory=str(frontend_dir))
    server = ThreadingHTTPServer((FRONTEND_HOST, FRONTEND_PORT), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True, name="ratio-frontend")
    worker.start()
    return server


def _start_backend_server() -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(
        app=backend_app,
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    worker = threading.Thread(target=server.run, daemon=True, name="ratio-backend")
    worker.start()
    return server, worker


def _resolve_frontend_dir() -> Path | None:
    candidates = [
        PROJECT_ROOT / "frontend",
        PROJECT_ROOT / "_internal" / "frontend",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return None


def _resolve_lancedb_dir() -> Path | None:
    candidates = [
        PROJECT_ROOT / "lancedb_store" / "jurisprudencia.lance",
        PROJECT_ROOT / "_internal" / "lancedb_store" / "jurisprudencia.lance",
    ]
    for path in candidates:
        if path.is_dir():
            return path.parent
    return None


def main() -> int:
    os.chdir(PROJECT_ROOT)

    frontend_dir = _resolve_frontend_dir()
    if frontend_dir is None:
        print("[ERRO] Pasta frontend nao encontrada.")
        print(f"Tentado: {PROJECT_ROOT / 'frontend'}")
        print(f"Tentado: {PROJECT_ROOT / '_internal' / 'frontend'}")
        return 1

    lancedb_dir = _resolve_lancedb_dir()
    if lancedb_dir is None:
        print("[ERRO] Base jurisprudencial LanceDB nao encontrada.")
        print(f"Tentado: {PROJECT_ROOT / 'lancedb_store' / 'jurisprudencia.lance'}")
        print(f"Tentado: {PROJECT_ROOT / '_internal' / 'lancedb_store' / 'jurisprudencia.lance'}")
        print("Inclua a pasta lancedb_store ao lado do Ratio.exe e tente novamente.")
        return 5

    frontend_server: ThreadingHTTPServer | None = None
    backend_server: uvicorn.Server | None = None
    backend_thread: threading.Thread | None = None

    try:
        if _is_port_busy(BACKEND_HOST, BACKEND_PORT):
            print(f"[INFO] Backend ja estava ativo em {BACKEND_URL}.")
        else:
            print(f"[1/3] Iniciando backend em {BACKEND_URL} ...")
            backend_server, backend_thread = _start_backend_server()

        if _is_port_busy(FRONTEND_HOST, FRONTEND_PORT):
            print(f"[INFO] Frontend ja estava ativo em {FRONTEND_URL}.")
        else:
            print(f"[2/3] Iniciando frontend em {FRONTEND_URL} ...")
            frontend_server = _start_frontend_server(frontend_dir)

        if not _wait_port(BACKEND_HOST, BACKEND_PORT, timeout_s=50):
            print("[ERRO] Backend nao respondeu dentro de 50s.")
            return 2
        if not _wait_port(FRONTEND_HOST, FRONTEND_PORT, timeout_s=20):
            print("[ERRO] Frontend nao respondeu dentro de 20s.")
            return 3

        print(f"[3/3] Abrindo navegador em {FRONTEND_URL} ...")
        webbrowser.open(FRONTEND_URL)
        print("Aplicacao iniciada. Pressione Ctrl+C para encerrar.")

        while True:
            time.sleep(0.4)
            if backend_thread and not backend_thread.is_alive():
                print("[ERRO] Backend encerrou inesperadamente.")
                return 4
    except KeyboardInterrupt:
        print("\nEncerrando Ratio...")
        return 0
    finally:
        if backend_server is not None:
            backend_server.should_exit = True
        if frontend_server is not None:
            with contextlib.suppress(Exception):
                frontend_server.shutdown()
            with contextlib.suppress(Exception):
                frontend_server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())

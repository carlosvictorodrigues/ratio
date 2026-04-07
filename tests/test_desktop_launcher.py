import sys
import threading
import time
from pathlib import Path

import requests

from desktop_launcher import QuietSimpleHTTPRequestHandler, _ensure_safe_stdio


def test_quiet_frontend_handler_serves_requests_when_stderr_is_none(tmp_path: Path):
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

    old_stderr = sys.stderr
    sys.stderr = None
    try:
        from http.server import ThreadingHTTPServer
        from functools import partial

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(QuietSimpleHTTPRequestHandler, directory=str(frontend_dir)),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.2)

        url = f"http://127.0.0.1:{server.server_port}/"
        response = requests.get(url, timeout=5)

        assert response.status_code == 200
        assert "ok" in response.text
    finally:
        server.shutdown()
        server.server_close()
        sys.stderr = old_stderr


class _BrokenStream:
    def write(self, _data):
        raise OSError(22, "Invalid argument")

    def flush(self):
        raise OSError(22, "Invalid argument")


def test_ensure_safe_stdio_wraps_broken_streams():
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        sys.stdout = _BrokenStream()
        sys.stderr = _BrokenStream()

        _ensure_safe_stdio()

        print("stdout survives")
        print("stderr survives", file=sys.stderr)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

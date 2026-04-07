from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable


class LanceDBReadonlyRegistry:
    def __init__(self, *, connect_fn: Callable[[str], Any] | None = None):
        self._connect_fn = connect_fn
        self._connections: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _cache_key_for(self, raw_path: str | Path) -> str:
        return str(Path(raw_path).expanduser().resolve())

    def _resolve_connect_fn(self) -> Callable[[str], Any]:
        if self._connect_fn is not None:
            return self._connect_fn

        import lancedb

        return lancedb.connect

    def get_connection(self, raw_path: str | Path) -> Any:
        cache_key = self._cache_key_for(raw_path)
        with self._lock:
            existing = self._connections.get(cache_key)
            if existing is not None:
                return existing

            connection = self._resolve_connect_fn()(cache_key)
            self._connections[cache_key] = connection
            return connection

    def open_table(self, raw_path: str | Path, table_name: str) -> Any:
        connection = self.get_connection(raw_path)
        return connection.open_table(table_name)

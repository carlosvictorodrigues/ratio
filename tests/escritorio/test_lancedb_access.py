from backend.escritorio.tools.lancedb_access import LanceDBReadonlyRegistry


def test_lancedb_registry_reuses_same_connection_per_path():
    opened_paths: list[str] = []

    def fake_connect(path: str):
        opened_paths.append(path)
        return {"path": path}

    registry = LanceDBReadonlyRegistry(connect_fn=fake_connect)

    first = registry.get_connection("C:/tmp/lancedb_store")
    second = registry.get_connection("C:/tmp/lancedb_store")

    assert first is second
    assert len(opened_paths) == 1

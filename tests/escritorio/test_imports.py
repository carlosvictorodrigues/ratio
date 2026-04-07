from importlib import import_module


def test_escritorio_package_imports():
    pkg = import_module("backend.escritorio")
    tools_pkg = import_module("backend.escritorio.tools")
    graph_pkg = import_module("backend.escritorio.graph")

    assert pkg is not None
    assert tools_pkg is not None
    assert graph_pkg is not None

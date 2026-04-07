from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_escritorio_frontend_no_longer_contains_mock_runtime_data():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "const MOCK_SECTIONS" not in html
    assert "const MOCK_TESES" not in html
    assert "const MOCK_CRITICAS" not in html
    assert "const FEED_SCRIPT" not in html
    assert "const AGENT_OUTPUTS" not in html


def test_escritorio_frontend_uses_named_confirmations_instead_of_gate_labels():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "Confirmacao da Triagem" in html
    assert "Confirmacao da Pesquisa" in html
    assert "Gate {gate}" not in html

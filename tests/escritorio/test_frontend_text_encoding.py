from pathlib import Path


def test_escritorio_frontend_has_no_mojibake_sequences():
    html = Path("frontend/Escritorio/escritorio.html").read_text(encoding="utf-8")

    for bad in ("Ã", "â", "\ufffd"):
        assert bad not in html

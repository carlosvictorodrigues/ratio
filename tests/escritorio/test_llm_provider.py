"""Tests for backend.escritorio.llm_provider.

All LLM calls are intercepted via monkeypatching — no real API keys needed.
"""
from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_gemini_response(text: str):
    resp = MagicMock()
    resp.text = text
    return resp


def _fake_anthropic_response(text: str):
    content_block = MagicMock()
    content_block.text = text
    resp = MagicMock()
    resp.content = [content_block]
    return resp


# ---------------------------------------------------------------------------
# Tests — Gemini provider (default)
# ---------------------------------------------------------------------------

def test_generate_text_uses_gemini_by_default(monkeypatch):
    """When GENERATION_PROVIDER is not set / 'gemini', uses Gemini client."""
    captured = {}

    fake_gemini = MagicMock()
    fake_gemini.models.generate_content.side_effect = lambda **kw: (
        captured.update(kw) or _fake_gemini_response('{"ok": true}')
    )

    import rag.query as rq

    monkeypatch.setattr(rq, "GENERATION_PROVIDER", "gemini")
    monkeypatch.setattr(rq, "get_gemini_client", lambda: fake_gemini)

    # Reload to pick up monkeypatched module-level vars
    import backend.escritorio.llm_provider as lp
    importlib.reload(lp)

    result = lp.generate_text('Ola mundo', 'gemini-3-flash')

    assert result == '{"ok": true}'
    assert captured.get("model") == "gemini-3-flash"
    assert captured.get("contents") == "Ola mundo"


def test_generate_text_gemini_raises_on_empty_response(monkeypatch):
    fake_gemini = MagicMock()
    fake_gemini.models.generate_content.return_value = _fake_gemini_response("")

    import rag.query as rq

    monkeypatch.setattr(rq, "GENERATION_PROVIDER", "gemini")
    monkeypatch.setattr(rq, "get_gemini_client", lambda: fake_gemini)

    import backend.escritorio.llm_provider as lp
    importlib.reload(lp)

    with pytest.raises(ValueError, match="vazia"):
        lp.generate_text("prompt", "gemini-3-flash")


# ---------------------------------------------------------------------------
# Tests — Claude provider
# ---------------------------------------------------------------------------

def test_generate_text_uses_claude_when_provider_set(monkeypatch):
    """When GENERATION_PROVIDER=claude and key present, calls Anthropic client."""
    captured = {}

    fake_anthropic = MagicMock()
    fake_anthropic.messages.create.side_effect = lambda **kw: (
        captured.update(kw) or _fake_anthropic_response("Resposta Claude")
    )

    import rag.query as rq

    monkeypatch.setattr(rq, "GENERATION_PROVIDER", "claude")
    monkeypatch.setattr(rq, "has_anthropic_api_key", lambda: True)
    monkeypatch.setattr(rq, "get_anthropic_client", lambda: fake_anthropic)

    import backend.escritorio.llm_provider as lp
    importlib.reload(lp)

    result = lp.generate_text("Redija uma peticao.", "gemini-3.1-pro-preview")

    assert result == "Resposta Claude"
    # Gemini model name should have been mapped to a Claude model
    assert captured.get("model", "").startswith("claude-")
    assert captured["messages"] == [{"role": "user", "content": "Redija uma peticao."}]


def test_generate_text_maps_flash_to_haiku(monkeypatch):
    """Gemini flash model maps to Claude haiku (cheaper tier)."""
    captured = {}

    fake_anthropic = MagicMock()
    fake_anthropic.messages.create.side_effect = lambda **kw: (
        captured.update(kw) or _fake_anthropic_response("ok")
    )

    import rag.query as rq

    monkeypatch.setattr(rq, "GENERATION_PROVIDER", "claude")
    monkeypatch.setattr(rq, "has_anthropic_api_key", lambda: True)
    monkeypatch.setattr(rq, "get_anthropic_client", lambda: fake_anthropic)

    import backend.escritorio.llm_provider as lp
    importlib.reload(lp)
    # Override defaults to known values for assertion
    monkeypatch.setattr(lp, "_DEFAULT_CLAUDE_PESQUISADOR", "claude-haiku-4-5-20251001")
    monkeypatch.setattr(lp, "_DEFAULT_CLAUDE_REASONING", "claude-sonnet-4-20250514")

    lp.generate_text("prompt", "gemini-3-flash")
    assert captured["model"] == "claude-haiku-4-5-20251001"

    lp.generate_text("prompt", "gemini-3.1-pro-preview")
    assert captured["model"] == "claude-sonnet-4-20250514"


def test_generate_text_falls_back_to_gemini_when_key_absent(monkeypatch, capsys):
    """When provider=claude but key absent, warns and uses Gemini."""
    fake_gemini = MagicMock()
    fake_gemini.models.generate_content.return_value = _fake_gemini_response("Gemini fallback")

    import rag.query as rq

    monkeypatch.setattr(rq, "GENERATION_PROVIDER", "claude")
    monkeypatch.setattr(rq, "has_anthropic_api_key", lambda: False)
    monkeypatch.setattr(rq, "get_gemini_client", lambda: fake_gemini)

    import backend.escritorio.llm_provider as lp
    importlib.reload(lp)

    result = lp.generate_text("prompt", "gemini-3-flash")

    assert result == "Gemini fallback"
    captured_err = capsys.readouterr().err
    assert "fallback" in captured_err.lower() or "ANTHROPIC_API_KEY" in captured_err


def test_generate_text_claude_raises_on_empty_response(monkeypatch):
    fake_anthropic = MagicMock()
    fake_anthropic.messages.create.return_value = _fake_anthropic_response("")

    import rag.query as rq

    monkeypatch.setattr(rq, "GENERATION_PROVIDER", "claude")
    monkeypatch.setattr(rq, "has_anthropic_api_key", lambda: True)
    monkeypatch.setattr(rq, "get_anthropic_client", lambda: fake_anthropic)

    import backend.escritorio.llm_provider as lp
    importlib.reload(lp)

    with pytest.raises(ValueError, match="vazia"):
        lp.generate_text("prompt", "gemini-3-flash")


# ---------------------------------------------------------------------------
# Tests — integration: existing call sites still accept explicit client
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_intake_llm_still_accepts_explicit_client():
    """Passing client= to generate_intake_with_gemini bypasses llm_provider."""
    from backend.escritorio.intake_llm import generate_intake_with_gemini
    from backend.escritorio.models import RatioEscritorioState

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_gemini_response(
        '{"fatos_estruturados":["fato"],"provas_disponiveis":[],"pontos_atencao":[]}'
    )

    state = RatioEscritorioState(
        caso_id="t1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Teste de intake.",
    )

    result = await generate_intake_with_gemini(state, client=fake_client)
    assert result["fatos_estruturados"] == ["fato"]
    fake_client.models.generate_content.assert_called_once()


@pytest.mark.anyio
async def test_redaction_still_accepts_explicit_client():
    """Passing client= to generate_sections_with_gemini bypasses llm_provider."""
    from backend.escritorio.models import RatioEscritorioState
    from backend.escritorio.redaction import generate_sections_with_gemini

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_gemini_response(
        '{"introducao":"Texto intro","pedidos":"Requer deferimento"}'
    )

    state = RatioEscritorioState(
        caso_id="t2",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente sofreu dano.",
    )

    result = await generate_sections_with_gemini(state, client=fake_client)
    assert "introducao" in result
    fake_client.models.generate_content.assert_called_once()

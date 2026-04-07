"""Tests for backend.escritorio.pii_guard — Guard Brasil PII protection."""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_guard_response(detections: list[dict], masked_text: str):
    """Build a fake httpx response for Guard Brasil /v1/inspect."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "masked_text": masked_text,
        "detections": detections,
    }
    return resp


# ---------------------------------------------------------------------------
# Tests — disabled (default)
# ---------------------------------------------------------------------------

def test_maybe_mask_disabled_by_default(monkeypatch):
    """When RATIO_PII_GUARD_ENABLED is not set, maybe_mask is a no-op."""
    import backend.escritorio.pii_guard as pg
    importlib.reload(pg)

    monkeypatch.delenv("RATIO_PII_GUARD_ENABLED", raising=False)
    text = "João da Silva, CPF 123.456.789-00"
    out, result = pg.maybe_mask(text)

    assert out == text
    assert result.masked_count == 0
    assert not result.has_pii


def test_maybe_mask_disabled_explicit_zero(monkeypatch):
    """RATIO_PII_GUARD_ENABLED=0 → no-op."""
    import backend.escritorio.pii_guard as pg
    importlib.reload(pg)

    monkeypatch.setenv("RATIO_PII_GUARD_ENABLED", "0")
    text = "CPF 999.888.777-66"
    out, result = pg.maybe_mask(text)
    assert out == text
    assert result.masked_count == 0


def test_maybe_mask_empty_string(monkeypatch):
    """Empty input returns empty string regardless of enabled state."""
    import backend.escritorio.pii_guard as pg
    importlib.reload(pg)

    monkeypatch.setenv("RATIO_PII_GUARD_ENABLED", "1")
    out, result = pg.maybe_mask("")
    assert out == ""
    assert result.masked_count == 0


# ---------------------------------------------------------------------------
# Tests — enabled, Guard Brasil responding
# ---------------------------------------------------------------------------

def test_maybe_mask_enabled_masks_cpf(monkeypatch):
    """When enabled, CPF detection triggers masking and sets lgpd_risk=high."""
    import backend.escritorio.pii_guard as pg
    importlib.reload(pg)

    monkeypatch.setenv("RATIO_PII_GUARD_ENABLED", "1")
    monkeypatch.setenv("GUARD_BRASIL_URL", "https://guard.egos.ia.br")

    fake_resp = _make_guard_response(
        detections=[{"type": "cpf", "value": "123.456.789-00", "start": 20, "end": 34}],
        masked_text="João da Silva, CPF [MASKED_CPF]",
    )

    with patch("httpx.post", return_value=fake_resp):
        out, result = pg.maybe_mask("João da Silva, CPF 123.456.789-00")

    assert "[MASKED_CPF]" in out
    assert result.masked_count == 1
    assert "cpf" in result.patterns
    assert result.lgpd_risk == "high"
    assert result.has_pii


def test_maybe_mask_medium_risk_for_phone(monkeypatch):
    """Phone number → lgpd_risk=medium (not in high_risk set)."""
    import backend.escritorio.pii_guard as pg
    importlib.reload(pg)

    monkeypatch.setenv("RATIO_PII_GUARD_ENABLED", "1")

    fake_resp = _make_guard_response(
        detections=[{"type": "phone", "value": "(11) 99999-0000"}],
        masked_text="Ligue para [MASKED_PHONE]",
    )

    with patch("httpx.post", return_value=fake_resp):
        out, result = pg.maybe_mask("Ligue para (11) 99999-0000")

    assert result.lgpd_risk == "medium"
    assert result.masked_count == 1


def test_maybe_mask_no_pii_detected(monkeypatch):
    """Guard Brasil responds with empty detections → lgpd_risk=none."""
    import backend.escritorio.pii_guard as pg
    importlib.reload(pg)

    monkeypatch.setenv("RATIO_PII_GUARD_ENABLED", "1")

    fake_resp = _make_guard_response(
        detections=[],
        masked_text="Texto sem PII detectável.",
    )

    with patch("httpx.post", return_value=fake_resp):
        out, result = pg.maybe_mask("Texto sem PII detectável.")

    assert result.masked_count == 0
    assert result.lgpd_risk == "none"
    assert not result.has_pii


# ---------------------------------------------------------------------------
# Tests — fail-open when Guard Brasil is down
# ---------------------------------------------------------------------------

def test_maybe_mask_fails_open_on_network_error(monkeypatch):
    """Network error → return original text unchanged (fail-open, no crash)."""
    import backend.escritorio.pii_guard as pg
    importlib.reload(pg)

    monkeypatch.setenv("RATIO_PII_GUARD_ENABLED", "1")

    with patch("httpx.post", side_effect=ConnectionError("timeout")):
        out, result = pg.maybe_mask("CPF 123.456.789-00")

    assert out == "CPF 123.456.789-00"  # original unchanged
    assert result.error is not None
    assert result.masked_count == 0


# ---------------------------------------------------------------------------
# Tests — integration: intake uses maybe_mask
# ---------------------------------------------------------------------------

def test_intake_calls_maybe_mask(monkeypatch):
    """build_intake_prompt invokes maybe_mask on fatos_brutos."""
    import backend.escritorio.pii_guard as pg
    importlib.reload(pg)
    import backend.escritorio.intake_llm as intake
    importlib.reload(intake)

    from backend.escritorio.models import RatioEscritorioState

    called_with = {}

    def fake_mask(text):
        called_with["text"] = text
        return text, pg.GuardResult()

    monkeypatch.setattr(pg, "maybe_mask", fake_mask)
    # Reload intake so it picks up the patched pii_guard
    importlib.reload(intake)

    state = RatioEscritorioState(
        caso_id="t1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente CPF 123.456.789-00",
    )
    intake.build_intake_prompt(state)

    assert called_with.get("text") == "Cliente CPF 123.456.789-00"

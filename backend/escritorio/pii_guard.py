"""Guard Brasil PII protection for the Escritório pipeline.

Intercepts raw case text before any LLM call and masks Brazilian PII
(CPF, RG, phone, name, address patterns) so client data never reaches
external LLM providers in plain text.

Configuration
-------------
Set ``RATIO_PII_GUARD_ENABLED=1`` to activate (default: off so existing
behaviour is unchanged). When enabled, also set the Guard Brasil endpoint:

.. code-block:: bash

    RATIO_PII_GUARD_ENABLED=1
    GUARD_BRASIL_URL=https://guard.egos.ia.br   # or your self-hosted URL

Why this matters
----------------
Today ``intake_llm.py`` and ``redaction.py`` send the raw ``fatos_brutos``
string directly to Gemini/Claude/OpenRouter. A typical case description
contains "meu cliente João da Silva, CPF 123.456.789-00 …". Under LGPD
art. 33 this is an international PII transfer requiring explicit consent or
a valid legal basis. Guard Brasil masks the data before it leaves Brazil.

Integration points in the Escritório pipeline
----------------------------------------------
1. ``intake_llm.generate_intake_with_gemini`` — mask ``fatos_brutos``
   before building the prompt (line 12 of build_intake_prompt).
2. ``redaction.build_redaction_prompt`` — mask ``fatos_brutos`` before
   embedding in the prompt (line 22 of build_redaction_prompt).
3. Both call ``maybe_mask()`` which is a no-op when the feature is
   disabled, so no behaviour change for users who don't configure it.

Usage
-----
.. code-block:: python

    from backend.escritorio.pii_guard import maybe_mask, GuardResult

    safe_text, result = maybe_mask(raw_text)
    # safe_text: text with PII replaced by [MASKED_CPF], [MASKED_RG], etc.
    # result: GuardResult(masked_count=3, patterns=["cpf", "rg", "phone"])
    # If RATIO_PII_GUARD_ENABLED is not "1": safe_text == raw_text, result.masked_count == 0
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GuardResult:
    """Result of a Guard Brasil PII inspection."""

    masked_count: int = 0
    patterns: list[str] = field(default_factory=list)
    lgpd_risk: str = "none"  # "none" | "low" | "medium" | "high"
    guard_url: str = ""
    error: Optional[str] = None

    @property
    def has_pii(self) -> bool:
        return self.masked_count > 0


def _is_enabled() -> bool:
    return os.getenv("RATIO_PII_GUARD_ENABLED", "0").strip() == "1"


def _guard_url() -> str:
    return os.getenv("GUARD_BRASIL_URL", "https://guard.egos.ia.br").rstrip("/")


def maybe_mask(text: str) -> tuple[str, GuardResult]:
    """Mask Brazilian PII in *text* if Guard Brasil is enabled.

    Returns:
        (masked_text, GuardResult)
        When disabled: (text, GuardResult(masked_count=0)) — zero cost, zero latency.
    """
    if not text or not _is_enabled():
        return text, GuardResult()

    url = _guard_url()
    try:
        import httpx  # already in requirements.txt  # noqa: PLC0415

        response = httpx.post(
            f"{url}/v1/inspect",
            json={"text": text, "mask": True},
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()

        masked_text = data.get("masked_text") or text
        detections = data.get("detections") or []
        patterns = list({d.get("type", "unknown") for d in detections})
        count = len(detections)

        # Simple LGPD risk heuristic: CPF/RG/CNPJ = high, phone/email = medium
        high_risk = {"cpf", "rg", "cnpj", "passaporte", "titulo_eleitor"}
        if any(p in high_risk for p in patterns):
            lgpd_risk = "high"
        elif count > 0:
            lgpd_risk = "medium"
        else:
            lgpd_risk = "none"

        return masked_text, GuardResult(
            masked_count=count,
            patterns=patterns,
            lgpd_risk=lgpd_risk,
            guard_url=url,
        )

    except Exception as exc:  # noqa: BLE001
        # Guard Brasil unreachable or returned error — log and pass through
        # (fail-open so a Guard Brasil outage doesn't break the pipeline).
        print(
            f"[pii_guard] Guard Brasil unavailable ({url}): {exc}. "
            "Sending text unmasked. Set RATIO_PII_GUARD_ENABLED=0 to silence.",
            file=sys.stderr,
        )
        return text, GuardResult(
            error=str(exc),
            guard_url=url,
        )

from __future__ import annotations

import os


DEFAULT_PESQUISADOR_MODEL = (
    os.getenv("RATIO_ESCRITORIO_PESQUISADOR_MODEL") or "gemini-3-flash-preview"
).strip()

DEFAULT_REASONING_MODEL = (
    os.getenv("RATIO_ESCRITORIO_REASONING_MODEL") or "gemini-3.1-pro-preview"
).strip()

DEFAULT_REASONING_FALLBACK_MODEL = (
    os.getenv("RATIO_ESCRITORIO_REASONING_FALLBACK_MODEL") or "gemini-3-flash-preview"
).strip()

DEFAULT_LLM_TIMEOUT_MS = int(
    (os.getenv("RATIO_ESCRITORIO_LLM_TIMEOUT_MS") or "120000").strip()
)

from __future__ import annotations

import os


DEFAULT_PESQUISADOR_MODEL = (
    os.getenv("RATIO_ESCRITORIO_PESQUISADOR_MODEL") or "gemini-3-flash"
).strip()

DEFAULT_REASONING_MODEL = (
    os.getenv("RATIO_ESCRITORIO_REASONING_MODEL") or "gemini-3.1-pro-preview"
).strip()

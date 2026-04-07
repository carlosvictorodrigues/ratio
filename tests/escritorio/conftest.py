"""Conftest for escritorio tests.

Stubs heavy optional dependencies (lancedb, google-genai, sentence-transformers,
huggingface_hub) so the test suite can run without the full ML stack installed.
The stubs only need to satisfy the module-level imports in rag/query.py.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _ensure_stub(name: str) -> MagicMock:
    """Register a MagicMock module under *name* if not already present."""
    if name not in sys.modules:
        stub = MagicMock(name=name)
        sys.modules[name] = stub
    return sys.modules[name]


# ── lancedb ──────────────────────────────────────────────────────────────────
_ensure_stub("lancedb")
_ensure_stub("lancedb.pydantic")
_ensure_stub("lancedb.embeddings")

# ── google-genai ─────────────────────────────────────────────────────────────
_ensure_stub("google")
_ensure_stub("google.genai")
_ensure_stub("google.genai.types")

# ── sentence-transformers / huggingface ──────────────────────────────────────
_ensure_stub("sentence_transformers")
_ensure_stub("huggingface_hub")

# ── transformers ─────────────────────────────────────────────────────────────
_ensure_stub("transformers")

# ── pyarrow ──────────────────────────────────────────────────────────────────
_ensure_stub("pyarrow")

# ── anthropic — keep real if installed, otherwise stub ───────────────────────
try:
    import anthropic  # noqa: F401
except ImportError:
    _ensure_stub("anthropic")

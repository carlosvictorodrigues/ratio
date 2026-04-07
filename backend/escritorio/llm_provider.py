"""Provider-agnostic text generation for the Escritório pipeline.

Routes to Claude or Gemini based on the GENERATION_PROVIDER env var
(already declared in .env.example and wired in rag/query.py for the
main RAG pipeline — this module extends that support to the Escritório nodes).

Usage::

    from backend.escritorio.llm_provider import generate_text

    text = generate_text(prompt="...", model="gemini-3.1-pro-preview")

When GENERATION_PROVIDER=claude, Gemini model names are automatically
mapped to their Claude equivalents via RATIO_ESCRITORIO_CLAUDE_MODEL_*
env vars. When ANTHROPIC_API_KEY is absent, falls back to Gemini with a
stderr warning (no silent failure).
"""
from __future__ import annotations

import os
import sys

# Optional overrides for Claude model names.
# Defaults match the closest-capability Claude models at 2025-05-14.
_DEFAULT_CLAUDE_REASONING = os.getenv(
    "RATIO_ESCRITORIO_CLAUDE_MODEL_REASONING",
    "claude-sonnet-4-20250514",
)
_DEFAULT_CLAUDE_PESQUISADOR = os.getenv(
    "RATIO_ESCRITORIO_CLAUDE_MODEL_PESQUISADOR",
    "claude-haiku-4-5-20251001",
)


def _claude_model_for(gemini_model: str) -> str:
    """Map a Gemini model name to its closest Claude equivalent.

    Flash-family (fast/cheap) -> haiku.
    Pro/preview/reasoning    -> sonnet.
    Already a Claude name    -> returned unchanged.
    """
    name = gemini_model.lower()
    if name.startswith("claude-"):
        return gemini_model
    if "flash" in name:
        return _DEFAULT_CLAUDE_PESQUISADOR
    return _DEFAULT_CLAUDE_REASONING


def generate_text(prompt: str, model: str) -> str:
    """Generate text using the active LLM provider.

    Provider resolution order:
    1. GENERATION_PROVIDER=claude + ANTHROPIC_API_KEY present → Claude
    2. GENERATION_PROVIDER=claude + ANTHROPIC_API_KEY absent  → Gemini (warn)
    3. GENERATION_PROVIDER=gemini (default)                   → Gemini

    Args:
        prompt: Full prompt text (system + user merged, or user-only).
        model:  Model name in the *current* provider's notation.
                Gemini model names are auto-mapped when provider=claude.

    Returns:
        Generated text string. Never empty (raises ValueError if the
        provider returns an empty response after all retries).

    Raises:
        ValueError: Provider returned an empty/null response.
        RuntimeError: Provider client could not be initialised.
    """
    from rag.query import GENERATION_PROVIDER, has_anthropic_api_key  # noqa: PLC0415

    if GENERATION_PROVIDER == "claude":
        if has_anthropic_api_key():
            from rag.query import get_anthropic_client  # noqa: PLC0415

            claude_model = _claude_model_for(model)
            client = get_anthropic_client()
            response = client.messages.create(
                model=claude_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = (response.content[0].text or "").strip()
            if not text:
                raise ValueError(
                    f"Claude ({claude_model}) retornou resposta vazia."
                )
            return text

        print(
            "[escritorio/llm_provider] GENERATION_PROVIDER=claude mas "
            "ANTHROPIC_API_KEY nao configurado — usando Gemini como fallback.",
            file=sys.stderr,
        )

    # Gemini path (default or fallback)
    from rag.query import get_gemini_client  # noqa: PLC0415

    response = get_gemini_client().models.generate_content(
        model=model,
        contents=prompt,
    )
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise ValueError(f"Gemini ({model}) retornou resposta vazia.")
    return text

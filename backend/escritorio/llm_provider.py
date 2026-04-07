"""Provider-agnostic text generation for the Escritório pipeline.

Routes to Claude, Gemini, or OpenRouter based on the GENERATION_PROVIDER
env var (already declared in .env.example and wired in rag/query.py for
the main RAG pipeline — this module extends that support to the Escritório
nodes).

Usage::

    from backend.escritorio.llm_provider import generate_text

    text = generate_text(prompt="...", model="gemini-3.1-pro-preview")

Provider resolution:

* ``GENERATION_PROVIDER=gemini`` (default) — Google Gemini via GEMINI_API_KEY.
* ``GENERATION_PROVIDER=claude`` — Anthropic Claude via ANTHROPIC_API_KEY.
  Gemini model names are auto-mapped to Claude equivalents; falls back to
  Gemini with a stderr warning when the key is absent.
* ``GENERATION_PROVIDER=openrouter`` — Any model on OpenRouter via
  OPENROUTER_API_KEY.  Uses the OpenAI-compatible chat-completions endpoint
  so users can choose free or cost-effective models (Qwen3.6 Plus free tier,
  DeepSeek V3, MiniMax, Kimi K2.5, etc.) with a single API key.

OpenRouter quick-start
----------------------
1. Create a free account at https://openrouter.ai
2. Generate an API key at https://openrouter.ai/keys
3. Add to your .env::

       OPENROUTER_API_KEY="sk-or-v1-..."
       GENERATION_PROVIDER="openrouter"
       OPENROUTER_MODEL="qwen/qwen3-235b-a22b:free"  # optional override

Recommended free/cheap models on OpenRouter
-------------------------------------------
* ``qwen/qwen3-235b-a22b:free``     — Qwen3.6 Plus, 1M context, FREE (limited)
* ``deepseek/deepseek-r1:free``     — DeepSeek R1 distill, reasoning, FREE
* ``minimax/minimax-01``            — MiniMax M2.7, $0.30/$1.20 per 1M tokens
* ``moonshot/kimi-k2``              — Kimi K2.5, $0.60/$3.00 per 1M tokens
* ``deepseek/deepseek-v3``          — DeepSeek V3, $0.27/$0.41 per 1M tokens
* ``anthropic/claude-sonnet-4``     — Claude Sonnet 4.6 via OpenRouter
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Claude model name overrides
# ---------------------------------------------------------------------------

_DEFAULT_CLAUDE_REASONING = os.getenv(
    "RATIO_ESCRITORIO_CLAUDE_MODEL_REASONING",
    "claude-sonnet-4-20250514",
)
_DEFAULT_CLAUDE_PESQUISADOR = os.getenv(
    "RATIO_ESCRITORIO_CLAUDE_MODEL_PESQUISADOR",
    "claude-haiku-4-5-20251001",
)

# ---------------------------------------------------------------------------
# OpenRouter defaults
# ---------------------------------------------------------------------------

# Default model when GENERATION_PROVIDER=openrouter and no explicit model
# override is given.  DeepSeek V3 offers excellent quality at very low cost.
_DEFAULT_OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "deepseek/deepseek-chat-v3-0324:free",
)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _openrouter_model_for(gemini_model: str) -> str:
    """Resolve the OpenRouter model slug to use.

    If OPENROUTER_MODEL env var is set it takes full precedence.
    Otherwise maps common Gemini model names to good cost-effective defaults
    so existing call sites work without extra configuration.
    """
    # Explicit env override always wins
    explicit = os.getenv("OPENROUTER_MODEL", "").strip()
    if explicit:
        return explicit

    name = gemini_model.lower()
    # Already an OpenRouter slug (contains "/")
    if "/" in name:
        return gemini_model
    # Flash-tier → free DeepSeek distill (reasoning-light, fast)
    if "flash" in name:
        return "deepseek/deepseek-r1-distill-qwen-7b:free"
    # Pro/preview/reasoning → DeepSeek V3 (best open quality at $0.27/$0.41)
    return "deepseek/deepseek-chat-v3-0324:free"


def _call_openrouter(prompt: str, model: str) -> str:
    """Call OpenRouter chat-completions endpoint via httpx (no extra deps)."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY não configurado. "
            "Crie uma conta em https://openrouter.ai/keys e adicione ao .env."
        )

    import httpx  # already in requirements.txt  # noqa: PLC0415

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # OpenRouter uses these for usage tracking / leaderboard
        "HTTP-Referer": "https://github.com/carlosvictorodrigues/ratio",
        "X-Title": "Ratio Escritório",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
    }

    response = httpx.post(
        _OPENROUTER_BASE_URL,
        headers=headers,
        json=payload,
        timeout=120.0,
    )
    response.raise_for_status()

    data = response.json()
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError) as exc:
        raise ValueError(
            f"OpenRouter ({model}) retornou estrutura inesperada: {data}"
        ) from exc

    if not text:
        raise ValueError(f"OpenRouter ({model}) retornou resposta vazia.")
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_text(prompt: str, model: str) -> str:
    """Generate text using the active LLM provider.

    Provider resolution order:
    1. GENERATION_PROVIDER=openrouter + OPENROUTER_API_KEY present → OpenRouter
    2. GENERATION_PROVIDER=claude + ANTHROPIC_API_KEY present       → Claude
    3. GENERATION_PROVIDER=claude + ANTHROPIC_API_KEY absent        → Gemini (warn)
    4. GENERATION_PROVIDER=gemini (default)                         → Gemini

    Args:
        prompt: Full prompt text (system + user merged, or user-only).
        model:  Model name in the *current* provider's notation.
                Gemini model names are auto-mapped when using Claude or
                OpenRouter — no call-site changes needed.

    Returns:
        Generated text string. Never empty (raises ValueError if the
        provider returns an empty response after all retries).

    Raises:
        ValueError:   Provider returned an empty/null response.
        RuntimeError: Provider client could not be initialised (missing key).
    """
    from rag.query import GENERATION_PROVIDER, has_anthropic_api_key  # noqa: PLC0415

    # ── OpenRouter ────────────────────────────────────────────────────────────
    if GENERATION_PROVIDER == "openrouter":
        or_model = _openrouter_model_for(model)
        return _call_openrouter(prompt, or_model)

    # ── Claude ────────────────────────────────────────────────────────────────
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

    # ── Gemini (default or fallback) ──────────────────────────────────────────
    from rag.query import get_gemini_client  # noqa: PLC0415

    response = get_gemini_client().models.generate_content(
        model=model,
        contents=prompt,
    )
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise ValueError(f"Gemini ({model}) retornou resposta vazia.")
    return text

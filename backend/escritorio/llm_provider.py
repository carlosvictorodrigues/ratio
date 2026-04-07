"""Provider-agnostic text generation for the Escritório pipeline.

Routes to Gemini, Claude, OpenRouter, or Alibaba DashScope based on the
``GENERATION_PROVIDER`` env var already declared in ``.env.example`` and
wired in ``rag/query.py`` for the main RAG pipeline — this module extends
that support to the Escritório nodes.

Usage::

    from backend.escritorio.llm_provider import generate_text

    text = generate_text(prompt="...", model="gemini-3.1-pro-preview")

Provider resolution order:

1. ``GENERATION_PROVIDER=openrouter``  → OpenRouter (200+ models, one key)
2. ``GENERATION_PROVIDER=alibaba``     → Alibaba DashScope (Qwen family)
3. ``GENERATION_PROVIDER=claude``      → Anthropic Claude (best PT-BR quality)
   * Falls back to Gemini if ``ANTHROPIC_API_KEY`` is absent
4. ``GENERATION_PROVIDER=gemini``      → Google Gemini (default)

Quick-start per provider
------------------------

**OpenRouter** — one key, free and paid models:

.. code-block:: bash

    OPENROUTER_API_KEY="sk-or-v1-..."
    GENERATION_PROVIDER="openrouter"
    # OPENROUTER_MODEL="qwen/qwen3-235b-a22b:free"   # optional

Recommended models:
  * ``qwen/qwen3-235b-a22b:free``            — free tier, 1M context
  * ``deepseek/deepseek-chat-v3-0324:free``  — free tier, excellent quality
  * ``deepseek/deepseek-r1:free``            — free tier, reasoning
  * ``minimax/minimax-01``                   — $0.30/$1.20 per 1M tokens
  * ``moonshot/kimi-k2``                     — $0.60/$3.00 per 1M tokens

**Alibaba DashScope** — Qwen models, OpenAI-compatible:

.. code-block:: bash

    ALIBABA_DASHSCOPE_API_KEY="sk-..."
    ALIBABA_DASHSCOPE_BASE_URL="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    GENERATION_PROVIDER="alibaba"
    # ALIBABA_MODEL="qwen-plus"   # optional override

Recommended models:
  * ``qwen-plus``       — best quality/cost (default)
  * ``qwen-turbo``      — fastest, cheapest
  * ``qwen-max``        — maximum quality
  * ``qwen3-235b-a22b`` — largest open-weight Qwen3

**Claude** — Anthropic, best quality for Brazilian legal text:

.. code-block:: bash

    ANTHROPIC_API_KEY="sk-ant-..."
    GENERATION_PROVIDER="claude"
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Claude model name overrides
# Defaults reference rag.query.SUPPORTED_CLAUDE_MODELS — same values kept
# in sync here as module-level constants for zero-import startup cost.
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

_DEFAULT_OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "deepseek/deepseek-chat-v3-0324:free",
)
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# ---------------------------------------------------------------------------
# Alibaba DashScope defaults
# ---------------------------------------------------------------------------

_DEFAULT_ALIBABA_MODEL = os.getenv("ALIBABA_MODEL", "qwen-plus")
_DEFAULT_ALIBABA_BASE_URL = os.getenv(
    "ALIBABA_DASHSCOPE_BASE_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)


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

    Explicit ``OPENROUTER_MODEL`` env var takes full precedence.
    Otherwise maps common Gemini model names to cost-effective defaults.
    """
    explicit = os.getenv("OPENROUTER_MODEL", "").strip()
    if explicit:
        return explicit
    name = gemini_model.lower()
    if "/" in name:
        return gemini_model  # already an OpenRouter slug
    if "flash" in name:
        return "deepseek/deepseek-r1-distill-qwen-7b:free"
    return "deepseek/deepseek-chat-v3-0324:free"


def _alibaba_model_for(gemini_model: str) -> str:
    """Resolve the Alibaba DashScope model to use.

    Explicit ``ALIBABA_MODEL`` env var takes full precedence.
    Otherwise maps Gemini tiers to Qwen equivalents.
    """
    explicit = os.getenv("ALIBABA_MODEL", "").strip()
    if explicit:
        return explicit
    name = gemini_model.lower()
    if "flash" in name:
        return "qwen-turbo"
    return "qwen-plus"


def _call_openrouter(prompt: str, model: str) -> str:
    """Call OpenRouter chat-completions endpoint via httpx (no extra deps)."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY não configurado. "
            "Crie uma conta em https://openrouter.ai/keys e adicione ao .env."
        )

    import httpx  # already in requirements.txt  # noqa: PLC0415

    response = httpx.post(
        _OPENROUTER_BASE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/carlosvictorodrigues/ratio",
            "X-Title": "Ratio Escritorio",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
        },
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


def _call_alibaba(prompt: str, model: str) -> str:
    """Call Alibaba DashScope via its OpenAI-compatible endpoint using httpx."""
    api_key = os.getenv("ALIBABA_DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ALIBABA_DASHSCOPE_API_KEY não configurado. "
            "Obtenha em https://dashscope.console.aliyun.com/apiKey "
            "e adicione ao .env."
        )

    import httpx  # noqa: PLC0415

    base_url = _DEFAULT_ALIBABA_BASE_URL.rstrip("/")
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
        },
        timeout=120.0,
    )
    response.raise_for_status()

    data = response.json()
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError) as exc:
        raise ValueError(
            f"Alibaba DashScope ({model}) retornou estrutura inesperada: {data}"
        ) from exc

    if not text:
        raise ValueError(f"Alibaba DashScope ({model}) retornou resposta vazia.")
    return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_code_fence(text: str) -> str:
    """Strip markdown code fences from LLM responses.

    Some models (non-Gemini) wrap JSON in ```json ... ``` even when the
    prompt explicitly requests raw JSON. This normalises the output so all
    callers receive clean text regardless of provider.

    Examples::

        ```json\\n{...}\\n```  →  {...}
        ```\\n{...}\\n```      →  {...}
        just plain text        →  just plain text (unchanged)
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence line (```json or just ```)
        lines = stripped.split("\n")
        # Remove first line (```…) and last line if it is ```
        start = 1
        end = len(lines)
        if lines[-1].strip() == "```":
            end -= 1
        stripped = "\n".join(lines[start:end]).strip()
    return stripped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_text(prompt: str, model: str) -> str:
    """Generate text using the active LLM provider.

    Provider resolution order:
    1. GENERATION_PROVIDER=openrouter → OpenRouter
    2. GENERATION_PROVIDER=alibaba   → Alibaba DashScope (Qwen)
    3. GENERATION_PROVIDER=claude + ANTHROPIC_API_KEY present → Claude
    4. GENERATION_PROVIDER=claude + ANTHROPIC_API_KEY absent  → Gemini (warn)
    5. GENERATION_PROVIDER=gemini (default)                   → Gemini

    Args:
        prompt: Full prompt text (system + user merged, or user-only).
        model:  Model name in Gemini notation; auto-mapped to provider
                equivalents when using Claude, OpenRouter, or Alibaba.

    Returns:
        Generated text string. Never empty (raises ValueError on empty response).

    Raises:
        ValueError:   Provider returned an empty/null response.
        RuntimeError: Provider key not configured.
    """
    from rag.query import (  # noqa: PLC0415
        GENERATION_MAX_OUTPUT_TOKENS,
        GENERATION_PROVIDER,
        has_anthropic_api_key,
    )

    # ── OpenRouter ────────────────────────────────────────────────────────────
    if GENERATION_PROVIDER == "openrouter":
        return _strip_code_fence(_call_openrouter(prompt, _openrouter_model_for(model)))

    # ── Alibaba DashScope ─────────────────────────────────────────────────────
    if GENERATION_PROVIDER == "alibaba":
        return _strip_code_fence(_call_alibaba(prompt, _alibaba_model_for(model)))

    # ── Claude ────────────────────────────────────────────────────────────────
    if GENERATION_PROVIDER == "claude":
        if has_anthropic_api_key():
            from rag.query import get_anthropic_client  # noqa: PLC0415

            claude_model = _claude_model_for(model)
            client = get_anthropic_client()
            response = client.messages.create(
                model=claude_model,
                max_tokens=max(300, int(GENERATION_MAX_OUTPUT_TOKENS)),
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            # Safe extraction: join all text blocks, guard against safety filters
            text = "".join(
                b.text for b in response.content if hasattr(b, "text")
            ).strip()
            if not text:
                raise ValueError(
                    f"Claude ({claude_model}) retornou resposta vazia "
                    "(possível filtro de segurança ou bloco não-texto)."
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

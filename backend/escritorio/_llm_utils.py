"""Shared helpers for LLM JSON parsing in the escritório pipeline.

Gemini frequently violates the requested output shape: it wraps JSON in
markdown fences, appends commentary, returns dicts where strings are
expected, or wraps payloads in envelopes. These helpers normalize the
response without dropping data, so each pipeline node can validate state
without crashing on shape drift.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

# Keys we prefer when collapsing a dict into a single sentence/string.
PREFERRED_DICT_KEYS: tuple[str, ...] = (
    "descricao",
    "texto",
    "conteudo",
    "fato",
    "evento",
    "resumo",
    "titulo",
    "argumento",
    "analise",
)


def make_json_response_config(*, timeout_ms: int = 45000):
    """Build a Gemini config that forces application/json output.

    Returns ``None`` if the google.genai package is not importable, so
    callers can degrade gracefully (parsing helpers still tolerate noise).
    """
    try:
        from google.genai import types as _genai_types
    except Exception:
        return None
    try:
        timeout = max(1000, int(timeout_ms or 45000))
        return _genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            http_options=_genai_types.HttpOptions(timeout=timeout),
        )
    except Exception:
        return None


def _extract_first_balanced(text: str, opener: str, closer: str) -> str | None:
    """Return the substring containing the first balanced ``opener``/``closer``.

    Walks the string tracking nesting depth while respecting JSON string
    literals and backslash escapes. Used as a fallback when ``json.loads``
    rejects extra trailing text.
    """
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            if depth == 0:
                start = i
            depth += 1
        elif ch == closer:
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    return text[start : i + 1]
    return None


def extract_first_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` block within ``text``."""
    return _extract_first_balanced(text, "{", "}")


def extract_first_json_array(text: str) -> str | None:
    """Return the first balanced ``[...]`` block within ``text``."""
    return _extract_first_balanced(text, "[", "]")


def _strip_fences_and_prefix(text: str, *, expect: str) -> str:
    text = str(text or "").strip()
    text = _JSON_FENCE.sub("", text).strip()
    if not text.startswith(expect):
        match = re.search(re.escape(expect), text)
        if match:
            text = text[match.start() :]
    return text


def parse_json_payload(
    raw_payload: str,
    *,
    expect: str = "object",
) -> Any:
    """Parse a Gemini response into a JSON value, tolerating noise.

    ``expect`` is ``"object"`` or ``"array"`` and only changes which
    structural opener is used as the prefix anchor and balanced-walk
    fallback. The parser:
      1. Strips markdown fences.
      2. Skips any prose before the structural opener.
      3. Uses ``raw_decode`` so trailing text after a valid value is ignored.
      4. Falls back to balanced-brace extraction when ``raw_decode`` fails.
    """
    if expect not in {"object", "array"}:
        raise ValueError(f"expect must be 'object' or 'array', got {expect!r}")

    opener = "{" if expect == "object" else "["
    text = _strip_fences_and_prefix(raw_payload, expect=opener)

    try:
        data, _end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        balanced = (
            extract_first_json_object(text)
            if expect == "object"
            else extract_first_json_array(text)
        )
        if balanced is None:
            raise
        data = json.loads(balanced)

    if expect == "object" and not isinstance(data, dict):
        # Some models wrap the dict inside a single-element list.
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
            return data[0]
        raise ValueError("Esperado objeto JSON, recebido outro tipo.")
    if expect == "array" and not isinstance(data, list):
        raise ValueError("Esperado array JSON, recebido outro tipo.")
    return data


def coerce_to_string(item: Any) -> str:
    """Flatten an arbitrary value into a single non-empty string when possible.

    Designed to preserve information from dicts/lists rather than discard
    them. Returns ``""`` only when the input has no usable content.
    """
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, (int, float)):
        return str(item).strip()
    if isinstance(item, dict):
        for key in PREFERRED_DICT_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                date = item.get("data") or item.get("date")
                if isinstance(date, str) and date.strip() and key not in {"data", "date"}:
                    return f"{date.strip()} — {value.strip()}"
                return value.strip()
            if isinstance(value, (list, dict)):
                nested = coerce_to_string(value)
                if nested:
                    return nested
        # Fallback: join all primitive values in insertion order so we never
        # lose information silently.
        joined = " — ".join(
            str(v).strip()
            for v in item.values()
            if isinstance(v, (str, int, float)) and str(v).strip()
        )
        if joined:
            return joined
        return json.dumps(item, ensure_ascii=False)
    if isinstance(item, list):
        parts = [coerce_to_string(sub) for sub in item]
        parts = [p for p in parts if p]
        return " — ".join(parts)
    return str(item).strip()


def coerce_to_long_text(item: Any) -> str:
    """Like :func:`coerce_to_string` but joins richer content with paragraphs.

    Used by section/text-heavy parsers (redaction) where dropping content
    would break the petition. Lists join with double newlines, dicts join
    all string-valued fields with newlines, preserving order.
    """
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, (int, float, bool)):
        return str(item).strip()
    if isinstance(item, list):
        parts: list[str] = []
        for sub in item:
            text = coerce_to_long_text(sub)
            if text:
                parts.append(text)
        return "\n\n".join(parts)
    if isinstance(item, dict):
        # Prefer canonical content keys when present.
        for key in ("conteudo", "texto", "descricao", "body", "content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (list, dict)):
                nested = coerce_to_long_text(value)
                if nested:
                    return nested
        # Otherwise concatenate all string-bearing values to keep info.
        chunks: list[str] = []
        for key, value in item.items():
            text = coerce_to_long_text(value)
            if not text:
                continue
            label = str(key).strip()
            if label and label.lower() not in {"conteudo", "texto", "descricao"}:
                chunks.append(f"{label}: {text}")
            else:
                chunks.append(text)
        return "\n\n".join(chunks)
    return str(item).strip()


def unwrap_envelope(
    data: Any,
    *,
    candidate_keys: Iterable[str] = ("teses", "items", "results", "data", "lista", "list"),
) -> Any:
    """If ``data`` is a single-key dict whose value matches an envelope, return it.

    Examples it handles::

        {"teses": [...]}        -> [...]
        {"items": {...}}        -> {...}
        {"data": {"teses": [...]}} -> [...]   (recursive once)
    """
    if not isinstance(data, dict):
        return data
    for key in candidate_keys:
        if key in data and isinstance(data[key], (list, dict)):
            inner = data[key]
            # Allow one extra level of unwrapping ({"data":{"teses":[...]}}).
            if isinstance(inner, dict):
                for nested_key in candidate_keys:
                    if nested_key in inner and isinstance(inner[nested_key], (list, dict)):
                        return inner[nested_key]
            return inner
    return data

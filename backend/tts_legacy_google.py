from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Generator

import requests


DEFAULT_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"


@dataclass(frozen=True)
class LegacyGoogleTTSConfig:
    api_key: str
    voice_name: str = "pt-BR-Neural2-B"
    language_code: str = "pt-BR"
    speaking_rate: float = 1.2
    pitch_semitones: float = -4.5
    max_ssml_chars: int = 5000
    timeout_ms: int = 45000
    endpoint: str = DEFAULT_ENDPOINT


LogEventFn = Callable[..., None]
NormalizeFn = Callable[[str], str]
SplitFn = Callable[[str, int], list[str]]
BuildSSMLFn = Callable[[str], str]


def _log(log_event: LogEventFn | None, event: str, trace_id: str, **fields: Any) -> None:
    if not callable(log_event):
        return
    try:
        log_event(event, trace_id, **fields)
    except Exception:
        return


def _extract_error_detail(resp: requests.Response) -> str:
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "").strip()
                if message:
                    return message
        return json.dumps(payload, ensure_ascii=False)[:300]
    except Exception:
        return (resp.text or "")[:300]


def _build_endpoint_with_key(endpoint: str, api_key: str) -> str:
    base = (endpoint or DEFAULT_ENDPOINT).strip() or DEFAULT_ENDPOINT
    joiner = "&" if "?" in base else "?"
    return f"{base}{joiner}key={api_key}"


def _request_chunk_audio(
    *,
    ssml: str,
    config: LegacyGoogleTTSConfig,
) -> bytes:
    payload = {
        "input": {"ssml": ssml},
        "voice": {"languageCode": config.language_code, "name": config.voice_name},
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": float(config.speaking_rate),
            "pitch": float(config.pitch_semitones),
        },
    }
    timeout_seconds = max(5.0, min(float(config.timeout_ms) / 1000.0, 300.0))
    response = requests.post(
        _build_endpoint_with_key(config.endpoint, config.api_key),
        json=payload,
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        raise RuntimeError(f"Falha no TTS Google ({response.status_code}): {detail}")

    data = response.json()
    b64 = str((data or {}).get("audioContent") or "").strip()
    if not b64:
        raise RuntimeError("Falha no TTS Google: resposta sem audioContent.")
    try:
        return base64.b64decode(b64)
    except Exception as exc:
        raise RuntimeError("Falha no TTS Google: audioContent invalido.") from exc


def _prepare_chunks(
    *,
    text: str,
    config: LegacyGoogleTTSConfig,
    normalize_for_tts: NormalizeFn,
    split_tts_chunks: SplitFn,
) -> tuple[str, list[str]]:
    if not (config.api_key or "").strip():
        raise RuntimeError("GOOGLE_TTS_API_KEY (ou GEMINI_API_KEY) nao configurada para TTS.")

    prepared = normalize_for_tts(text)
    max_chars = max(250, min(int(config.max_ssml_chars or 5000), 5000))
    chunks = split_tts_chunks(prepared, max_chars)
    return prepared, chunks


def synthesize_legacy_google_tts(
    *,
    text: str,
    trace_id: str,
    config: LegacyGoogleTTSConfig,
    normalize_for_tts: NormalizeFn,
    split_tts_chunks: SplitFn,
    build_ssml: BuildSSMLFn,
    log_event: LogEventFn | None = None,
) -> tuple[bytes, str]:
    prepared, chunks = _prepare_chunks(
        text=text,
        config=config,
        normalize_for_tts=normalize_for_tts,
        split_tts_chunks=split_tts_chunks,
    )
    started = time.perf_counter()
    _log(
        log_event,
        "tts_legacy_start",
        trace_id,
        chars=len(prepared),
        chunks=len(chunks),
        voice=config.voice_name,
        language=config.language_code,
        timeout_ms=config.timeout_ms,
    )

    parts: list[bytes] = []
    for idx, chunk in enumerate(chunks, start=1):
        ssml = build_ssml(chunk)
        ssml_bytes = len(ssml.encode("utf-8"))
        if ssml_bytes > int(config.max_ssml_chars):
            raise RuntimeError(
                f"Falha no TTS Google: bloco SSML com {ssml_bytes} bytes excede o limite de {int(config.max_ssml_chars)} bytes."
            )
        chunk_started = time.perf_counter()
        _log(log_event, "tts_legacy_chunk_start", trace_id, chunk_index=idx, chunk_chars=len(chunk))
        audio = _request_chunk_audio(ssml=ssml, config=config)
        parts.append(audio)
        _log(
            log_event,
            "tts_legacy_chunk_ok",
            trace_id,
            chunk_index=idx,
            chunk_chars=len(chunk),
            audio_bytes=len(audio),
            duration_ms=int((time.perf_counter() - chunk_started) * 1000),
        )

    merged = b"".join(parts)
    _log(
        log_event,
        "tts_legacy_success",
        trace_id,
        output_bytes=len(merged),
        total_duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return merged, "audio/mpeg"


def stream_legacy_google_tts_chunks(
    *,
    text: str,
    trace_id: str,
    config: LegacyGoogleTTSConfig,
    normalize_for_tts: NormalizeFn,
    split_tts_chunks: SplitFn,
    build_ssml: BuildSSMLFn,
    log_event: LogEventFn | None = None,
) -> Generator[tuple[bytes, str, int, int], None, None]:
    prepared, chunks = _prepare_chunks(
        text=text,
        config=config,
        normalize_for_tts=normalize_for_tts,
        split_tts_chunks=split_tts_chunks,
    )
    total_chunks = len(chunks)
    _log(
        log_event,
        "tts_legacy_stream_start",
        trace_id,
        chars=len(prepared),
        chunks=total_chunks,
        voice=config.voice_name,
        language=config.language_code,
        timeout_ms=config.timeout_ms,
    )

    for idx, chunk in enumerate(chunks, start=1):
        ssml = build_ssml(chunk)
        ssml_bytes = len(ssml.encode("utf-8"))
        if ssml_bytes > int(config.max_ssml_chars):
            raise RuntimeError(
                f"Falha no TTS Google: bloco SSML com {ssml_bytes} bytes excede o limite de {int(config.max_ssml_chars)} bytes."
            )
        chunk_started = time.perf_counter()
        _log(log_event, "tts_legacy_stream_chunk_start", trace_id, chunk_index=idx, chunk_chars=len(chunk))
        audio = _request_chunk_audio(ssml=ssml, config=config)
        _log(
            log_event,
            "tts_legacy_stream_chunk_ok",
            trace_id,
            chunk_index=idx,
            chunk_chars=len(chunk),
            audio_bytes=len(audio),
            duration_ms=int((time.perf_counter() - chunk_started) * 1000),
        )
        yield audio, "audio/mpeg", idx, total_chunks

    _log(log_event, "tts_legacy_stream_done", trace_id, chunks_emitted=total_chunks)

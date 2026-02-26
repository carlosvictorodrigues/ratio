from __future__ import annotations

import base64
import copy
import html
import io
import json
import logging
import hashlib
import os
import queue
import re
import threading
import sys
import time
import uuid
import wave
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import httpx
try:
    import lancedb
except Exception:  # pragma: no cover - optional runtime dependency in some test harnesses
    lancedb = None
try:
    import pyarrow as pa
except Exception:  # pragma: no cover - optional runtime dependency in some test harnesses
    pa = None
try:
    import fitz
except Exception:  # pragma: no cover - optional runtime dependency in some test harnesses
    fitz = None
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field
from backend.tts_legacy_google import (
    DEFAULT_ENDPOINT as LEGACY_TTS_DEFAULT_ENDPOINT,
    LegacyGoogleTTSConfig,
    stream_legacy_google_tts_chunks as _run_legacy_tts_stream,
    synthesize_legacy_google_tts as _run_legacy_tts_sync,
)

def _resolve_project_root() -> Path:
    raw = (os.getenv("RATIO_PROJECT_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = _resolve_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.query import (  # noqa: E402
    EXPLAIN_MODEL,
    GEMINI_RERANK_MODEL,
    GENERATION_MODEL,
    RERANKER_BACKEND,
    RERANKER_MODEL,
    configure_gemini_api_key,
    explain_answer,
    get_gemini_client,
    get_supported_generation_models,
    get_rag_tuning_defaults,
    get_rag_tuning_schema,
    has_gemini_api_key,
    orgao_label,
    run_query,
    type_label,
)


def _runtime_logs_dir() -> Path:
    runtime_dir = PROJECT_ROOT / "logs" / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return PROJECT_ROOT
    return runtime_dir


_TTS_LOGGER = logging.getLogger("ratio.tts")
if not _TTS_LOGGER.handlers:
    _TTS_LOGGER.setLevel(logging.INFO)
    _TTS_LOGGER.propagate = False
    _formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_formatter)
    _TTS_LOGGER.addHandler(_stream_handler)

    try:
        _file_handler = logging.FileHandler(_runtime_logs_dir() / "tts_backend.log", encoding="utf-8")
        _file_handler.setFormatter(_formatter)
        _TTS_LOGGER.addHandler(_file_handler)
    except Exception:
        pass

_ACERVO_LOGGER = logging.getLogger("ratio.acervo")
if not _ACERVO_LOGGER.handlers:
    _ACERVO_LOGGER.setLevel(logging.INFO)
    _ACERVO_LOGGER.propagate = False
    _formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_formatter)
    _ACERVO_LOGGER.addHandler(_stream_handler)

    try:
        _file_handler = logging.FileHandler(_runtime_logs_dir() / "acervo_backend.log", encoding="utf-8")
        _file_handler.setFormatter(_formatter)
        _ACERVO_LOGGER.addHandler(_file_handler)
    except Exception:
        pass


def _new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def _log_tts_event(event: str, trace_id: str, **fields: Any) -> None:
    payload: dict[str, Any] = {"event": event, "trace_id": trace_id}
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = value
    try:
        _TTS_LOGGER.info(json.dumps(payload, ensure_ascii=False))
    except Exception:
        _TTS_LOGGER.info("%s trace_id=%s", event, trace_id)


class _TTSModelUnavailableError(RuntimeError):
    pass


class _TTSTransientError(RuntimeError):
    pass


def _tts_cache_dir() -> Path:
    cache_dir = _runtime_logs_dir() / "tts_cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return _runtime_logs_dir()
    return cache_dir


def _tts_chunk_cache_key(model_name: str, voice_name: str, language_code: str, content: str) -> str:
    raw = f"{model_name}|{voice_name}|{language_code}|{content}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def _tts_load_cached_chunk(cache_key: str) -> tuple[bytes, str] | None:
    if not TTS_CACHE_ENABLED:
        return None
    cache_dir = _tts_cache_dir()
    audio_path = cache_dir / f"{cache_key}.bin"
    meta_path = cache_dir / f"{cache_key}.json"
    if not audio_path.exists() or not meta_path.exists():
        return None
    try:
        audio_bytes = audio_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        mime_type = str(meta.get("mime_type") or "audio/wav").strip() or "audio/wav"
        if not audio_bytes:
            return None
        return audio_bytes, mime_type
    except Exception:
        return None


def _tts_store_cached_chunk(cache_key: str, audio_bytes: bytes, mime_type: str) -> None:
    if not TTS_CACHE_ENABLED:
        return
    if not audio_bytes:
        return
    cache_dir = _tts_cache_dir()
    audio_path = cache_dir / f"{cache_key}.bin"
    meta_path = cache_dir / f"{cache_key}.json"
    try:
        audio_path.write_bytes(audio_bytes)
        meta_path.write_text(
            json.dumps({"mime_type": mime_type or "audio/wav"}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        return


def _get_tts_httpx_client(timeout_ms: int) -> httpx.Client:
    normalized_timeout_ms = max(5000, min(int(timeout_ms or 60000), 600000))
    with _TTS_HTTPX_CLIENTS_LOCK:
        existing = _TTS_HTTPX_CLIENTS.get(normalized_timeout_ms)
        if existing is not None:
            return existing

        timeout_s = normalized_timeout_ms / 1000.0
        connect_s = min(10.0, timeout_s)
        timeout = httpx.Timeout(
            timeout=timeout_s,
            connect=connect_s,
            read=timeout_s,
            write=timeout_s,
            pool=min(15.0, timeout_s),
        )
        client = httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        _TTS_HTTPX_CLIENTS[normalized_timeout_ms] = client
        return client


def _get_acervo_httpx_client(timeout_ms: int) -> httpx.Client:
    normalized_timeout_ms = max(5000, min(int(timeout_ms or 60000), 600000))
    with _ACERVO_HTTPX_CLIENTS_LOCK:
        existing = _ACERVO_HTTPX_CLIENTS.get(normalized_timeout_ms)
        if existing is not None:
            return existing

        timeout_s = normalized_timeout_ms / 1000.0
        connect_s = min(10.0, timeout_s)
        timeout = httpx.Timeout(
            timeout=timeout_s,
            connect=connect_s,
            read=timeout_s,
            write=timeout_s,
            pool=min(15.0, timeout_s),
        )
        client = httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        _ACERVO_HTTPX_CLIENTS[normalized_timeout_ms] = client
        return client

app = FastAPI(
    title="Ratio API - Pesquisa Jurisprudencial",
    version="1.0.0",
    description="Backend desacoplado para consulta RAG STF/STJ.",
)

RAG_CONFIG_VERSION = "2026-02-24-rich-default-v4-gemini-3-flash-preview-default"

DEFAULT_CORS_ORIGINS = "http://127.0.0.1:5500,http://localhost:5500"
cors_origins = [o.strip() for o in os.getenv("API_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o.strip()]
if not cors_origins:
    cors_origins = [origin.strip() for origin in DEFAULT_CORS_ORIGINS.split(",") if origin.strip()]

# Browsers reject allow_credentials with wildcard origin and this widens CSRF surface.
allow_credentials = "*" not in cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)
    tribunais: Optional[list[str]] = None
    tipos: Optional[list[str]] = None
    sources: Optional[list[str]] = None
    ramos: Optional[list[str]] = None
    orgaos: Optional[list[str]] = None
    relator_contains: Optional[str] = Field(default=None, max_length=200)
    date_from: Optional[str] = Field(default=None, max_length=10)
    date_to: Optional[str] = Field(default=None, max_length=10)
    prefer_recent: bool = True
    prefer_user_sources: bool = True
    reranker_backend: Literal["local", "gemini"] = "local"
    rag_config: Optional[dict[str, Any]] = None
    trace: bool = False


class ExplainRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=40000)
    docs: Optional[list[dict[str, Any]]] = None
    model_name: Optional[str] = Field(default=None, max_length=120)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=120000)


class GeminiConfigRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    api_key: str = Field(min_length=8, max_length=400)
    persist_env: bool = True
    validate_key: bool = Field(default=True, alias="validate")
    test_model: Optional[str] = Field(default=GENERATION_MODEL, max_length=120)
    validation_timeout_ms: int = Field(
        default=int(os.getenv("GEMINI_KEY_VALIDATION_TIMEOUT_MS", "12000")),
        ge=3000,
        le=120000,
    )


class UserSourceActionRequest(BaseModel):
    source_id: str = Field(min_length=4, max_length=120)


# TTS profile aligned with the configured extension voice.
def _normalize_tts_provider(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in {"legacy", "legacy_google", "google", "google_cloud", "gcloud", "google-legacy"}:
        return "legacy_google"
    if value in {"gemini", "gemini_native", "gemini-native", "gemini_preview", "gemini-native-preview"}:
        return "gemini_native"
    return "legacy_google"


TTS_PROVIDER = _normalize_tts_provider(os.getenv("TTS_PROVIDER", "legacy_google"))
TTS_RATE = 1.2
TTS_PITCH_SEMITONES = -4.5
TTS_BREAK_ALT_MS = 450
TTS_BREAK_ART_MS = 900
try:
    TTS_MAX_CHARS = int(os.getenv("GEMINI_TTS_MAX_CHARS", "400"))
except (TypeError, ValueError):
    TTS_MAX_CHARS = 400
TTS_MAX_CHARS = max(250, min(TTS_MAX_CHARS, 5000))
TTS_ALTERNATIVE_LABEL = os.getenv("TTS_ALTERNATIVE_LABEL", "Alternativa")
TTS_MARK_ALT = "[[BRK_ALT]]"
TTS_MARK_ART = "[[BRK_ART]]"
TTS_VOICE_NAME = (os.getenv("GEMINI_TTS_VOICE") or "charon").strip() or "charon"
TTS_LANGUAGE_CODE = os.getenv("TTS_LANGUAGE_CODE", "pt-BR")
TTS_MODEL = (os.getenv("GEMINI_TTS_MODEL") or "gemini-2.5-flash-preview-tts").strip()
TTS_FALLBACK_MODELS_RAW = (
    os.getenv("GEMINI_TTS_FALLBACK_MODELS")
    or ""
)
TTS_FALLBACK_MODELS = [m.strip() for m in TTS_FALLBACK_MODELS_RAW.split(",") if m.strip()]
TTS_REQUEST_TIMEOUT_MS = int(os.getenv("GEMINI_TTS_REQUEST_TIMEOUT_MS", "120000"))
TTS_REQUEST_RETRY_ATTEMPTS = int(os.getenv("GEMINI_TTS_REQUEST_RETRY_ATTEMPTS", "1"))
TTS_MODEL_MAX_ATTEMPTS = int(os.getenv("GEMINI_TTS_MODEL_MAX_ATTEMPTS", "2"))
TTS_PREFETCH_CONCURRENCY = max(
    1,
    min(int(os.getenv("GEMINI_TTS_PREFETCH_CONCURRENCY", "1")), 6),
)
TTS_CACHE_ENABLED = os.getenv("GEMINI_TTS_CACHE_ENABLED", "1").strip() != "0"
LEGACY_TTS_VOICE_NAME = (os.getenv("GOOGLE_TTS_VOICE_NAME") or "pt-BR-Neural2-B").strip() or "pt-BR-Neural2-B"
LEGACY_TTS_ENDPOINT = (
    (os.getenv("GOOGLE_TTS_ENDPOINT") or LEGACY_TTS_DEFAULT_ENDPOINT).strip()
    or LEGACY_TTS_DEFAULT_ENDPOINT
)
try:
    LEGACY_TTS_MAX_CHARS = int(os.getenv("GOOGLE_TTS_MAX_CHARS", "5000"))
except (TypeError, ValueError):
    LEGACY_TTS_MAX_CHARS = 5000
LEGACY_TTS_MAX_CHARS = max(250, min(LEGACY_TTS_MAX_CHARS, 5000))
LEGACY_TTS_REQUEST_TIMEOUT_MS = max(
    10000,
    min(int(os.getenv("GOOGLE_TTS_REQUEST_TIMEOUT_MS", "45000")), 300000),
)
LEGACY_GCLOUD_TO_GEMINI_VOICE = {
    "pt-BR-Neural2-B": "charon",
    "pt-BR-Neural2-C": "kore",
    "pt-BR-Neural2-A": "leda",
}
USER_ACERVO_TABLE = (os.getenv("USER_ACERVO_TABLE") or "meu_acervo").strip() or "meu_acervo"
USER_ACERVO_MANIFEST = _runtime_logs_dir() / "meu_acervo_manifest.json"
USER_ACERVO_UPLOAD_DIR = _runtime_logs_dir() / "meu_acervo_uploads"
USER_ACERVO_LANCE_DIR = PROJECT_ROOT / "lancedb_store"
USER_ACERVO_CHUNK_CHARS = max(500, min(int(os.getenv("USER_ACERVO_CHUNK_CHARS", "1400")), 4000))
USER_ACERVO_MAX_FILES_PER_REQUEST = max(1, min(int(os.getenv("USER_ACERVO_MAX_FILES_PER_REQUEST", "24")), 100))
USER_ACERVO_MAX_FILE_SIZE_MB = max(1, min(int(os.getenv("USER_ACERVO_MAX_FILE_SIZE_MB", "1024")), 10240))
USER_ACERVO_MAX_REQUEST_SIZE_MB = max(
    USER_ACERVO_MAX_FILE_SIZE_MB,
    min(int(os.getenv("USER_ACERVO_MAX_REQUEST_SIZE_MB", "16384")), 30720),
)
USER_ACERVO_MAX_FILE_SIZE_BYTES = USER_ACERVO_MAX_FILE_SIZE_MB * 1024 * 1024
USER_ACERVO_MAX_REQUEST_SIZE_BYTES = USER_ACERVO_MAX_REQUEST_SIZE_MB * 1024 * 1024
USER_ACERVO_CLEAN_MODEL = (os.getenv("USER_ACERVO_CLEAN_MODEL") or "gemini-2.5-flash").strip() or "gemini-2.5-flash"
USER_ACERVO_OCR_MODEL = (os.getenv("USER_ACERVO_OCR_MODEL") or "gemini-2.5-flash").strip() or "gemini-2.5-flash"
USER_ACERVO_EMBED_MODEL = (os.getenv("USER_ACERVO_EMBED_MODEL") or "gemini-embedding-001").strip() or "gemini-embedding-001"
USER_ACERVO_REQUIRE_CONFIRM = os.getenv("USER_ACERVO_REQUIRE_CONFIRM", "1").strip() != "0"
USER_ACERVO_OCR_DPI = max(96, min(int(os.getenv("USER_ACERVO_OCR_DPI", "144")), 300))
USER_ACERVO_EMBED_DIM = 768
USER_ACERVO_CLEAN_TIMEOUT_MS = max(
    10000,
    min(int(os.getenv("USER_ACERVO_CLEAN_TIMEOUT_MS", "45000")), 300000),
)
USER_ACERVO_OCR_TIMEOUT_MS = max(
    10000,
    min(int(os.getenv("USER_ACERVO_OCR_TIMEOUT_MS", "90000")), 300000),
)
USER_ACERVO_EMBED_TIMEOUT_MS = max(
    10000,
    min(int(os.getenv("USER_ACERVO_EMBED_TIMEOUT_MS", "120000")), 300000),
)
USER_ACERVO_RETRY_ATTEMPTS = max(
    1,
    min(int(os.getenv("USER_ACERVO_RETRY_ATTEMPTS", "2")), 4),
)
USER_ACERVO_EMBED_BATCH_SIZE = max(
    1,
    min(int(os.getenv("USER_ACERVO_EMBED_BATCH_SIZE", "8")), 32),
)
USER_ACERVO_INDEX_MAX_WORKERS = max(1, min(int(os.getenv("USER_ACERVO_INDEX_MAX_WORKERS", "2")), 8))
USER_ACERVO_INDEX_JOB_POLL_MS = max(500, min(int(os.getenv("USER_ACERVO_INDEX_JOB_POLL_MS", "1200")), 10000))
USER_ACERVO_INDEX_JOB_TTL_SECONDS = max(600, min(int(os.getenv("USER_ACERVO_INDEX_JOB_TTL_SECONDS", "21600")), 86400))

_USER_ACERVO_JOBS: dict[str, dict[str, Any]] = {}
_USER_ACERVO_JOBS_LOCK = threading.Lock()
_USER_ACERVO_WRITE_LOCK = threading.Lock()
_USER_ACERVO_CLEAN_CIRCUIT_UNTIL = 0.0
_USER_ACERVO_CLEAN_CIRCUIT_LOCK = threading.Lock()

LEGAL_TTS_EXPANSIONS = [
    (r"\bHC\b", "habeas corpus"),
    (r"\bRHC\b", "recurso ordinário em habeas corpus"),
    (r"\bMS\b", "mandado de segurança"),
    (r"\bRMS\b", "recurso ordinário em mandado de segurança"),
    (r"\bREsp\b", "recurso especial"),
    (r"\bRE\b", "recurso extraordinário"),
    (r"\bARE\b", "agravo em recurso extraordinário"),
    (r"\bAI\b", "agravo de instrumento"),
    (r"\bAgInt\b", "agravo interno"),
    (r"\bAgR\b", "agravo regimental"),
    (r"\bAgRg\b", "agravo regimental"),
    (r"\bEDcl\b", "embargos de declaração"),
    (r"\bADI\b", "ação direta de inconstitucionalidade"),
    (r"\bADC\b", "ação declaratória de constitucionalidade"),
    (r"\bADPF\b", "arguição de descumprimento de preceito fundamental"),
    (r"\bIRDR\b", "incidente de resolução de demandas repetitivas"),
    (r"\bIAC\b", "incidente de assunção de competência"),
    (r"\bRG\b", "repercussão geral"),
    (r"\bSTF\b", "Supremo Tribunal Federal"),
    (r"\bSTJ\b", "Superior Tribunal de Justiça"),
    (r"\bCPC\b", "Código de Processo Civil"),
    (r"\bCPP\b", "Código de Processo Penal"),
    (r"\bCF\b", "Constituição Federal"),
]

TTS_PRONUNCIATION_FIXES = [
    (r"\bjustica\b", "justiça"),
    (r"\bjudiciario\b", "judiciário"),
    (r"\bjuridico\b", "jurídico"),
    (r"\bjuridica\b", "jurídica"),
    (r"\bconstituicao\b", "constituição"),
    (r"\bcodigo\b", "código"),
    (r"\brepercussao\b", "repercussão"),
    (r"\bdecisao\b", "decisão"),
    (r"\bacordao\b", "acórdão"),
    (r"\bsumula\b", "súmula"),
    (r"\bparagrafo\b", "parágrafo"),
    (r"\bnao\b", "não"),
]

DOC_CITATION_BRACKET_PATTERN = re.compile(
    r"\[(?=[^\]]*(?:DOC(?:UMENTO)?\.?|DOCUMENTO))(?=[^\]]*(?:\d+|[Nn]))[^\]]*\]",
    flags=re.IGNORECASE,
)

_TTS_HTTPX_CLIENTS: dict[int, httpx.Client] = {}
_TTS_HTTPX_CLIENTS_LOCK = threading.Lock()
_ACERVO_HTTPX_CLIENTS: dict[int, httpx.Client] = {}
_ACERVO_HTTPX_CLIENTS_LOCK = threading.Lock()


def _short(text: str, max_chars: int = 1200) -> str:
    value = (text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _extract_normative_statement_from_row(row: dict[str, Any], max_chars: int = 260) -> str:
    tipo = (row.get("tipo") or "").strip().lower()
    merged = "\n".join([
        str(row.get("texto_busca") or ""),
        str(row.get("texto_integral") or ""),
    ])
    text = _normalize_for_tts(merged)
    if not text:
        return ""

    norm = re.sub(r"\s+", " ", text).strip().lower()
    structural_types = {"sumula", "sumula_stj", "sumula_vinculante", "tema_repetitivo_stj"}
    if tipo not in structural_types:
        if tipo not in {"acordao", "acordao_sv"}:
            return ""
        if not re.search(r"\brepercuss(?:ao|ão)\s+geral\b", norm) and not re.search(r"\btema\s+\d+\b", norm):
            return ""

    patterns = (
        r"(?im)\benunciado\s*:\s*(.+)",
        r"(?im)\btese(?:\s+fixada|\s+firmada)?\s*:\s*(.+)",
        r"(?im)\bementa\s*:\s*(.+)",
        r"(?im)\btema\s*:\s*(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(1)).strip(" -:")
        if len(candidate) >= 24:
            return _short(candidate, max_chars=max_chars)

    for line in text.splitlines():
        candidate = re.sub(r"\s+", " ", line).strip(" -:")
        if len(candidate) < 28:
            continue
        if candidate.lower().startswith(("processo:", "origem:", "relator:", "orgao julgador:", "ramo:", "data:")):
            continue
        if re.match(r"(?i)^(stf|stj)\s+", candidate):
            continue
        candidate = re.sub(
            r"(?i)^(sumula(?:\s+stj)?\s*\d+|sumula vinculante\s*\d+|tema repetitivo\s*\d+|tema\s*\d+)\s*[:\-]\s*",
            "",
            candidate,
        )
        if len(candidate) >= 24:
            return _short(candidate, max_chars=max_chars)
    return ""


def _normalize_for_tts(raw: str) -> str:
    text = html.unescape((raw or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h\d|section|article)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)<[^>]+>", "", text)

    text = re.sub(r"(?is)\[\s*AVISO DE AUDITORIA[^\n]*?(?:\n|$).*?(?=\n\s*Documentos citados(?:\s*\([^\n]*\))?:|\Z)", "", text)
    text = re.sub(r"(?is)\n\s*Documentos citados(?:\s*\([^\n]*\))?:\s*.*$", "", text)
    text = DOC_CITATION_BRACKET_PATTERN.sub("", text)
    text = re.sub(r"(?m)^\s*>\s*", "", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "").replace("*", "")
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)

    for pattern, expanded in LEGAL_TTS_EXPANSIONS:
        text = re.sub(pattern, expanded, text, flags=re.IGNORECASE)
    for pattern, fixed in TTS_PRONUNCIATION_FIXES:
        text = re.sub(pattern, fixed, text, flags=re.IGNORECASE)

    alt_pattern = r"(?im)^\s*[\(\[]?([A-E])[\)\]\.\-:]\s*"
    text = re.sub(
        alt_pattern,
        lambda m: f"{TTS_MARK_ALT}{TTS_ALTERNATIVE_LABEL} {m.group(1)}. ",
        text,
    )

    text = re.sub(
        r"\bart\.\s*(\d+[A-Za-z\-]*)",
        lambda m: f"artigo {m.group(1)} {TTS_MARK_ART}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b[Â]?[§]\s*(\d+[A-Za-z\-]*)", r"paragrafo \1", text)
    text = text.replace(TTS_MARK_ALT, f" {TTS_MARK_ALT} ").replace(TTS_MARK_ART, f" {TTS_MARK_ART} ")
    return re.sub(r"\s+", " ", text).strip()


def _build_ssml(chunk: str) -> str:
    escaped = html.escape(chunk or "")
    escaped = escaped.replace(TTS_MARK_ALT, f"<break time='{TTS_BREAK_ALT_MS}ms'/>")
    escaped = escaped.replace(TTS_MARK_ART, f"<break time='{TTS_BREAK_ART_MS}ms'/>")
    return f"<speak>{escaped}</speak>"


def _ssml_bytes(chunk: str) -> int:
    return len(_build_ssml(chunk).encode("utf-8"))


def _slice_prefix_within_ssml_limit(text: str, max_ssml_bytes: int) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    if _ssml_bytes(value) <= max_ssml_bytes:
        return value

    lo, hi = 1, len(value)
    best = 1
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = value[:mid].rstrip()
        if not candidate:
            lo = mid + 1
            continue
        if _ssml_bytes(candidate) <= max_ssml_bytes:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    cut = best
    if cut < len(value):
        ws = max(value.rfind(" ", 0, cut), value.rfind("\n", 0, cut), value.rfind("\t", 0, cut))
        if ws > 0 and ws >= int(cut * 0.6):
            cut = ws

    head = value[:cut].strip()
    if head and _ssml_bytes(head) <= max_ssml_bytes:
        return head
    head = value[:best].strip()
    if head and _ssml_bytes(head) <= max_ssml_bytes:
        return head
    return value[0]


def _split_by_ssml_limit(text: str, max_ssml_bytes: int) -> list[str]:
    value = (text or "").strip()
    if not value:
        return [""]
    if _ssml_bytes(value) <= max_ssml_bytes:
        return [value]

    parts: list[str] = []
    remaining = value
    while remaining:
        piece = _slice_prefix_within_ssml_limit(remaining, max_ssml_bytes)
        if not piece:
            break
        parts.append(piece)
        remaining = remaining[len(piece) :].strip()
        if remaining and _ssml_bytes(remaining) <= max_ssml_bytes:
            parts.append(remaining)
            break
    return parts or [value]


def _split_tts_chunks(text: str, max_ssml_bytes: int = TTS_MAX_CHARS) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[\.\!\?;:])\s+", text or "") if s.strip()]
    if not sentences:
        return [text or ""]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if candidate and _ssml_bytes(candidate) <= max_ssml_bytes:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        sentence_parts = _split_by_ssml_limit(sentence, max_ssml_bytes)
        if not sentence_parts:
            continue
        if len(sentence_parts) == 1:
            current = sentence_parts[0]
            continue
        chunks.extend(sentence_parts[:-1])
        current = sentence_parts[-1]

    if current:
        chunks.append(current)
    return chunks or [text or ""]


def _normalize_voice_name_for_gemini(voice_name: str) -> str:
    raw = (voice_name or "").strip()
    if not raw:
        return "charon"
    mapped = LEGACY_GCLOUD_TO_GEMINI_VOICE.get(raw, raw)
    return mapped.strip().lower() or "charon"


def _tts_candidate_models() -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in [TTS_MODEL, *TTS_FALLBACK_MODELS]:
        model = (raw or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        candidates.append(model)
    return candidates or ["gemini-2.5-flash-preview-tts"]


def _legacy_tts_api_key() -> str:
    return (os.getenv("GOOGLE_TTS_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()


def _tts_response_voice() -> str:
    if TTS_PROVIDER == "legacy_google":
        return LEGACY_TTS_VOICE_NAME
    return _normalize_voice_name_for_gemini(TTS_VOICE_NAME)


def _tts_response_model() -> str:
    if TTS_PROVIDER == "legacy_google":
        return "google-cloud-text-to-speech"
    return TTS_MODEL


def _tts_response_max_chars() -> int:
    if TTS_PROVIDER == "legacy_google":
        return LEGACY_TTS_MAX_CHARS
    return TTS_MAX_CHARS


def _prepare_chunk_for_gemini_tts(chunk: str) -> str:
    value = (chunk or "")
    value = value.replace(TTS_MARK_ALT, ". ")
    value = value.replace(TTS_MARK_ART, ". ")
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


def _is_wav_mime(mime_type: str) -> bool:
    norm = (mime_type or "").strip().lower()
    return norm in {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"}


def _is_pcm_mime(mime_type: str) -> bool:
    norm = (mime_type or "").strip().lower()
    if not norm:
        return False
    if norm.startswith("audio/l16"):
        return True
    if "audio/pcm" in norm or "audio/x-pcm" in norm or "audio/lpcm" in norm or "audio/raw" in norm:
        return True
    return "codec=pcm" in norm


def _parse_pcm_mime_params(mime_type: str) -> tuple[int, int, int]:
    norm = (mime_type or "").strip().lower()
    sample_rate = 24000
    channels = 1
    bits_per_sample = 16

    l16_match = re.search(r"audio/l(\d+)", norm)
    if l16_match:
        try:
            bits_per_sample = max(8, min(32, int(l16_match.group(1))))
        except (TypeError, ValueError):
            bits_per_sample = 16

    rate_match = re.search(r"(?:rate|samplerate)\s*=\s*(\d+)", norm)
    if rate_match:
        try:
            sample_rate = max(8000, min(96000, int(rate_match.group(1))))
        except (TypeError, ValueError):
            sample_rate = 24000

    channels_match = re.search(r"(?:channels?|channel-count)\s*=\s*(\d+)", norm)
    if channels_match:
        try:
            channels = max(1, min(8, int(channels_match.group(1))))
        except (TypeError, ValueError):
            channels = 1

    return sample_rate, channels, bits_per_sample


def _pcm_to_wav_bytes(pcm_bytes: bytes, mime_type: str) -> bytes:
    if not pcm_bytes:
        return b""

    sample_rate, channels, bits_per_sample = _parse_pcm_mime_params(mime_type)
    sample_width = max(1, bits_per_sample // 8)
    payload = bytes(pcm_bytes)

    # RFC for audio/L16 uses big-endian samples. WAV PCM expects little-endian.
    if "audio/l16" in (mime_type or "").lower() and sample_width == 2:
        if len(payload) % 2 != 0:
            payload = payload[:-1]
        swapped = bytearray(len(payload))
        swapped[0::2] = payload[1::2]
        swapped[1::2] = payload[0::2]
        payload = bytes(swapped)

    wav_io = io.BytesIO()
    with wave.open(wav_io, "wb") as wav_writer:
        wav_writer.setnchannels(channels)
        wav_writer.setsampwidth(sample_width)
        wav_writer.setframerate(sample_rate)
        wav_writer.writeframes(payload)
    return wav_io.getvalue()


def _merge_wav_audio_chunks(chunks: list[bytes]) -> bytes:
    if not chunks:
        return b""
    if len(chunks) == 1:
        return chunks[0]

    base_params: Optional[tuple[int, int, int, str, str]] = None
    frames: list[bytes] = []
    for idx, chunk in enumerate(chunks, 1):
        try:
            with wave.open(io.BytesIO(chunk), "rb") as wav_reader:
                params = (
                    wav_reader.getnchannels(),
                    wav_reader.getsampwidth(),
                    wav_reader.getframerate(),
                    wav_reader.getcomptype(),
                    wav_reader.getcompname(),
                )
                if base_params is None:
                    base_params = params
                elif params != base_params:
                    raise RuntimeError("formatos de audio diferentes entre blocos")
                frames.append(wav_reader.readframes(wav_reader.getnframes()))
        except Exception as exc:
            raise RuntimeError(f"Falha no TTS: nao foi possivel combinar bloco WAV {idx}. {exc}") from exc

    if base_params is None:
        return b""
    merged = io.BytesIO()
    with wave.open(merged, "wb") as wav_writer:
        wav_writer.setnchannels(base_params[0])
        wav_writer.setsampwidth(base_params[1])
        wav_writer.setframerate(base_params[2])
        wav_writer.setcomptype(base_params[3], base_params[4])
        wav_writer.writeframes(b"".join(frames))
    return merged.getvalue()


def _extract_inline_audio_from_response(response: Any) -> tuple[bytes, str]:
    parts = getattr(response, "parts", None)
    if not parts:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None)
    if not parts:
        raise RuntimeError("Falha no TTS: resposta Gemini sem partes de audio.")

    mime_type = ""
    audio_chunks: list[bytes] = []
    for part in parts:
        inline_data = getattr(part, "inline_data", None)
        if inline_data is None:
            continue
        raw = getattr(inline_data, "data", None)
        if isinstance(raw, str):
            try:
                raw = base64.b64decode(raw)
            except Exception:
                raw = None
        if not isinstance(raw, (bytes, bytearray)):
            continue
        audio_chunks.append(bytes(raw))
        if not mime_type:
            mime_type = str(getattr(inline_data, "mime_type", "") or "").strip().lower()

    if not audio_chunks:
        raise RuntimeError("Falha no TTS: resposta Gemini sem payload de audio inline_data.")

    if _is_wav_mime(mime_type):
        return _merge_wav_audio_chunks(audio_chunks), "audio/wav"
    if _is_pcm_mime(mime_type):
        return _pcm_to_wav_bytes(b"".join(audio_chunks), mime_type), "audio/wav"
    return b"".join(audio_chunks), (mime_type or "audio/mpeg")


def _combine_audio_chunks(parts: list[tuple[bytes, str]]) -> tuple[bytes, str]:
    valid = [(audio, mime) for audio, mime in parts if audio]
    if not valid:
        raise RuntimeError("Falha no TTS: nenhum bloco de audio foi retornado.")

    if len(valid) == 1:
        audio, mime = valid[0]
        return audio, (mime or "audio/wav")

    mimes = [str(mime or "").strip().lower() for _, mime in valid]
    if all(_is_wav_mime(mime) or not mime for mime in mimes):
        return _merge_wav_audio_chunks([audio for audio, _ in valid]), "audio/wav"

    first = mimes[0] or "audio/mpeg"
    if all((mime or first) == first for mime in mimes):
        return b"".join(audio for audio, _ in valid), first

    raise RuntimeError("Falha no TTS: blocos de audio retornaram mime_types diferentes.")


def _is_model_unavailable_error(exc: Exception) -> bool:
    norm = str(exc or "").lower()
    if "multi-modal output is not supported" in norm:
        return True
    if "does not support the requested response modalities: audio" in norm:
        return True
    if "model" in norm and ("not found" in norm or "unsupported" in norm or "not available" in norm):
        return True
    return False


def _is_tts_retryable_error(exc: Exception) -> bool:
    norm = str(exc or "").lower()
    soft_markers = (
        "falha no tts: resposta gemini sem partes de audio",
        "falha no tts: resposta gemini sem payload de audio",
        "timeout",
        "timed out",
        "deadline exceeded",
        "service unavailable",
        "temporarily unavailable",
        "connection error",
        "network error",
        "503",
        "500 internal",
        "an internal error has occurred",
        "status': 'internal'",
        '"status": "internal"',
    )
    return any(marker in norm for marker in soft_markers)


def _synthesize_google_tts(text: str, trace_id: str | None = None) -> tuple[bytes, str]:
    if not has_gemini_api_key():
        raise RuntimeError("GEMINI_API_KEY nao configurada para TTS.")

    trace = (trace_id or "").strip() or _new_trace_id()
    prepared = _normalize_for_tts(text)
    chunks = _split_tts_chunks(prepared)
    voice_name = _normalize_voice_name_for_gemini(TTS_VOICE_NAME)
    model_candidates = _tts_candidate_models()
    last_error: Optional[Exception] = None
    timeout_ms = max(10000, min(int(TTS_REQUEST_TIMEOUT_MS or 120000), 600000))
    retry_attempts = max(1, min(int(TTS_REQUEST_RETRY_ATTEMPTS or 1), 3))
    chunk_attempts = max(1, min(int(TTS_MODEL_MAX_ATTEMPTS or 2), 4))
    http_client = _get_tts_httpx_client(timeout_ms)
    total_started = time.perf_counter()

    _log_tts_event(
        "tts_start",
        trace,
        chars=len(prepared),
        chunks=len(chunks),
        model_candidates=model_candidates,
        timeout_ms=timeout_ms,
        retry_attempts=retry_attempts,
        chunk_attempts=chunk_attempts,
        voice=voice_name,
        language=TTS_LANGUAGE_CODE,
    )

    unavailable_models: set[str] = set()
    for model_name in model_candidates:
        model_started = time.perf_counter()
        audio_parts: list[tuple[bytes, str]] = []
        model_failed = False
        model_unavailable = False

        _log_tts_event(
            "tts_model_start",
            trace,
            model=model_name,
            total_chunks=len(chunks),
        )

        for chunk_idx, chunk in enumerate(chunks, start=1):
            content = _prepare_chunk_for_gemini_tts(chunk)
            if not content:
                continue

            chunk_ok = False
            for attempt in range(1, chunk_attempts + 1):
                chunk_started = time.perf_counter()
                _log_tts_event(
                    "tts_chunk_attempt_start",
                    trace,
                    model=model_name,
                    chunk_index=chunk_idx,
                    attempt=attempt,
                    chunk_chars=len(content),
                )
                try:
                    response = get_gemini_client().models.generate_content(
                        model=model_name,
                        contents=content,
                        config=types.GenerateContentConfig(
                            response_modalities=["audio"],
                            speech_config=types.SpeechConfig(
                                language_code=TTS_LANGUAGE_CODE,
                                voice_config=types.VoiceConfig(
                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                        voice_name=voice_name
                                    )
                                ),
                            ),
                            temperature=0.1,
                            http_options=types.HttpOptions(
                                timeout=timeout_ms,
                                retry_options=types.HttpRetryOptions(attempts=retry_attempts),
                                httpx_client=http_client,
                            ),
                        ),
                    )
                    audio_bytes, mime_type = _extract_inline_audio_from_response(response)
                    audio_parts.append((audio_bytes, mime_type))
                    chunk_ok = True
                    _log_tts_event(
                        "tts_chunk_ok",
                        trace,
                        model=model_name,
                        attempt=attempt,
                        chunk_index=chunk_idx,
                        chunk_chars=len(content),
                        audio_bytes=len(audio_bytes),
                        mime_type=mime_type,
                        duration_ms=int((time.perf_counter() - chunk_started) * 1000),
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    is_unavailable = _is_model_unavailable_error(exc)
                    retryable = _is_tts_retryable_error(exc)
                    _log_tts_event(
                        "tts_chunk_attempt_error",
                        trace,
                        model=model_name,
                        chunk_index=chunk_idx,
                        attempt=attempt,
                        retryable=retryable,
                        model_unavailable=is_unavailable,
                        duration_ms=int((time.perf_counter() - chunk_started) * 1000),
                        error=_short(str(exc), max_chars=600),
                    )
                    if is_unavailable:
                        unavailable_models.add(model_name)
                        model_unavailable = True
                        model_failed = True
                        break
                    if retryable and attempt < chunk_attempts:
                        continue
                    if retryable:
                        model_failed = True
                        break
                    raise RuntimeError(f"Falha no TTS Gemini ({model_name}): {exc}") from exc

            if model_failed or not chunk_ok:
                if not model_unavailable:
                    _log_tts_event(
                        "tts_chunk_exhausted",
                        trace,
                        model=model_name,
                        chunk_index=chunk_idx,
                        chunk_attempts=chunk_attempts,
                        error=_short(str(last_error or "sem erro detalhado"), max_chars=600),
                    )
                break

        if model_unavailable:
            _log_tts_event(
                "tts_model_unavailable",
                trace,
                model=model_name,
                duration_ms=int((time.perf_counter() - model_started) * 1000),
            )
            continue
        if model_failed:
            _log_tts_event(
                "tts_model_failed",
                trace,
                model=model_name,
                duration_ms=int((time.perf_counter() - model_started) * 1000),
                error=_short(str(last_error or "sem erro detalhado"), max_chars=600),
            )
            continue

        merged_audio, merged_mime = _combine_audio_chunks(audio_parts)
        _log_tts_event(
            "tts_success",
            trace,
            model=model_name,
            output_bytes=len(merged_audio),
            mime_type=merged_mime,
            model_duration_ms=int((time.perf_counter() - model_started) * 1000),
            total_duration_ms=int((time.perf_counter() - total_started) * 1000),
        )
        return merged_audio, merged_mime

    tested = ", ".join(model_candidates)
    _log_tts_event(
        "tts_failed_all_models",
        trace,
        tested_models=model_candidates,
        total_duration_ms=int((time.perf_counter() - total_started) * 1000),
        last_error=_short(str(last_error or "sem erro detalhado"), max_chars=600),
    )
    if model_candidates and len(unavailable_models) == len(model_candidates):
        raise RuntimeError(
            f"Falha no TTS Gemini: nenhum modelo de voz suporta audio para esta chave/API. Modelos testados: {tested}."
        ) from last_error
    if last_error is not None:
        raise RuntimeError(
            f"Falha no TTS Gemini: indisponibilidade upstream apos tentativas. Ultimo erro: {last_error}"
        ) from last_error
    raise RuntimeError(
        f"Falha no TTS Gemini: nenhum modelo de voz disponivel para esta chave. Modelos testados: {tested}."
    ) from last_error


def _stream_chunk_root_error(exc: Exception) -> Exception:
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, Exception):
        return cause
    return exc


def _synthesize_stream_chunk_with_retries(
    *,
    trace: str,
    model_name: str,
    chunk_index: int,
    total_chunks: int,
    content: str,
    voice_name: str,
    timeout_ms: int,
    retry_attempts: int,
    chunk_attempts: int,
    http_client: httpx.Client,
) -> tuple[bytes, str]:
    cache_key = _tts_chunk_cache_key(model_name, voice_name, TTS_LANGUAGE_CODE, content)
    cached = _tts_load_cached_chunk(cache_key)
    if cached is not None:
        audio_bytes, mime_type = cached
        _log_tts_event(
            "tts_stream_chunk_cache_hit",
            trace,
            model=model_name,
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            chunk_chars=len(content),
            audio_bytes=len(audio_bytes),
            mime_type=mime_type,
        )
        return audio_bytes, mime_type

    last_error: Optional[Exception] = None
    for attempt in range(1, chunk_attempts + 1):
        started = time.perf_counter()
        _log_tts_event(
            "tts_stream_chunk_attempt_start",
            trace,
            model=model_name,
            chunk_index=chunk_index,
            attempt=attempt,
            chunk_chars=len(content),
        )
        try:
            response = get_gemini_client().models.generate_content(
                model=model_name,
                contents=content,
                config=types.GenerateContentConfig(
                    response_modalities=["audio"],
                    speech_config=types.SpeechConfig(
                        language_code=TTS_LANGUAGE_CODE,
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice_name
                            )
                        ),
                    ),
                    temperature=0.1,
                    http_options=types.HttpOptions(
                        timeout=timeout_ms,
                        retry_options=types.HttpRetryOptions(attempts=retry_attempts),
                        httpx_client=http_client,
                    ),
                ),
            )
            audio_bytes, mime_type = _extract_inline_audio_from_response(response)
            _tts_store_cached_chunk(cache_key, audio_bytes, mime_type)
            _log_tts_event(
                "tts_stream_chunk_ok",
                trace,
                model=model_name,
                chunk_index=chunk_index,
                attempt=attempt,
                chunk_chars=len(content),
                audio_bytes=len(audio_bytes),
                mime_type=mime_type,
                cached=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return audio_bytes, mime_type
        except Exception as exc:
            last_error = exc
            is_unavailable = _is_model_unavailable_error(exc)
            retryable = _is_tts_retryable_error(exc)
            _log_tts_event(
                "tts_stream_chunk_attempt_error",
                trace,
                model=model_name,
                chunk_index=chunk_index,
                attempt=attempt,
                retryable=retryable,
                model_unavailable=is_unavailable,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=_short(str(exc), max_chars=600),
            )
            if is_unavailable:
                raise _TTSModelUnavailableError(str(exc)) from exc
            if retryable and attempt < chunk_attempts:
                continue
            if retryable:
                raise _TTSTransientError(str(exc)) from exc
            raise RuntimeError(f"Falha no TTS Gemini ({model_name}): {exc}") from exc

    if last_error is not None:
        raise _TTSTransientError(str(last_error)) from last_error
    raise _TTSTransientError("Falha no TTS: chunk sem retorno de audio.")


def _stream_google_tts_chunks(
    text: str,
    trace_id: str | None = None,
) -> "Generator[tuple[bytes, str, int, int], None, None]":
    if not has_gemini_api_key():
        raise RuntimeError("GEMINI_API_KEY nao configurada para TTS.")

    trace = (trace_id or "").strip() or _new_trace_id()
    prepared = _normalize_for_tts(text)
    raw_chunks = _split_tts_chunks(prepared)
    chunks = [_prepare_chunk_for_gemini_tts(chunk) for chunk in raw_chunks]
    chunks = [chunk for chunk in chunks if chunk]
    total_chunks = len(chunks)
    if total_chunks == 0:
        return

    voice_name = _normalize_voice_name_for_gemini(TTS_VOICE_NAME)
    model_candidates = _tts_candidate_models()
    timeout_ms = max(10000, min(int(TTS_REQUEST_TIMEOUT_MS or 120000), 600000))
    retry_attempts = max(1, min(int(TTS_REQUEST_RETRY_ATTEMPTS or 1), 3))
    chunk_attempts = max(1, min(int(TTS_MODEL_MAX_ATTEMPTS or 2), 4))
    prefetch_concurrency = max(1, min(int(TTS_PREFETCH_CONCURRENCY or 1), 6))
    http_client = _get_tts_httpx_client(timeout_ms)

    _log_tts_event(
        "tts_stream_start",
        trace,
        chars=len(prepared),
        chunks=total_chunks,
        model_candidates=model_candidates,
        timeout_ms=timeout_ms,
        retry_attempts=retry_attempts,
        chunk_attempts=chunk_attempts,
        prefetch_concurrency=prefetch_concurrency,
        cache_enabled=bool(TTS_CACHE_ENABLED),
        voice=voice_name,
        language=TTS_LANGUAGE_CODE,
    )

    last_error: Optional[Exception] = None
    unavailable_models: set[str] = set()

    for model_name in model_candidates:
        _log_tts_event("tts_stream_model_start", trace, model=model_name, total_chunks=total_chunks)
        emitted_chunks = 0
        model_unavailable = False
        model_failed = False
        pending: dict[int, Future[tuple[bytes, str]]] = {}
        next_submit = 1
        next_emit = 1
        executor = ThreadPoolExecutor(
            max_workers=prefetch_concurrency,
            thread_name_prefix=f"tts-prefetch-{trace[:6]}",
        )

        def submit_chunk(chunk_index: int) -> None:
            content = chunks[chunk_index - 1]
            pending[chunk_index] = executor.submit(
                _synthesize_stream_chunk_with_retries,
                trace=trace,
                model_name=model_name,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                content=content,
                voice_name=voice_name,
                timeout_ms=timeout_ms,
                retry_attempts=retry_attempts,
                chunk_attempts=chunk_attempts,
                http_client=http_client,
            )

        def fill_prefetch_window() -> None:
            nonlocal next_submit
            target_window = 1 if emitted_chunks == 0 else prefetch_concurrency
            while next_submit <= total_chunks and len(pending) < target_window:
                submit_chunk(next_submit)
                next_submit += 1

        try:
            fill_prefetch_window()
            while next_emit <= total_chunks:
                if next_emit not in pending:
                    submit_chunk(next_emit)
                fill_prefetch_window()

                future = pending.pop(next_emit)
                try:
                    audio_bytes, mime_type = future.result()
                except _TTSModelUnavailableError as exc:
                    root = _stream_chunk_root_error(exc)
                    last_error = root
                    unavailable_models.add(model_name)
                    model_unavailable = True
                    model_failed = True
                    _log_tts_event(
                        "tts_stream_chunk_exhausted",
                        trace,
                        model=model_name,
                        chunk_index=next_emit,
                        chunk_attempts=chunk_attempts,
                        error=_short(str(root), max_chars=600),
                    )
                    break
                except _TTSTransientError as exc:
                    root = _stream_chunk_root_error(exc)
                    last_error = root
                    model_failed = True
                    _log_tts_event(
                        "tts_stream_chunk_exhausted",
                        trace,
                        model=model_name,
                        chunk_index=next_emit,
                        chunk_attempts=chunk_attempts,
                        error=_short(str(root), max_chars=600),
                    )
                    break
                except Exception as exc:
                    root = _stream_chunk_root_error(exc)
                    last_error = root
                    model_failed = True
                    _log_tts_event(
                        "tts_stream_chunk_exhausted",
                        trace,
                        model=model_name,
                        chunk_index=next_emit,
                        chunk_attempts=chunk_attempts,
                        error=_short(str(root), max_chars=600),
                    )
                    break

                emitted_chunks += 1
                yield audio_bytes, mime_type, next_emit, total_chunks
                next_emit += 1
                fill_prefetch_window()
        finally:
            for future in pending.values():
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        if not model_failed:
            _log_tts_event(
                "tts_stream_success",
                trace,
                model=model_name,
                emitted_chunks=emitted_chunks,
                total_chunks=total_chunks,
            )
            return

        # If this model already emitted some chunks, do not switch model to avoid duplicated/overlapping playback.
        if emitted_chunks > 0:
            break
        if model_unavailable:
            _log_tts_event("tts_stream_model_unavailable", trace, model=model_name)
            continue

    tested = ", ".join(model_candidates)
    if model_candidates and len(unavailable_models) == len(model_candidates):
        raise RuntimeError(
            f"Falha no TTS Gemini: nenhum modelo de voz suporta audio para esta chave/API. Modelos testados: {tested}."
        ) from last_error
    if last_error is not None:
        raise RuntimeError(
            f"Falha no TTS Gemini: indisponibilidade upstream apos tentativas. Ultimo erro: {last_error}"
        ) from last_error
    raise RuntimeError(
        f"Falha no TTS Gemini: nenhum modelo de voz disponivel para esta chave. Modelos testados: {tested}."
    ) from last_error


def _legacy_tts_config() -> LegacyGoogleTTSConfig:
    return LegacyGoogleTTSConfig(
        api_key=_legacy_tts_api_key(),
        voice_name=LEGACY_TTS_VOICE_NAME,
        language_code=TTS_LANGUAGE_CODE,
        speaking_rate=TTS_RATE,
        pitch_semitones=TTS_PITCH_SEMITONES,
        max_ssml_chars=LEGACY_TTS_MAX_CHARS,
        timeout_ms=LEGACY_TTS_REQUEST_TIMEOUT_MS,
        endpoint=LEGACY_TTS_ENDPOINT,
    )


def _synthesize_legacy_google_tts(text: str, trace_id: str | None = None) -> tuple[bytes, str]:
    trace = (trace_id or "").strip() or _new_trace_id()
    return _run_legacy_tts_sync(
        text=text,
        trace_id=trace,
        config=_legacy_tts_config(),
        normalize_for_tts=_normalize_for_tts,
        split_tts_chunks=_split_tts_chunks,
        build_ssml=_build_ssml,
        log_event=_log_tts_event,
    )


def _stream_legacy_tts_chunks(
    text: str,
    trace_id: str | None = None,
) -> "Generator[tuple[bytes, str, int, int], None, None]":
    trace = (trace_id or "").strip() or _new_trace_id()
    yield from _run_legacy_tts_stream(
        text=text,
        trace_id=trace,
        config=_legacy_tts_config(),
        normalize_for_tts=_normalize_for_tts,
        split_tts_chunks=_split_tts_chunks,
        build_ssml=_build_ssml,
        log_event=_log_tts_event,
    )


def _synthesize_tts(text: str, trace_id: str | None = None) -> tuple[bytes, str]:
    if TTS_PROVIDER == "legacy_google":
        return _synthesize_legacy_google_tts(text, trace_id=trace_id)
    return _synthesize_google_tts(text, trace_id=trace_id)


def _stream_tts_chunks(
    text: str,
    trace_id: str | None = None,
) -> "Generator[tuple[bytes, str, int, int], None, None]":
    if TTS_PROVIDER == "legacy_google":
        yield from _stream_legacy_tts_chunks(text, trace_id=trace_id)
        return
    yield from _stream_google_tts_chunks(text, trace_id=trace_id)


def _serialize_doc(idx: int, row: dict[str, Any]) -> dict[str, Any]:
    tipo_raw = (row.get("tipo") or "").strip()
    tribunal = (row.get("tribunal") or "-").strip()
    processo = (row.get("processo") or row.get("doc_id") or "-").strip()
    relator = (row.get("relator") or "-").strip()
    orgao = orgao_label((row.get("orgao_julgador") or "").strip())
    authority_level = (row.get("_authority_level") or "-").strip().upper()
    authority_label = (row.get("_authority_label") or "-").strip()
    final_score = float(row.get("_final_score") or 0.0)
    normative_statement = _extract_normative_statement_from_row(row)
    source_id = str(row.get("source_id") or "").strip() or "ratio"
    source_label = str(row.get("source_label") or "").strip()
    if not source_label:
        source_label = "Base Ratio (STF/STJ)" if source_id == "ratio" else source_id
    source_kind = str(row.get("source_kind") or "").strip() or ("ratio" if source_id == "ratio" else "user")

    return {
        "index": idx,
        "doc_id": row.get("doc_id"),
        "tipo": tipo_raw,
        "tipo_label": type_label(tipo_raw),
        "processo": processo,
        "tribunal": tribunal,
        "data_julgamento": (row.get("data_julgamento") or "").strip(),
        "relator": relator,
        "orgao_julgador": orgao,
        "authority_level": authority_level,
        "authority_label": authority_label,
        "final_score": round(final_score, 6),
        "semantic_backend": (row.get("_semantic_backend") or "").strip(),
        "inteiro_teor_url": (row.get("inteiro_teor_url") or row.get("url") or "").strip(),
        "texto_busca": _short(row.get("texto_busca") or "", max_chars=1500),
        "texto_integral_excerpt": _short(row.get("texto_integral") or "", max_chars=1800),
        "normative_statement": _short(normative_statement, max_chars=260),
        "source_id": source_id,
        "source_label": source_label,
        "source_kind": source_kind,
    }


def _upsert_env_gemini_key(api_key: str) -> Path:
    env_path = PROJECT_ROOT / ".env"
    key_line = f"GEMINI_API_KEY={api_key}"
    current = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    if re.search(r"(?im)^\s*GEMINI_API_KEY\s*=", current):
        updated = re.sub(r"(?im)^\s*GEMINI_API_KEY\s*=.*$", key_line, current, count=1)
    else:
        updated = current
        if updated and not updated.endswith("\n"):
            updated += "\n"
        updated += key_line + "\n"
    env_path.write_text(updated, encoding="utf-8")
    return env_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_json_load(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        if not path.exists():
            return dict(fallback)
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return dict(fallback)


def _load_user_sources_manifest() -> dict[str, Any]:
    fallback = {"version": 1, "sources": []}
    payload = _safe_json_load(USER_ACERVO_MANIFEST, fallback)
    sources = payload.get("sources")
    if not isinstance(sources, list):
        sources = []
    normalized: list[dict[str, Any]] = []
    for raw in sources:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("id") or "").strip()
        if not source_id.startswith("user:"):
            continue
        normalized.append(
            {
                "id": source_id,
                "name": str(raw.get("name") or source_id.replace("user:", "")).strip() or source_id,
                "created_at": str(raw.get("created_at") or "").strip() or _utc_now_iso(),
                "deleted_at": str(raw.get("deleted_at") or "").strip() or None,
                "doc_count": int(raw.get("doc_count") or 0),
                "chunk_count": int(raw.get("chunk_count") or 0),
                "last_indexed_at": str(raw.get("last_indexed_at") or "").strip() or "",
            }
        )
    return {"version": 1, "sources": normalized}


def _save_user_sources_manifest(payload: dict[str, Any]) -> None:
    USER_ACERVO_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    USER_ACERVO_MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _slugify_user_source_name(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return value or "banco"


def _ensure_user_source(source_name: str) -> dict[str, Any]:
    manifest = _load_user_sources_manifest()
    sources: list[dict[str, Any]] = list(manifest.get("sources", []))

    requested_name = (source_name or "").strip() or "Banco 1"
    for src in sources:
        if str(src.get("name") or "").strip().lower() == requested_name.lower():
            if src.get("deleted_at"):
                src["deleted_at"] = None
            _save_user_sources_manifest({"version": 1, "sources": sources})
            return src

    base_slug = _slugify_user_source_name(requested_name)
    existing_ids = {str(src.get("id") or "") for src in sources}
    candidate = f"user:{base_slug}"
    idx = 2
    while candidate in existing_ids:
        candidate = f"user:{base_slug}-{idx}"
        idx += 1

    created = {
        "id": candidate,
        "name": requested_name,
        "created_at": _utc_now_iso(),
        "deleted_at": None,
        "doc_count": 0,
        "chunk_count": 0,
        "last_indexed_at": "",
    }
    sources.append(created)
    _save_user_sources_manifest({"version": 1, "sources": sources})
    return created


def _set_user_source_deleted(source_id: str, *, deleted: bool) -> dict[str, Any]:
    normalized_id = str(source_id or "").strip()
    if not normalized_id.startswith("user:"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_source_id",
                "message": "source_id invalido para Meu Acervo.",
                "hint": "Use um id no formato user:<nome>.",
            },
        )

    manifest = _load_user_sources_manifest()
    sources: list[dict[str, Any]] = list(manifest.get("sources", []))
    for src in sources:
        if str(src.get("id") or "").strip() != normalized_id:
            continue
        src["deleted_at"] = _utc_now_iso() if deleted else None
        _save_user_sources_manifest({"version": 1, "sources": sources})
        return src

    raise HTTPException(
        status_code=404,
        detail={
            "code": "source_not_found",
            "message": "Fonte do Meu Acervo nao encontrada.",
            "hint": "Atualize a lista de fontes e tente novamente.",
        },
    )


def _list_available_sources_payload() -> dict[str, Any]:
    manifest = _load_user_sources_manifest()
    user_sources: list[dict[str, Any]] = list(manifest.get("sources", []))
    sources: list[dict[str, Any]] = [
        {
            "id": "ratio",
            "label": "Base Ratio (STF/STJ)",
            "kind": "ratio",
            "deleted": False,
            "doc_count": None,
            "chunk_count": None,
            "created_at": None,
        }
    ]

    defaults = ["ratio"]
    for src in user_sources:
        deleted = bool(src.get("deleted_at"))
        source_id = str(src.get("id") or "").strip()
        if not source_id:
            continue
        sources.append(
            {
                "id": source_id,
                "label": str(src.get("name") or source_id).strip() or source_id,
                "kind": "user",
                "deleted": deleted,
                "doc_count": int(src.get("doc_count") or 0),
                "chunk_count": int(src.get("chunk_count") or 0),
                "created_at": str(src.get("created_at") or "").strip(),
            }
        )
        if not deleted:
            defaults.append(source_id)

    return {
        "sources": sources,
        "default_selected": defaults,
        "manual_confirm_required": USER_ACERVO_REQUIRE_CONFIRM,
    }


def _require_user_acervo_runtime() -> None:
    if lancedb is None or pa is None:
        raise RuntimeError("Dependencias de indexacao nao disponiveis (lancedb/pyarrow).")
    if fitz is None:
        raise RuntimeError("PyMuPDF nao disponivel neste ambiente de execucao.")


class _UserAcervoValidationError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = str(code or "invalid_request")
        self.message = str(message or "Requisicao invalida.")
        self.hint = str(hint or "").strip()


def _raise_user_acervo_validation_error(code: str, message: str, hint: str = "") -> None:
    detail: dict[str, str] = {"code": str(code), "message": str(message)}
    hint_value = str(hint or "").strip()
    if hint_value:
        detail["hint"] = hint_value
    raise HTTPException(status_code=400, detail=detail)


def _store_upload_file(upload: UploadFile, filename: str) -> tuple[Path, str, int]:
    USER_ACERVO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    safe_suffix = Path(filename or "documento.pdf").suffix.lower() or ".pdf"
    temp_path = USER_ACERVO_UPLOAD_DIR / f"{uuid.uuid4().hex}{safe_suffix}"
    digest = hashlib.sha256()
    total_bytes = 0

    try:
        with temp_path.open("wb") as handle:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > USER_ACERVO_MAX_FILE_SIZE_BYTES:
                    raise _UserAcervoValidationError(
                        code="file_too_large",
                        message=(
                            f"Arquivo '{filename}' excede o limite de "
                            f"{USER_ACERVO_MAX_FILE_SIZE_MB} MB por arquivo."
                        ),
                        hint="Divida em arquivos menores ou aumente USER_ACERVO_MAX_FILE_SIZE_MB no backend.",
                    )
                digest.update(chunk)
                handle.write(chunk)
        if total_bytes <= 0:
            raise _UserAcervoValidationError(
                code="empty_file",
                message=f"Arquivo '{filename}' esta vazio.",
                hint="Selecione arquivos PDF validos com conteudo.",
            )
        return temp_path, digest.hexdigest(), int(total_bytes)
    except Exception:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
        raise


def _user_lance_schema() -> Any:
    _require_user_acervo_runtime()
    return pa.schema(
        [
            pa.field("vector", pa.list_(pa.float32(), USER_ACERVO_EMBED_DIM)),
            pa.field("doc_id", pa.utf8()),
            pa.field("tribunal", pa.utf8()),
            pa.field("tipo", pa.utf8()),
            pa.field("processo", pa.utf8()),
            pa.field("relator", pa.utf8()),
            pa.field("ramo_direito", pa.utf8()),
            pa.field("data_julgamento", pa.utf8()),
            pa.field("orgao_julgador", pa.utf8()),
            pa.field("texto_busca", pa.utf8()),
            pa.field("texto_integral", pa.large_utf8()),
            pa.field("url", pa.utf8()),
            pa.field("metadata_extra", pa.utf8()),
            pa.field("source_id", pa.utf8()),
            pa.field("source_label", pa.utf8()),
            pa.field("source_kind", pa.utf8()),
            pa.field("doc_sha256", pa.utf8()),
            pa.field("file_name", pa.utf8()),
            pa.field("chunk_index", pa.int32()),
            pa.field("chunk_total", pa.int32()),
        ]
    )


def _open_user_table(create_if_missing: bool = False):
    _require_user_acervo_runtime()
    USER_ACERVO_LANCE_DIR.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(USER_ACERVO_LANCE_DIR))
    try:
        return db.open_table(USER_ACERVO_TABLE)
    except Exception:
        if not create_if_missing:
            return None
    return db.create_table(USER_ACERVO_TABLE, data=[], schema=_user_lance_schema(), mode="overwrite")


def _existing_hashes_for_source(source_id: str) -> set[str]:
    tbl = _open_user_table(create_if_missing=False)
    if tbl is None:
        return set()
    try:
        rows = tbl.to_list()
    except Exception:
        return set()
    hashes: set[str] = set()
    for row in rows:
        if str(row.get("source_id") or "").strip() != source_id:
            continue
        digest = str(row.get("doc_sha256") or "").strip()
        if digest:
            hashes.add(digest)
    return hashes


def _acervo_log_event(event: str, **fields: Any) -> None:
    payload: dict[str, Any] = {"event": event}
    for key, value in fields.items():
        if value is None:
            continue
        payload[str(key)] = value
    try:
        _ACERVO_LOGGER.info(json.dumps(payload, ensure_ascii=False))
    except Exception:
        _ACERVO_LOGGER.info("%s", event)


def _run_with_hard_timeout(
    *,
    label: str,
    timeout_ms: int,
    operation: Callable[[], Any],
) -> Any:
    timeout_s = max(0.1, min(float(timeout_ms or 0) / 1000.0, 600.0))
    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            value = operation()
            result_queue.put((True, value))
        except Exception as exc:  # pragma: no cover - passthrough path
            result_queue.put((False, exc))

    thread = threading.Thread(target=_runner, daemon=True, name=f"acervo-timeout-{label}")
    thread.start()
    try:
        ok, payload = result_queue.get(timeout=timeout_s)
    except queue.Empty as exc:
        raise TimeoutError(f"{label} excedeu timeout hard de {int(timeout_ms)}ms") from exc
    if ok:
        return payload
    if isinstance(payload, Exception):
        raise payload
    return payload


def _is_user_acervo_clean_circuit_open() -> bool:
    now = time.time()
    with _USER_ACERVO_CLEAN_CIRCUIT_LOCK:
        return now < _USER_ACERVO_CLEAN_CIRCUIT_UNTIL


def _open_user_acervo_clean_circuit(cooldown_seconds: int = 300) -> None:
    global _USER_ACERVO_CLEAN_CIRCUIT_UNTIL
    now = time.time()
    with _USER_ACERVO_CLEAN_CIRCUIT_LOCK:
        _USER_ACERVO_CLEAN_CIRCUIT_UNTIL = max(_USER_ACERVO_CLEAN_CIRCUIT_UNTIL, now + max(30, int(cooldown_seconds)))


def _clean_user_chunk_heuristic(text: str) -> str:
    chunk = (text or "").strip()
    if not chunk:
        return ""
    cleaned = chunk
    cleaned = re.sub(r"(?im)^\s*p[aá]gina\s+\d+\s*$", " ", cleaned)
    cleaned = re.sub(r"(?im)^\s*\d+\s*$", " ", cleaned)
    cleaned = re.sub(r"(?im)^\s*(tribunal|poder judici[aá]rio|justi[cç]a)[^\n]{0,120}$", " ", cleaned)
    cleaned = re.sub(r"(?im)^\s*(assinado digitalmente|documento assinado)[^\n]*$", " ", cleaned)
    cleaned = re.sub(r"[ \\t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    normalized = cleaned.strip()
    return normalized or chunk


def _new_user_acervo_job(
    *,
    source_id: str,
    source_label: str,
    accepted_files: int,
    skipped_files: int,
) -> str:
    now_ts = time.time()
    now_iso = _utc_now_iso()
    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "status": "queued",
        "stage": "upload",
        "message": "Lote recebido. Aguardando execucao.",
        "source_id": source_id,
        "source_label": source_label,
        "submitted_at": now_iso,
        "submitted_ts": now_ts,
        "started_at": "",
        "started_ts": None,
        "updated_at": now_iso,
        "updated_ts": now_ts,
        "finished_at": "",
        "finished_ts": None,
        "progress": {
            "total_files": int(max(accepted_files, 0)),
            "accepted_files": int(max(accepted_files, 0)),
            "processed_files": 0,
            "indexed_docs": 0,
            "indexed_chunks": 0,
            "inserted_rows": 0,
            "duplicate_files": 0,
            "skipped_files": int(max(skipped_files, 0)),
            "pages_text": 0,
            "pages_ocr": 0,
            "running_files": 0,
            "current_file": "",
            "last_error": "",
        },
        "result": {},
        "error": None,
    }
    with _USER_ACERVO_JOBS_LOCK:
        cutoff = now_ts - USER_ACERVO_INDEX_JOB_TTL_SECONDS
        stale_ids = [
            key
            for key, value in _USER_ACERVO_JOBS.items()
            if str(value.get("status") or "") in {"done", "error"}
            and float(value.get("finished_ts") or 0.0) > 0.0
            and float(value.get("finished_ts") or 0.0) < cutoff
        ]
        for stale_id in stale_ids:
            _USER_ACERVO_JOBS.pop(stale_id, None)
        _USER_ACERVO_JOBS[job_id] = job
    _acervo_log_event(
        "acervo_job_created",
        job_id=job_id,
        source_id=source_id,
        accepted_files=accepted_files,
        skipped_files=skipped_files,
    )
    return job_id


def _update_user_acervo_job(
    job_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    message: str | None = None,
    error: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    progress_set: dict[str, Any] | None = None,
    progress_delta: dict[str, int] | None = None,
) -> None:
    now_ts = time.time()
    now_iso = _utc_now_iso()
    with _USER_ACERVO_JOBS_LOCK:
        job = _USER_ACERVO_JOBS.get(job_id)
        if not isinstance(job, dict):
            return
        if status is not None:
            job["status"] = str(status or "").strip() or str(job.get("status") or "queued")
            if status == "running" and not job.get("started_ts"):
                job["started_ts"] = now_ts
                job["started_at"] = now_iso
            if status in {"done", "error"}:
                job["finished_ts"] = now_ts
                job["finished_at"] = now_iso
        if stage is not None:
            job["stage"] = str(stage or "").strip() or str(job.get("stage") or "upload")
        if message is not None:
            job["message"] = str(message or "").strip()
        if isinstance(error, dict):
            job["error"] = dict(error)
        if isinstance(result, dict):
            job["result"] = dict(result)
        progress = job.get("progress")
        if not isinstance(progress, dict):
            progress = {}
            job["progress"] = progress
        if isinstance(progress_set, dict):
            for key, value in progress_set.items():
                progress[str(key)] = value
        if isinstance(progress_delta, dict):
            for key, value in progress_delta.items():
                raw_current = progress.get(str(key), 0)
                try:
                    current = int(raw_current)
                except Exception:
                    current = 0
                try:
                    delta = int(value)
                except Exception:
                    delta = 0
                progress[str(key)] = current + delta
        job["updated_ts"] = now_ts
        job["updated_at"] = now_iso


def _estimate_user_acervo_eta_seconds(job: dict[str, Any]) -> int | None:
    status = str(job.get("status") or "")
    if status != "running":
        return None
    progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    total_files = int(progress.get("total_files") or 0)
    processed_files = int(progress.get("processed_files") or 0)
    if total_files <= 0 or processed_files <= 0 or processed_files >= total_files:
        return None
    started_ts = float(job.get("started_ts") or 0.0)
    if started_ts <= 0:
        return None
    elapsed = max(0.0, time.time() - started_ts)
    if elapsed <= 0.0:
        return None
    avg_per_file = elapsed / max(processed_files, 1)
    remaining = max(0, total_files - processed_files)
    if remaining <= 0:
        return None
    eta = int(max(1.0, round(avg_per_file * remaining)))
    return eta


def _get_user_acervo_job_payload(job_id: str) -> dict[str, Any] | None:
    normalized = str(job_id or "").strip()
    if not normalized:
        return None
    with _USER_ACERVO_JOBS_LOCK:
        job = _USER_ACERVO_JOBS.get(normalized)
        if not isinstance(job, dict):
            return None
        payload = copy.deepcopy(job)
    payload["eta_seconds"] = _estimate_user_acervo_eta_seconds(payload)
    started_ts = float(payload.get("started_ts") or 0.0)
    if started_ts > 0:
        payload["elapsed_seconds"] = round(max(0.0, time.time() - started_ts), 2)
    else:
        payload["elapsed_seconds"] = 0.0
    payload.pop("submitted_ts", None)
    payload.pop("started_ts", None)
    payload.pop("updated_ts", None)
    payload.pop("finished_ts", None)
    return payload


def _build_user_acervo_record_batch(
    *,
    cleaned_batch: list[str],
    vectors: list[list[float]],
    batch_start: int,
    total_chunks: int,
    source_id: str,
    source_label: str,
    filename: str,
    digest: str,
    ocr_missing_only: bool,
) -> list[dict[str, Any]]:
    records_batch: list[dict[str, Any]] = []
    for local_idx, (chunk_text, vector) in enumerate(zip(cleaned_batch, vectors), start=1):
        chunk_index = batch_start + local_idx
        metadata_extra = json.dumps(
            {
                "source_kind": "user",
                "source_id": source_id,
                "source_label": source_label,
                "file_name": filename,
                "doc_sha256": digest,
                "chunk_index": chunk_index,
                "chunk_total": total_chunks,
                "ocr_missing_only": bool(ocr_missing_only),
            },
            ensure_ascii=False,
        )
        records_batch.append(
            {
                "vector": vector,
                "doc_id": f"{source_id}:{digest[:16]}:{chunk_index}",
                "tribunal": "MEU_ACERVO",
                "tipo": "acervo_usuario",
                "processo": filename,
                "relator": "-",
                "ramo_direito": "",
                "data_julgamento": "",
                "orgao_julgador": "Meu Acervo",
                "texto_busca": chunk_text[:8000],
                "texto_integral": chunk_text,
                "url": "",
                "metadata_extra": metadata_extra,
                "source_id": source_id,
                "source_label": source_label,
                "source_kind": "user",
                "doc_sha256": digest,
                "file_name": filename,
                "chunk_index": chunk_index,
                "chunk_total": total_chunks,
            }
        )
    return records_batch


def _index_single_user_acervo_file(
    *,
    job_id: str,
    source_id: str,
    source_label: str,
    ocr_missing_only: bool,
    existing_hashes: set[str],
    inflight_hashes: set[str],
    hash_lock: threading.Lock,
    file_payload: dict[str, Any],
) -> dict[str, Any]:
    filename = str(file_payload.get("filename") or "documento.pdf").strip() or "documento.pdf"
    digest = str(file_payload.get("digest") or "").strip()
    temp_path = Path(str(file_payload.get("temp_path") or "")).expanduser()
    started = time.perf_counter()

    summary: dict[str, Any] = {
        "indexed_docs": 0,
        "indexed_chunks": 0,
        "inserted_rows": 0,
        "duplicate_files": 0,
        "skipped_files": 0,
        "pages_text": 0,
        "pages_ocr": 0,
        "error": "",
    }

    reserved_hash = False
    with hash_lock:
        if digest and (digest in existing_hashes or digest in inflight_hashes):
            summary["duplicate_files"] = 1
            _acervo_log_event(
                "acervo_file_duplicate",
                job_id=job_id,
                file_name=filename,
                doc_sha256=digest[:16],
            )
            return summary
        if digest:
            inflight_hashes.add(digest)
            reserved_hash = True

    try:
        _acervo_log_event(
            "acervo_file_start",
            job_id=job_id,
            file_name=filename,
            doc_sha256=digest[:16],
        )
        _update_user_acervo_job(
            job_id,
            stage="extract",
            message=f"Extraindo texto: {filename}",
            progress_set={"current_file": filename},
        )
        extracted_text, page_stats = _extract_pdf_text_with_optional_ocr(temp_path, bool(ocr_missing_only))
        summary["pages_text"] = int(page_stats.get("pages_with_text") or 0)
        summary["pages_ocr"] = int(page_stats.get("pages_with_ocr") or 0)

        if not extracted_text:
            summary["skipped_files"] = 1
            return summary

        chunks = _split_user_text_chunks(extracted_text, max_chars=USER_ACERVO_CHUNK_CHARS)
        if not chunks:
            summary["skipped_files"] = 1
            return summary

        total_chunks = len(chunks)
        batch_size = 32
        file_inserted_rows = 0
        for batch_start in range(0, total_chunks, batch_size):
            raw_batch = chunks[batch_start : batch_start + batch_size]
            _update_user_acervo_job(
                job_id,
                stage="clean",
                message=f"Limpando ruido juridico: {filename}",
                progress_set={"current_file": filename},
            )
            cleaned_batch = [_clean_user_chunk_with_flash(chunk) for chunk in raw_batch]
            _update_user_acervo_job(
                job_id,
                stage="embed",
                message=f"Gerando embeddings e gravando: {filename}",
                progress_set={"current_file": filename},
            )
            vectors = _embed_user_chunks(cleaned_batch)
            records_batch = _build_user_acervo_record_batch(
                cleaned_batch=cleaned_batch,
                vectors=vectors,
                batch_start=batch_start,
                total_chunks=total_chunks,
                source_id=source_id,
                source_label=source_label,
                filename=filename,
                digest=digest,
                ocr_missing_only=bool(ocr_missing_only),
            )
            if records_batch:
                with _USER_ACERVO_WRITE_LOCK:
                    file_inserted_rows += _upsert_user_records(records_batch)

        summary["indexed_docs"] = 1
        summary["indexed_chunks"] = int(total_chunks)
        summary["inserted_rows"] = int(file_inserted_rows)
        _acervo_log_event(
            "acervo_file_done",
            job_id=job_id,
            file_name=filename,
            indexed_chunks=summary["indexed_chunks"],
            inserted_rows=summary["inserted_rows"],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        if digest:
            with hash_lock:
                existing_hashes.add(digest)
    except Exception as exc:
        summary["skipped_files"] = 1
        summary["error"] = _short(str(exc), max_chars=400)
        _acervo_log_event(
            "acervo_file_error",
            job_id=job_id,
            file_name=filename,
            error=summary["error"],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    finally:
        if reserved_hash and digest:
            with hash_lock:
                inflight_hashes.discard(digest)
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
    return summary


def _run_user_acervo_index_job(
    *,
    job_id: str,
    source_id: str,
    source_label: str,
    ocr_missing_only: bool,
    stored_files: list[dict[str, Any]],
) -> None:
    total_files = len(stored_files)
    workers = max(1, min(USER_ACERVO_INDEX_MAX_WORKERS, total_files if total_files > 0 else 1))
    _update_user_acervo_job(
        job_id,
        status="running",
        stage="upload",
        message=f"Upload validado. Iniciando com {workers} worker(s).",
        progress_set={"running_files": workers if total_files > 0 else 0},
    )
    _acervo_log_event(
        "acervo_job_started",
        job_id=job_id,
        source_id=source_id,
        files=total_files,
        workers=workers,
    )

    try:
        existing_hashes = _existing_hashes_for_source(source_id)
        inflight_hashes: set[str] = set()
        hash_lock = threading.Lock()
        processed_files = 0
        errors: list[str] = []

        if total_files <= 0:
            _update_user_acervo_job(
                job_id,
                status="done",
                stage="done",
                message="Nenhum PDF valido para processar.",
                progress_set={"running_files": 0},
                result={"indexed_docs": 0, "indexed_chunks": 0, "inserted_rows": 0},
            )
            return

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"acervo-{job_id[:6]}") as executor:
            futures: dict[Future, dict[str, Any]] = {}
            for file_payload in stored_files:
                future = executor.submit(
                    _index_single_user_acervo_file,
                    job_id=job_id,
                    source_id=source_id,
                    source_label=source_label,
                    ocr_missing_only=bool(ocr_missing_only),
                    existing_hashes=existing_hashes,
                    inflight_hashes=inflight_hashes,
                    hash_lock=hash_lock,
                    file_payload=file_payload,
                )
                futures[future] = file_payload

            for future in as_completed(futures):
                try:
                    summary = future.result()
                except Exception as exc:
                    summary = {
                        "indexed_docs": 0,
                        "indexed_chunks": 0,
                        "inserted_rows": 0,
                        "duplicate_files": 0,
                        "skipped_files": 1,
                        "pages_text": 0,
                        "pages_ocr": 0,
                        "error": _short(str(exc), max_chars=400),
                    }
                processed_files += 1
                error_text = str(summary.get("error") or "").strip()
                if error_text:
                    errors.append(error_text)
                _update_user_acervo_job(
                    job_id,
                    progress_delta={
                        "processed_files": 1,
                        "indexed_docs": int(summary.get("indexed_docs") or 0),
                        "indexed_chunks": int(summary.get("indexed_chunks") or 0),
                        "inserted_rows": int(summary.get("inserted_rows") or 0),
                        "duplicate_files": int(summary.get("duplicate_files") or 0),
                        "skipped_files": int(summary.get("skipped_files") or 0),
                        "pages_text": int(summary.get("pages_text") or 0),
                        "pages_ocr": int(summary.get("pages_ocr") or 0),
                    },
                    progress_set={
                        "running_files": max(0, total_files - processed_files),
                        "last_error": error_text if error_text else "",
                        "current_file": "",
                    },
                    message=f"Processando lote: {processed_files}/{total_files} arquivo(s).",
                )

        payload = _get_user_acervo_job_payload(job_id) or {}
        progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
        indexed_docs = int(progress.get("indexed_docs") or 0)
        indexed_chunks = int(progress.get("indexed_chunks") or 0)
        inserted_rows = int(progress.get("inserted_rows") or 0)
        duplicate_files = int(progress.get("duplicate_files") or 0)
        skipped_files = int(progress.get("skipped_files") or 0)
        pages_text = int(progress.get("pages_text") or 0)
        pages_ocr = int(progress.get("pages_ocr") or 0)

        manifest = _load_user_sources_manifest()
        sources: list[dict[str, Any]] = list(manifest.get("sources", []))
        for src in sources:
            if str(src.get("id") or "").strip() != source_id:
                continue
            src["doc_count"] = int(src.get("doc_count") or 0) + indexed_docs
            src["chunk_count"] = int(src.get("chunk_count") or 0) + indexed_chunks
            src["last_indexed_at"] = _utc_now_iso()
            break
        _save_user_sources_manifest({"version": 1, "sources": sources})

        result_payload = {
            "indexed_docs": indexed_docs,
            "indexed_chunks": indexed_chunks,
            "inserted_rows": inserted_rows,
            "duplicate_files": duplicate_files,
            "skipped_files": skipped_files,
            "pages_text": pages_text,
            "pages_ocr": pages_ocr,
        }
        if errors and indexed_docs <= 0:
            _update_user_acervo_job(
                job_id,
                status="error",
                stage="embed",
                message="Falha na indexacao do lote.",
                error={
                    "code": "index_job_failed",
                    "message": errors[0],
                    "hint": "Consulte logs/runtime/acervo_backend.log para detalhes.",
                },
                result=result_payload,
                progress_set={"running_files": 0, "current_file": ""},
            )
        else:
            done_message = (
                f"Indexacao concluida: {indexed_docs} doc(s), {duplicate_files} duplicado(s), "
                f"{skipped_files} ignorado(s)."
            )
            if errors:
                done_message += f" ({len(errors)} arquivo(s) com erro.)"
            _update_user_acervo_job(
                job_id,
                status="done",
                stage="done",
                message=done_message,
                result=result_payload,
                progress_set={"running_files": 0, "current_file": ""},
            )
        _acervo_log_event("acervo_job_finished", job_id=job_id, indexed_docs=indexed_docs, errors=len(errors))
    except Exception as exc:
        _update_user_acervo_job(
            job_id,
            status="error",
            stage="embed",
            message="Falha inesperada na indexacao do Meu Acervo.",
            error={
                "code": "internal_error",
                "message": _short(str(exc), max_chars=400),
                "hint": "Consulte logs/runtime/acervo_backend.log para diagnostico.",
            },
            progress_set={"running_files": 0, "current_file": ""},
        )
        _acervo_log_event("acervo_job_crashed", job_id=job_id, error=_short(str(exc), max_chars=600))
    finally:
        for item in stored_files:
            try:
                temp_path = Path(str(item.get("temp_path") or "")).expanduser()
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass


def _start_user_acervo_index_job(
    *,
    source_id: str,
    source_label: str,
    ocr_missing_only: bool,
    stored_files: list[dict[str, Any]],
    pre_skipped_files: int = 0,
) -> str:
    job_id = _new_user_acervo_job(
        source_id=source_id,
        source_label=source_label,
        accepted_files=len(stored_files),
        skipped_files=int(max(pre_skipped_files, 0)),
    )
    thread = threading.Thread(
        target=_run_user_acervo_index_job,
        daemon=True,
        name=f"acervo-index-{job_id}",
        kwargs={
            "job_id": job_id,
            "source_id": source_id,
            "source_label": source_label,
            "ocr_missing_only": bool(ocr_missing_only),
            "stored_files": stored_files,
        },
    )
    thread.start()
    return job_id


def _split_user_text_chunks(text: str, max_chars: int = USER_ACERVO_CHUNK_CHARS) -> list[str]:
    content = (text or "").strip()
    if not content:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", content) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            part = paragraph[start : start + max_chars].strip()
            if part:
                chunks.append(part)
            start += max_chars
    if current:
        chunks.append(current)
    return chunks


def _clean_user_chunk_with_flash(text: str) -> str:
    chunk = (text or "").strip()
    if not chunk:
        return ""
    heuristic = _clean_user_chunk_heuristic(chunk)
    if _is_user_acervo_clean_circuit_open():
        return heuristic
    prompt = (
        "Limpe ruido de OCR/paginacao de um texto juridico em portugues.\n"
        "Remova: cabecalhos repetidos, numeracao de pagina isolada, rodapes administrativos, "
        "linhas de assinatura e metadados irrelevantes.\n"
        "Preserve integralmente o conteudo juridico util, sem resumir.\n"
        "Retorne apenas o texto limpo."
    )
    timeout_ms = max(10000, min(int(USER_ACERVO_CLEAN_TIMEOUT_MS or 45000), 300000))
    retry_attempts = max(1, min(int(USER_ACERVO_RETRY_ATTEMPTS or 1), 4))
    http_client = _get_acervo_httpx_client(timeout_ms)
    try:
        response = _run_with_hard_timeout(
            label="acervo_clean_chunk",
            timeout_ms=timeout_ms,
            operation=lambda: get_gemini_client().models.generate_content(
                model=USER_ACERVO_CLEAN_MODEL,
                contents=f"{prompt}\n\n[TEXTO]\n{chunk}",
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=4096,
                    http_options=types.HttpOptions(
                        timeout=timeout_ms,
                        retry_options=types.HttpRetryOptions(attempts=retry_attempts),
                        httpx_client=http_client,
                    ),
                ),
            ),
        )
        cleaned = str(response.text or "").strip()
        return cleaned or heuristic
    except TimeoutError:
        _open_user_acervo_clean_circuit(cooldown_seconds=300)
        _acervo_log_event(
            "acervo_clean_timeout",
            timeout_ms=timeout_ms,
            model=USER_ACERVO_CLEAN_MODEL,
        )
        return heuristic
    except Exception as exc:
        _acervo_log_event(
            "acervo_clean_fallback",
            model=USER_ACERVO_CLEAN_MODEL,
            error=_short(str(exc), max_chars=400),
        )
        return heuristic


def _ocr_png_with_gemini(png_bytes: bytes) -> str:
    prompt = (
        "Extraia o texto desta pagina de PDF juridico em portugues.\n"
        "Retorne apenas texto corrido, sem markdown, sem comentarios."
    )
    timeout_ms = max(10000, min(int(USER_ACERVO_OCR_TIMEOUT_MS or 60000), 300000))
    retry_attempts = max(1, min(int(USER_ACERVO_RETRY_ATTEMPTS or 1), 4))
    http_client = _get_acervo_httpx_client(timeout_ms)
    response = _run_with_hard_timeout(
        label="acervo_ocr_page",
        timeout_ms=timeout_ms,
        operation=lambda: get_gemini_client().models.generate_content(
            model=USER_ACERVO_OCR_MODEL,
            contents=[
                types.Part.from_text(prompt),
                types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=4096,
                http_options=types.HttpOptions(
                    timeout=timeout_ms,
                    retry_options=types.HttpRetryOptions(attempts=retry_attempts),
                    httpx_client=http_client,
                ),
            ),
        ),
    )
    return str(response.text or "").strip()


def _extract_pdf_text_with_optional_ocr(pdf_path: Path, ocr_missing_only: bool) -> tuple[str, dict[str, int]]:
    _require_user_acervo_runtime()
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise RuntimeError(f"PDF invalido ou corrompido: {exc}") from exc

    total_pages = 0
    text_pages = 0
    ocr_pages = 0
    page_chunks: list[str] = []
    try:
        total_pages = len(doc)
        for idx in range(total_pages):
            page = doc.load_page(idx)
            raw_text = (page.get_text("text") or "").strip()

            use_ocr = False
            if ocr_missing_only:
                use_ocr = not raw_text
            else:
                use_ocr = True

            if use_ocr:
                try:
                    pix = page.get_pixmap(dpi=USER_ACERVO_OCR_DPI, alpha=False)
                    png = pix.tobytes("png")
                    ocr_text = _ocr_png_with_gemini(png)
                    if ocr_text:
                        raw_text = ocr_text
                        ocr_pages += 1
                except Exception:
                    pass

            if raw_text:
                text_pages += 1
                page_chunks.append(f"[PAGINA {idx + 1}]\n{raw_text}")
    finally:
        doc.close()

    return "\n\n".join(page_chunks).strip(), {
        "pages_total": int(total_pages),
        "pages_with_text": int(text_pages),
        "pages_with_ocr": int(ocr_pages),
    }


def _embed_user_chunks(chunks: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    if not chunks:
        return vectors
    batch_size = max(1, min(int(USER_ACERVO_EMBED_BATCH_SIZE or 8), 32))
    timeout_ms = max(10000, min(int(USER_ACERVO_EMBED_TIMEOUT_MS or 45000), 300000))
    retry_attempts = max(1, min(int(USER_ACERVO_RETRY_ATTEMPTS or 1), 4))
    http_client = _get_acervo_httpx_client(timeout_ms)
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        result = _run_with_hard_timeout(
            label="acervo_embed_batch",
            timeout_ms=timeout_ms,
            operation=lambda: get_gemini_client().models.embed_content(
                model=USER_ACERVO_EMBED_MODEL,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=USER_ACERVO_EMBED_DIM,
                    http_options=types.HttpOptions(
                        timeout=timeout_ms,
                        retry_options=types.HttpRetryOptions(attempts=retry_attempts),
                        httpx_client=http_client,
                    ),
                ),
            ),
        )
        vectors.extend([list(e.values) for e in (result.embeddings or [])])
    if len(vectors) != len(chunks):
        raise RuntimeError("Falha ao gerar embeddings de todos os chunks do Meu Acervo.")
    return vectors


def _upsert_user_records(records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    tbl = _open_user_table(create_if_missing=True)
    if tbl is None:
        raise RuntimeError("Tabela do Meu Acervo indisponivel para escrita.")

    try:
        before = int(tbl.count_rows())
    except Exception:
        before = 0

    try:
        (
            tbl.merge_insert("doc_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(records)
        )
    except Exception:
        # Fallback para ambientes sem suporte a merge_insert.
        tbl.add(records)

    try:
        tbl.create_fts_index("texto_busca", use_tantivy=False, replace=True)
    except Exception:
        pass

    try:
        after = int(tbl.count_rows())
        return max(0, after - before)
    except Exception:
        return len(records)


def _classify_runtime_error(exc: Exception) -> tuple[int, dict[str, str]]:
    message = str(exc).strip() or "Falha interna no backend."
    norm = message.lower()

    if (
        ("gemini_api_key" in norm or "google_tts_api_key" in norm)
        and ("ausente" in norm or "not found" in norm or "nao configur" in norm)
    ):
        return 400, {
            "code": "missing_api_key",
            "message": message,
            "hint": "Configure a chave Gemini/Google TTS no guia inicial ou em .env antes de consultar.",
        }
    if "api key not valid" in norm or ("invalid" in norm and "api key" in norm):
        return 401, {
            "code": "invalid_api_key",
            "message": message,
            "hint": "Confira se a chave foi copiada corretamente no Google AI Studio.",
        }
    if "permission_denied" in norm or "api key" in norm and "permission" in norm:
        return 401, {
            "code": "api_key_not_active",
            "message": message,
            "hint": "Ative a Gemini API no projeto Google Cloud associado a chave e tente novamente.",
        }
    if "resource_exhausted" in norm or "quota" in norm:
        return 429, {
            "code": "quota_exhausted",
            "message": message,
            "hint": "Cota gratuita/escalonamento atingido. Aguarde reset ou ajuste billing/limites.",
        }
    if "rate limit" in norm or "too many requests" in norm:
        return 429, {
            "code": "rate_limited",
            "message": message,
            "hint": "Reduza paralelismo e frequencia das consultas por minuto.",
        }
    if "model" in norm and ("not found" in norm or "unsupported" in norm):
        return 400, {
            "code": "model_unavailable",
            "message": message,
            "hint": "Escolha outro modelo Gemini nas configuracoes da plataforma.",
        }
    if "nenhum modelo de voz suporta audio" in norm or "nenhum modelo de voz disponivel" in norm:
        return 400, {
            "code": "model_unavailable",
            "message": message,
            "hint": "A chave/API atual nao possui modelo de voz compativel neste endpoint. Configure um modelo TTS suportado.",
        }
    if "falha no tts gemini" in norm and (
        "500 internal" in norm
        or "an internal error has occurred" in norm
        or "status': 'internal'" in norm
        or '"status": "internal"' in norm
    ):
        return 503, {
            "code": "upstream_unavailable",
            "message": message,
            "hint": "Servico de voz Gemini indisponivel no momento (erro interno 500). Tente novamente em instantes.",
        }
    if "indisponibilidade upstream apos tentativas" in norm:
        return 503, {
            "code": "upstream_unavailable",
            "message": message,
            "hint": "Servico de voz Gemini instavel no momento. Tente novamente em instantes.",
        }
    if "timeout" in norm or "timed out" in norm or "deadline" in norm or "unavailable" in norm or "503" in norm:
        return 503, {
            "code": "upstream_unavailable",
            "message": message,
            "hint": "Servico Gemini indisponivel no momento. Tente novamente em instantes.",
        }
    return 500, {
        "code": "internal_error",
        "message": message,
        "hint": "Verifique logs do backend para diagnostico detalhado.",
    }


def _is_soft_gemini_validation_error(exc: Exception) -> bool:
    norm = str(exc or "").strip().lower()
    if not norm:
        return False

    hard_failure_markers = (
        "api key not valid",
        "invalid api key",
        "permission_denied",
        "permission denied",
        "gemini_api_key ausente",
        "missing_api_key",
    )
    if any(marker in norm for marker in hard_failure_markers):
        return False

    soft_failure_markers = (
        "timeout",
        "timed out",
        "deadline exceeded",
        "temporarily unavailable",
        "temporario indisponivel",
        "service unavailable",
        "connection error",
        "network",
        "econnreset",
        "read timed out",
        "503",
    )
    return any(marker in norm for marker in soft_failure_markers)


def _raise_api_error(exc: Exception, trace_id: str | None = None) -> None:
    status_code, detail = _classify_runtime_error(exc)
    if trace_id:
        detail = dict(detail)
        detail["trace_id"] = trace_id
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _jsonl_line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "has_gemini_api_key": has_gemini_api_key(),
        "defaults": {
            "reranker_backend": RERANKER_BACKEND,
            "reranker_model": RERANKER_MODEL,
            "gemini_rerank_model": GEMINI_RERANK_MODEL,
            "generation_model": GENERATION_MODEL,
            "explain_model": EXPLAIN_MODEL,
            "tts_provider": TTS_PROVIDER,
            "tts_model": _tts_response_model(),
            "tts_voice": _tts_response_voice(),
            "tts_rate": TTS_RATE,
            "tts_pitch_semitones": TTS_PITCH_SEMITONES,
            "tts_break_alt_ms": TTS_BREAK_ALT_MS,
            "tts_break_art_ms": TTS_BREAK_ART_MS,
            "tts_max_ssml_chars": _tts_response_max_chars(),
            "rag_tuning": get_rag_tuning_defaults(),
        },
    }


@app.get("/api/gemini/status")
def gemini_status_api() -> dict[str, Any]:
    return {
        "status": "ok",
        "required": True,
        "has_api_key": has_gemini_api_key(),
        "supported_models": get_supported_generation_models(),
    }


@app.post("/api/gemini/config")
def gemini_config_api(payload: GeminiConfigRequest) -> dict[str, Any]:
    key = payload.api_key.strip()
    if not key:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "missing_api_key",
                "message": "GEMINI_API_KEY ausente.",
                "hint": "Informe uma chave valida para continuar.",
            },
        )
    validation_warning = ""
    validated = False
    setup_result: dict[str, Any] = {}

    try:
        setup_result = configure_gemini_api_key(
            key,
            validate=payload.validate_key,
            test_model=(payload.test_model or GENERATION_MODEL),
            validation_timeout_ms=payload.validation_timeout_ms,
        )
        validated = bool(setup_result.get("validated"))
    except Exception as exc:
        if payload.validate_key and _is_soft_gemini_validation_error(exc):
            validation_warning = str(exc).strip()
            try:
                setup_result = configure_gemini_api_key(
                    key,
                    validate=False,
                    test_model=(payload.test_model or GENERATION_MODEL),
                    validation_timeout_ms=payload.validation_timeout_ms,
                )
            except Exception as fallback_exc:
                _raise_api_error(fallback_exc)
            validated = False
        else:
            _raise_api_error(exc)

    env_path = ""
    if payload.persist_env:
        env_path = str(_upsert_env_gemini_key(key))
    return {
        "status": "ok",
        "saved": True,
        "validated": bool(validated),
        "test_model": setup_result.get("model", payload.test_model),
        "persisted_env": bool(payload.persist_env),
        "env_path": env_path,
        "has_api_key": has_gemini_api_key(),
        "validation_timeout_ms": int(payload.validation_timeout_ms),
        "validation_warning": validation_warning,
    }


@app.get("/api/rag-config")
def rag_config_api() -> dict[str, Any]:
    return {
        "version": RAG_CONFIG_VERSION,
        "defaults": get_rag_tuning_defaults(),
        "schema": get_rag_tuning_schema(),
    }


@app.get("/api/meu-acervo/sources")
def meu_acervo_sources_api() -> dict[str, Any]:
    return _list_available_sources_payload()


@app.post("/api/meu-acervo/source/delete")
def meu_acervo_source_delete_api(payload: UserSourceActionRequest) -> dict[str, Any]:
    source = _set_user_source_deleted(payload.source_id, deleted=True)
    return {
        "status": "ok",
        "source": source,
        "default_selected": _list_available_sources_payload().get("default_selected", ["ratio"]),
    }


@app.post("/api/meu-acervo/source/restore")
def meu_acervo_source_restore_api(payload: UserSourceActionRequest) -> dict[str, Any]:
    source = _set_user_source_deleted(payload.source_id, deleted=False)
    return {
        "status": "ok",
        "source": source,
        "default_selected": _list_available_sources_payload().get("default_selected", ["ratio"]),
    }


@app.post("/api/meu-acervo/index", status_code=202)
def meu_acervo_index_api(
    files: list[UploadFile] = File(...),
    confirm_index: bool = Form(False),
    source_name: str = Form("Banco 1"),
    ocr_missing_only: bool = Form(True),
) -> dict[str, Any]:
    if USER_ACERVO_REQUIRE_CONFIRM and not bool(confirm_index):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "confirmation_required",
                "message": "Confirmacao manual obrigatoria antes de indexar no Meu Acervo.",
                "hint": "Confirme a indexacao no frontend e reenvie com confirm_index=true.",
            },
        )
    if not files:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "missing_files",
                "message": "Nenhum arquivo PDF enviado para indexacao.",
                "hint": "Selecione ao menos 1 PDF.",
            },
        )
    if len(files) > USER_ACERVO_MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "too_many_files",
                "message": f"Limite de {USER_ACERVO_MAX_FILES_PER_REQUEST} arquivos por indexacao.",
                "hint": "Envie em lotes menores.",
            },
        )

    source = _ensure_user_source(source_name)
    source_id = str(source.get("id") or "").strip()
    source_label = str(source.get("name") or source_id).strip() or source_id

    stored_files: list[dict[str, Any]] = []
    skipped_non_pdf = 0
    request_total_bytes = 0

    for upload in files:
        filename = (upload.filename or "documento.pdf").strip() or "documento.pdf"
        try:
            if not filename.lower().endswith(".pdf"):
                skipped_non_pdf += 1
                continue

            temp_path, digest, file_bytes = _store_upload_file(upload, filename)
            request_total_bytes += int(file_bytes)
            if request_total_bytes > USER_ACERVO_MAX_REQUEST_SIZE_BYTES:
                _raise_user_acervo_validation_error(
                    code="request_too_large",
                    message=(
                        "Lote de indexacao excede o limite total de "
                        f"{USER_ACERVO_MAX_REQUEST_SIZE_MB} MB por requisicao."
                    ),
                    hint="Envie em lotes menores ou aumente USER_ACERVO_MAX_REQUEST_SIZE_MB no backend.",
                )
            stored_files.append(
                {
                    "filename": filename,
                    "digest": digest,
                    "file_bytes": int(file_bytes),
                    "temp_path": str(temp_path),
                }
            )
        except _UserAcervoValidationError as exc:
            for item in stored_files:
                try:
                    temp = Path(str(item.get("temp_path") or "")).expanduser()
                    if temp.exists():
                        temp.unlink()
                except Exception:
                    pass
            _raise_user_acervo_validation_error(exc.code, exc.message, exc.hint)
        except HTTPException:
            for item in stored_files:
                try:
                    temp = Path(str(item.get("temp_path") or "")).expanduser()
                    if temp.exists():
                        temp.unlink()
                except Exception:
                    pass
            raise
        except Exception as exc:
            for item in stored_files:
                try:
                    temp = Path(str(item.get("temp_path") or "")).expanduser()
                    if temp.exists():
                        temp.unlink()
                except Exception:
                    pass
            _raise_api_error(exc)
        finally:
            try:
                upload.file.close()
            except Exception:
                pass

    if not stored_files:
        _raise_user_acervo_validation_error(
            code="missing_files",
            message="Nenhum arquivo PDF valido enviado para indexacao.",
            hint="Selecione ao menos 1 PDF valido.",
        )

    try:
        job_id = _start_user_acervo_index_job(
            source_id=source_id,
            source_label=source_label,
            ocr_missing_only=bool(ocr_missing_only),
            stored_files=stored_files,
            pre_skipped_files=int(skipped_non_pdf),
        )
    except Exception as exc:
        for item in stored_files:
            try:
                temp_path = Path(str(item.get("temp_path") or "")).expanduser()
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
        _raise_api_error(exc)

    return {
        "status": "accepted",
        "job_id": job_id,
        "source_id": source_id,
        "source_label": source_label,
        "accepted_files": len(stored_files),
        "skipped_files": int(skipped_non_pdf),
        "poll_after_ms": USER_ACERVO_INDEX_JOB_POLL_MS,
    }


@app.get("/api/meu-acervo/index/jobs/{job_id}")
def meu_acervo_index_job_status_api(job_id: str) -> dict[str, Any]:
    payload = _get_user_acervo_job_payload(job_id)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "job_not_found",
                "message": "Job de indexacao nao encontrado.",
                "hint": "Inicie uma nova indexacao no Meu Acervo.",
            },
        )
    return payload


@app.post("/api/query")
def query_api(payload: QueryRequest) -> dict[str, Any]:
    try:
        answer, docs, meta = run_query(
            query=payload.query,
            tribunais=payload.tribunais,
            tipos=payload.tipos,
            sources=payload.sources,
            prefer_recent=payload.prefer_recent,
            prefer_user_sources=payload.prefer_user_sources,
            reranker_backend=payload.reranker_backend,
            ramos=payload.ramos,
            orgaos=payload.orgaos,
            relator_contains=payload.relator_contains,
            date_from=payload.date_from,
            date_to=payload.date_to,
            rag_config=payload.rag_config,
            trace=payload.trace,
            return_meta=True,
        )
    except Exception as exc:
        _raise_api_error(exc)

    return {
        "answer": answer,
        "docs": [_serialize_doc(i, d) for i, d in enumerate(docs, 1)],
        "meta": meta,
    }


@app.post("/api/query/stream")
def query_stream_api(payload: QueryRequest) -> StreamingResponse:
    event_queue: queue.Queue[Optional[dict[str, Any]]] = queue.Queue()

    def stage_callback(stage: str, stage_payload: dict[str, Any]) -> None:
        event_queue.put(
            {
                "event": "stage",
                "stage": str(stage or ""),
                "payload": stage_payload or {},
            }
        )

    def worker() -> None:
        try:
            answer, docs, meta = run_query(
                query=payload.query,
                tribunais=payload.tribunais,
                tipos=payload.tipos,
                sources=payload.sources,
                prefer_recent=payload.prefer_recent,
                prefer_user_sources=payload.prefer_user_sources,
                reranker_backend=payload.reranker_backend,
                ramos=payload.ramos,
                orgaos=payload.orgaos,
                relator_contains=payload.relator_contains,
                date_from=payload.date_from,
                date_to=payload.date_to,
                rag_config=payload.rag_config,
                trace=payload.trace,
                stage_callback=stage_callback,
                return_meta=True,
            )
            event_queue.put(
                {
                    "event": "result",
                    "data": {
                        "answer": answer,
                        "docs": [_serialize_doc(i, d) for i, d in enumerate(docs, 1)],
                        "meta": meta,
                    },
                }
            )
        except Exception as exc:  # pragma: no cover - integration-level behavior
            status_code, detail = _classify_runtime_error(exc)
            event_queue.put(
                {
                    "event": "error",
                    "status_code": int(status_code),
                    "detail": detail,
                }
            )
        finally:
            event_queue.put(None)

    def stream_iter():
        yield _jsonl_line({"event": "started"})
        while True:
            try:
                item = event_queue.get(timeout=0.5)
            except queue.Empty:
                yield _jsonl_line({"event": "heartbeat"})
                continue
            if item is None:
                break
            yield _jsonl_line(item)

    threading.Thread(target=worker, daemon=True).start()
    return StreamingResponse(
        stream_iter(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/explain")
def explain_api(payload: ExplainRequest) -> dict[str, Any]:
    try:
        explanation = explain_answer(
            query=payload.query,
            answer=payload.answer,
            docs=payload.docs or [],
            model_name=payload.model_name or EXPLAIN_MODEL,
        )
    except Exception as exc:
        _raise_api_error(exc)
    return {"explanation": explanation}


@app.post("/api/tts")
def tts_api(payload: TTSRequest) -> dict[str, Any]:
    trace_id = _new_trace_id()
    try:
        synthesized = _synthesize_tts(payload.text, trace_id=trace_id)
    except Exception as exc:
        _raise_api_error(exc, trace_id=trace_id)
    if isinstance(synthesized, tuple):
        audio, mime_type = synthesized
    else:
        audio, mime_type = synthesized, "audio/mpeg"
    return {
        "mime_type": mime_type,
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "voice": _tts_response_voice(),
        "model": _tts_response_model(),
        "provider": TTS_PROVIDER,
        "rate": TTS_RATE,
        "pitch_semitones": TTS_PITCH_SEMITONES,
        "break_alt_ms": TTS_BREAK_ALT_MS,
        "break_art_ms": TTS_BREAK_ART_MS,
        "max_ssml_chars": _tts_response_max_chars(),
        "trace_id": trace_id,
    }


@app.post("/api/tts/stream")
def tts_stream_api(payload: TTSRequest) -> StreamingResponse:
    event_queue: queue.Queue[Optional[dict[str, Any]]] = queue.Queue()
    trace_id = _new_trace_id()

    def worker() -> None:
        emitted = 0
        try:
            for audio_bytes, mime_type, chunk_index, total_chunks in _stream_tts_chunks(
                payload.text,
                trace_id=trace_id,
            ):
                emitted += 1
                event_queue.put(
                    {
                        "event": "chunk",
                        "trace_id": trace_id,
                        "index": int(chunk_index),
                        "total": int(total_chunks),
                        "mime_type": str(mime_type or "audio/wav"),
                        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                        "voice": _tts_response_voice(),
                        "provider": TTS_PROVIDER,
                    }
                )
            event_queue.put(
                {
                    "event": "done",
                    "trace_id": trace_id,
                    "chunks_emitted": int(emitted),
                }
            )
        except Exception as exc:
            status_code, detail = _classify_runtime_error(exc)
            detail = dict(detail)
            detail["trace_id"] = trace_id
            event_queue.put(
                {
                    "event": "error",
                    "trace_id": trace_id,
                    "status_code": int(status_code),
                    "detail": detail,
                }
            )
        finally:
            event_queue.put(None)

    def stream_iter():
        yield _jsonl_line(
            {
                "event": "started",
                "trace_id": trace_id,
                "voice": _tts_response_voice(),
                "model": _tts_response_model(),
                "provider": TTS_PROVIDER,
            }
        )
        while True:
            try:
                item = event_queue.get(timeout=0.5)
            except queue.Empty:
                yield _jsonl_line({"event": "heartbeat", "trace_id": trace_id})
                continue
            if item is None:
                break
            yield _jsonl_line(item)

    threading.Thread(target=worker, daemon=True, name=f"tts-stream-{trace_id}").start()
    return StreamingResponse(
        stream_iter(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



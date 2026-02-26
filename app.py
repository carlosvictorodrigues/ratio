import contextlib
import base64
import html
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent))

from rag.query import RERANKER_BACKEND, explain_answer, run_query

st.set_page_config(
    page_title="Ratio",
    page_icon="âš–ï¸",
    layout="wide",
    initial_sidebar_state="expanded",
)


TYPE_LABELS = {
    "acordao": "AcÃ³rdÃ£o",
    "acordao_sv": "AcÃ³rdÃ£o (SV)",
    "sumula": "SÃºmula",
    "sumula_stj": "SÃºmula STJ",
    "sumula_vinculante": "SÃºmula Vinculante",
    "informativo": "Informativo",
    "monocratica": "DecisÃ£o MonocrÃ¡tica",
    "monocratica_sv": "DecisÃ£o MonocrÃ¡tica (SV)",
    "tema_repetitivo_stj": "Tema Repetitivo STJ",
}

ROLE_LABELS = {
    "tese_material": "Tese material",
    "barreira_processual": "Barreira processual",
    "aplicacao": "AplicaÃ§Ã£o/caso",
}

AUTHORITY_LEVEL_LABELS = {
    "A": "Vinculante forte",
    "B": "Precedente qualificado (tese/tema)",
    "C": "Observancia qualificada",
    "D": "Nao vinculante (orientativo)",
    "E": "Editorial/consulta",
}

LEGAL_TTS_EXPANSIONS = [
    (r"\bHC\b", "habeas corpus"),
    (r"\bRHC\b", "recurso ordinÃ¡rio em habeas corpus"),
    (r"\bMS\b", "mandado de seguranÃ§a"),
    (r"\bRMS\b", "recurso ordinÃ¡rio em mandado de seguranÃ§a"),
    (r"\bREsp\b", "recurso especial"),
    (r"\bRE\b", "recurso extraordinÃ¡rio"),
    (r"\bARE\b", "agravo em recurso extraordinÃ¡rio"),
    (r"\bAI\b", "agravo de instrumento"),
    (r"\bAgInt\b", "agravo interno"),
    (r"\bAgR\b", "agravo regimental"),
    (r"\bAgRg\b", "agravo regimental"),
    (r"\bEDcl\b", "embargos de declaraÃ§Ã£o"),
    (r"\bEDI\b", "embargos de divergÃªncia"),
    (r"\bADI\b", "aÃ§Ã£o direta de inconstitucionalidade"),
    (r"\bADC\b", "aÃ§Ã£o declaratÃ³ria de constitucionalidade"),
    (r"\bADPF\b", "arguiÃ§Ã£o de descumprimento de preceito fundamental"),
    (r"\bIRDR\b", "incidente de resoluÃ§Ã£o de demandas repetitivas"),
    (r"\bIAC\b", "incidente de assunÃ§Ã£o de competÃªncia"),
    (r"\bRG\b", "repercussÃ£o geral"),
    (r"\bSTF\b", "Supremo Tribunal Federal"),
    (r"\bSTJ\b", "Superior Tribunal de JustiÃ§a"),
    (r"\bCPC\b", "CÃ³digo de Processo Civil"),
    (r"\bCPP\b", "CÃ³digo de Processo Penal"),
    (r"\bCP\b", "CÃ³digo Penal"),
    (r"\bCF\b", "ConstituiÃ§Ã£o Federal"),
    (r"\bCNJ\b", "Conselho Nacional de JustiÃ§a"),
    (r"\bTJ\b", "Tribunal de JustiÃ§a"),
    (r"\bTRF\b", "Tribunal Regional Federal"),
]

TTS_PRONUNCIATION_FIXES = [
    (r"\bjustica\b", "justiÃ§a"),
    (r"\bjudiciario\b", "judiciÃ¡rio"),
    (r"\bjuridico\b", "jurÃ­dico"),
    (r"\bjuridica\b", "jurÃ­dica"),
    (r"\bconstituicao\b", "constituiÃ§Ã£o"),
    (r"\bcodigo\b", "cÃ³digo"),
    (r"\brepercussao\b", "repercussÃ£o"),
    (r"\bdecisao\b", "decisÃ£o"),
    (r"\bacordao\b", "acÃ³rdÃ£o"),
    (r"\bsumula\b", "sÃºmula"),
    (r"\bparagrafo\b", "parÃ¡grafo"),
    (r"\bnao\b", "nÃ£o"),
]

DOC_CITATION_BRACKET_PATTERN = re.compile(
    r"\[(?=[^\]]*(?:DOC(?:UMENTO)?\.?|DOCUMENTO))(?=[^\]]*(?:\d+|[Nn]))[^\]]*\]",
    flags=re.IGNORECASE,
)

TTS_RATE = 1.2
TTS_PITCH_SEMITONES = -4.5
TTS_BREAK_ALT_MS = 450
TTS_BREAK_ART_MS = 900
TTS_MAX_CHARS = 5000
TTS_ENABLE_ALTERNATIVES = True
TTS_ALTERNATIVE_LABEL = "Alternativa"
TTS_MARK_ALT = "[[BRK_ALT]]"
TTS_MARK_ART = "[[BRK_ART]]"
TTS_VOICE_PREFERENCES = [
    "pt-BR-Neural2-B",
    "Google portuguÃªs do Brasil",
    "Google portuguÃªs do Brasil (Brasil)",
    "Microsoft Maria - Portuguese (Brazil)",
    "Microsoft Antonio - Portuguese (Brazil)",
]
TTS_VOICE_NAME = "pt-BR-Neural2-B"
TTS_LANGUAGE_CODE = "pt-BR"
TTS_API_KEY = os.getenv("GOOGLE_TTS_API_KEY") or os.getenv("GEMINI_API_KEY")
TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
AUTO_PREGENERATE_AUDIO = os.getenv("AUTO_PREGENERATE_AUDIO", "1").strip() != "0"

STAGE_ORDER = [
    ("embedding_start", "Embeddings"),
    ("retrieval_start", "Busca"),
    ("rerank_start", "Rerank"),
    ("generation_start", "GeraÃ§Ã£o"),
    ("validation_start", "ValidaÃ§Ã£o"),
]
STAGE_INDEX = {key: idx for idx, (key, _) in enumerate(STAGE_ORDER)}
STAGE_INDEX["done"] = len(STAGE_ORDER)


def repair_mojibake(text: str) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        return str(text)
    try:
        fixed = text.encode("latin-1").decode("utf-8")
        if "\ufffd" not in fixed:
            return fixed
    except Exception:
        pass
    return text


def safe_text(value: str, default: str = "-") -> str:
    text = repair_mojibake((value or "").strip())
    return text or default


def inject_css() -> None:
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,500;8..60,700&display=swap');

            :root {
                --bg-0: #060b17;
                --bg-1: #0c1324;
                --text: #eef2ff;
                --text-soft: #b8c4e3;
                --line: rgba(196, 208, 237, 0.22);
            }

            .stApp {
                background:
                    radial-gradient(1200px 520px at 8% -12%, rgba(196, 163, 93, 0.14), transparent 45%),
                    radial-gradient(1200px 520px at 92% -24%, rgba(61, 104, 181, 0.12), transparent 45%),
                    linear-gradient(180deg, var(--bg-1) 0%, var(--bg-0) 100%);
            }

            .stApp, .stApp p, .stApp label, .stApp li, .stApp div {
                font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
                color: var(--text);
            }

            h1, h2, h3 {
                font-family: "Source Serif 4", Georgia, serif !important;
                letter-spacing: 0.2px;
            }

            [data-testid="stSidebar"] {
                border-right: 1px solid var(--line);
                background: linear-gradient(180deg, rgba(20, 29, 48, 0.96) 0%, rgba(12, 18, 32, 0.98) 100%);
            }

            .hero-wrap {
                padding: 18px 22px;
                border-radius: 14px;
                border: 1px solid var(--line);
                background: linear-gradient(145deg, rgba(23, 33, 54, 0.72), rgba(14, 22, 39, 0.72));
                margin-bottom: 10px;
            }

            .hero-title {
                margin: 0;
                font-size: 2.45rem;
                font-weight: 700;
                color: #f5f7ff;
            }

            .hero-subtitle {
                margin: 8px 0 0 0;
                color: var(--text-soft);
                font-size: 1.04rem;
            }

            .chips {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin: 8px 0 16px 0;
            }

            .chip {
                border: 1px solid var(--line);
                border-radius: 999px;
                padding: 4px 10px;
                font-size: 0.82rem;
                color: var(--text-soft);
                background: rgba(30, 44, 70, 0.48);
            }

            .stage-grid {
                display: grid;
                grid-template-columns: repeat(5, minmax(90px, 1fr));
                gap: 8px;
                margin: 10px 0 14px 0;
            }

            .stage-pill {
                border-radius: 10px;
                border: 1px solid var(--line);
                padding: 7px 8px;
                font-size: 0.78rem;
                text-align: center;
                background: rgba(18, 29, 50, 0.65);
                color: var(--text-soft);
            }

            .stage-done {
                border-color: rgba(73, 185, 133, 0.55);
                color: #d8ffe9;
                background: rgba(44, 91, 76, 0.30);
            }

            .stage-active {
                border-color: rgba(209, 180, 114, 0.62);
                color: #fff4db;
                background: rgba(86, 70, 37, 0.35);
            }

            .source-mini {
                border: 1px solid var(--line);
                background: rgba(20, 30, 50, 0.62);
                border-radius: 11px;
                padding: 11px 12px;
                margin-bottom: 9px;
            }

            /* Controles de audio e chat mais discretos */
            [data-testid="stChatMessage"] .stButton > button {
                min-height: 1.95rem;
                padding: 0.2rem 0.5rem;
                font-size: 0.84rem;
                border-radius: 8px;
            }

            [data-testid="stChatMessage"] [data-testid="stAvatarIcon"] {
                width: 1.38rem;
                height: 1.38rem;
                font-size: 0.7rem;
            }

            [data-testid="stChatMessage"] audio {
                width: 100%;
                max-width: 760px;
                height: 32px;
                position: sticky;
                top: 6px;
                z-index: 3;
                border-radius: 999px;
                background: rgba(9, 14, 28, 0.94);
                margin-bottom: 10px;
            }

            .source-title {
                font-size: 0.95rem;
                font-weight: 600;
                margin-bottom: 4px;
                color: #eef2ff;
            }

            .source-meta {
                font-size: 0.80rem;
                color: var(--text-soft);
                margin: 0;
            }

            .stats-line {
                font-size: 0.84rem;
                color: var(--text-soft);
                margin-top: 8px;
            }

            .evidence-text {
                white-space: pre-wrap;
                overflow-wrap: anywhere;
                word-break: break-word;
                margin-top: 8px;
                padding: 13px;
                border-radius: 10px;
                border: 1px solid rgba(196, 208, 237, 0.18);
                background: rgba(18, 29, 50, 0.5);
                line-height: 1.55;
            }

            .stMarkdown a {
                overflow-wrap: anywhere;
                word-break: break-word;
            }

            @media (max-width: 920px) {
                .hero-title {
                    font-size: 2rem;
                }
                .stage-grid {
                    grid-template-columns: repeat(2, minmax(90px, 1fr));
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_date(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "Sem data"

    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return raw[:10]


def type_label(tipo: str) -> str:
    if not tipo:
        return "Documento"
    return TYPE_LABELS.get(tipo, tipo.replace("_", " ").title())


def orgao_label(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return "Indefinido"
    if "monocr" in value.lower():
        return "DecisÃ£o MonocrÃ¡tica"
    return value


def role_label(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return "-"
    return ROLE_LABELS.get(value, value.replace("_", " ").title())


def authority_level_label(level: str, fallback: str = "") -> str:
    value = (level or "").strip().upper()
    if value in AUTHORITY_LEVEL_LABELS:
        return AUTHORITY_LEVEL_LABELS[value]
    if fallback:
        return fallback
    return AUTHORITY_LEVEL_LABELS["D"]


def processo_display(doc: dict) -> str:
    processo = safe_text(doc.get("processo") or f"ID: {doc.get('doc_id')}")
    tipo = (doc.get("tipo") or "").strip().lower()
    corpus = (
        f"{repair_mojibake(doc.get('processo', '') or '')}\n"
        f"{repair_mojibake(doc.get('texto_busca', '') or '')}\n"
        f"{repair_mojibake(doc.get('texto_integral', '') or '')}"
    ).lower()

    if tipo == "acordao":
        if "agravo regimental" in corpus and not processo.lower().startswith("agr"):
            return f"AgR no {processo}"
        if "agravo interno" in corpus and not processo.lower().startswith("agint"):
            return f"AgInt no {processo}"
        if "embargos de declar" in corpus and not processo.lower().startswith("edcl"):
            return f"EDcl no {processo}"
    return processo


def sanitize_retrieved_text(raw: str) -> str:
    text = repair_mojibake(html.unescape((raw or "").replace("\r\n", "\n").replace("\r", "\n")))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h\d|section|article)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)<[^>]+>", "", text)
    text = re.sub(r"(?im)^\s*(supremo tribunal federal|superior tribunal de justi[cÃ§]a|p[aÃ¡]gina \d+).*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return html.escape(text)


def normalize_for_tts(raw: str) -> str:
    text = html.unescape((raw or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h\d|section|article)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)<[^>]+>", "", text)
    text = repair_mojibake(text)

    # Remove seÃ§Ãµes tÃ©cnicas que nÃ£o agregam na leitura em voz alta.
    text = re.sub(r"(?is)\[\s*AVISO DE AUDITORIA[^\n]*?(?:\n|$).*?(?=\n\s*Documentos citados(?:\s*\([^\n]*\))?:|\Z)", "", text)
    text = re.sub(r"(?is)\n\s*Documentos citados(?:\s*\([^\n]*\))?:\s*.*$", "", text)
    # Remove tags de citaÃ§Ã£o no corpo: [DOC. 1], [DOC. 1, DOC. 2], [DOCUMENTO 7], etc.
    text = DOC_CITATION_BRACKET_PATTERN.sub("", text)
    # Remove sintaxe markdown para evitar leituras indesejadas no TTS
    # (ex.: ">" -> "maior que", "**" -> "asterisco").
    text = re.sub(r"(?m)^\s*>\s*", "", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = text.replace("*", "")
    # Remove colchetes residuais vazios e espaÃ§os duplicados ao redor de pontuaÃ§Ã£o.
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)

    for pattern, expanded in LEGAL_TTS_EXPANSIONS:
        text = re.sub(pattern, expanded, text, flags=re.IGNORECASE)
    for pattern, fixed in TTS_PRONUNCIATION_FIXES:
        text = re.sub(pattern, fixed, text, flags=re.IGNORECASE)

    if TTS_ENABLE_ALTERNATIVES:
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
    text = re.sub(r"\s+", " ", text).strip()
    return text


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


@st.cache_data(show_spinner=False, ttl=60 * 60, max_entries=128)
def synthesize_google_tts(text: str) -> bytes:
    if not TTS_API_KEY:
        raise RuntimeError("GOOGLE_TTS_API_KEY (ou GEMINI_API_KEY) nao configurada para TTS.")

    prepared = normalize_for_tts(text)
    chunks = _split_tts_chunks(prepared)
    audio_parts: list[bytes] = []
    for chunk in chunks:
        ssml = _build_ssml(chunk)
        ssml_bytes = len(ssml.encode("utf-8"))
        if ssml_bytes > TTS_MAX_CHARS:
            raise RuntimeError(
                f"Falha no TTS: bloco SSML com {ssml_bytes} bytes excede o limite de {TTS_MAX_CHARS} bytes."
            )
        payload = {
            "input": {"ssml": ssml},
            "voice": {"languageCode": TTS_LANGUAGE_CODE, "name": TTS_VOICE_NAME},
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": TTS_RATE,
                "pitch": TTS_PITCH_SEMITONES,
            },
        }
        resp = requests.post(
            f"{TTS_ENDPOINT}?key={TTS_API_KEY}",
            json=payload,
            timeout=40,
        )
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except Exception:
                detail = resp.text[:300]
            raise RuntimeError(f"Falha no TTS ({resp.status_code}): {detail}")
        data = resp.json()
        b64 = data.get("audioContent")
        if not b64:
            raise RuntimeError("Resposta TTS sem audioContent.")
        audio_parts.append(base64.b64decode(b64))

    return b"".join(audio_parts)


def prefetch_audio_assets(message: dict, msg_key: str) -> None:
    if not AUTO_PREGENERATE_AUDIO:
        return
    if st.session_state["audio_prefetch_done"].get(msg_key):
        return

    answer_text = repair_mojibake(message.get("answer", ""))
    question_text = repair_mojibake(message.get("question", ""))
    docs = message.get("top_docs") or []

    def build_explanation_and_audio() -> tuple[str, bytes]:
        explanation = explain_answer(
            query=question_text,
            answer=answer_text,
            docs=docs,
        )
        explanation = repair_mojibake(explanation)
        explanation_audio = synthesize_google_tts(explanation)
        return explanation, explanation_audio

    need_answer_audio = bool(answer_text) and msg_key not in st.session_state["audio_listen_cache"]
    need_explain_text = msg_key not in st.session_state["explain_cache"]
    need_explain_audio = msg_key not in st.session_state["audio_explain_cache"]

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_answer = (
                executor.submit(synthesize_google_tts, answer_text)
                if need_answer_audio
                else None
            )
            future_explain_bundle = (
                executor.submit(build_explanation_and_audio)
                if need_explain_text
                else None
            )
            future_explain_audio = (
                executor.submit(
                    synthesize_google_tts,
                    st.session_state["explain_cache"].get(msg_key, ""),
                )
                if (not need_explain_text and need_explain_audio)
                else None
            )

            if future_answer is not None:
                st.session_state["audio_listen_cache"][msg_key] = future_answer.result()
            if future_explain_bundle is not None:
                explanation_text, explanation_audio = future_explain_bundle.result()
                st.session_state["explain_cache"][msg_key] = explanation_text
                st.session_state["audio_explain_cache"][msg_key] = explanation_audio
            elif future_explain_audio is not None:
                st.session_state["audio_explain_cache"][msg_key] = future_explain_audio.result()
    except Exception as exc:
        st.session_state["audio_error"] = str(exc)

    if msg_key not in st.session_state["audio_cache"]:
        default_audio = st.session_state["audio_listen_cache"].get(msg_key)
        if default_audio:
            st.session_state["audio_cache"][msg_key] = default_audio
            st.session_state["_audio_mode"][msg_key] = "resposta"

    st.session_state["audio_prefetch_done"][msg_key] = True


def expand_orgaos_selection(orgaos: list[str]) -> list[str]:
    expanded: list[str] = []
    for orgao in orgaos:
        expanded.append(orgao)
        # Backward compatibility with older rows already ingested.
        if orgao == "DecisÃ£o MonocrÃ¡tica":
            expanded.append("MonocrÃ¡tica")
    # Keep order, remove duplicates.
    return list(dict.fromkeys(expanded))


def build_active_filter_chips(scope_all: bool, config: dict) -> str:
    if scope_all:
        return "<div class='chips'><span class='chip'>Escopo: base completa (sem pre-filtro)</span></div>"

    chips = []
    if config.get("tribunais"):
        chips.append("Tribunais: " + ", ".join(config["tribunais"]))
    if config.get("tipos"):
        labels = [type_label(t) for t in config["tipos"]]
        chips.append("Tipos: " + ", ".join(labels))
    if config.get("ramos"):
        chips.append("Ramos: " + ", ".join(config["ramos"]))
    if config.get("orgaos"):
        chips.append("Ã“rgÃ£os: " + ", ".join(config["orgaos"]))
    if config.get("relator"):
        chips.append("Relator contÃ©m: " + config["relator"])
    if config.get("date_from") or config.get("date_to"):
        chips.append(f"Data: {config.get('date_from') or '...'} atÃ© {config.get('date_to') or '...'}")

    if not chips:
        chips = ["Escopo: base completa (sem pre-filtro)"]

    html_chips = "".join(f"<span class='chip'>{c}</span>" for c in chips)
    return f"<div class='chips'>{html_chips}</div>"


def render_pipeline_status(placeholder, stage: str, timings: dict) -> None:
    idx = STAGE_INDEX.get(stage, 0)
    pills = []
    for i, (_, label) in enumerate(STAGE_ORDER):
        css = "stage-pill"
        if i < idx:
            css += " stage-done"
        elif i == idx and stage != "done":
            css += " stage-active"
        pills.append(f"<div class='{css}'>{label}</div>")

    timing_line = " | ".join(f"{k}: {v:.2f}s" for k, v in timings.items() if isinstance(v, (int, float)))
    if not timing_line:
        timing_line = "Inicializando..."

    placeholder.markdown(
        "<div class='stage-grid'>" + "".join(pills) + "</div>"
        + f"<div class='stats-line'>Pipeline: {timing_line}</div>",
        unsafe_allow_html=True,
    )


@st.dialog("Detalhes da Fonte Analisada", width="large")
def show_source_dialog(d: dict):
    tipo = type_label(d.get("tipo") or "")
    processo = processo_display(d)
    tribunal = safe_text(d.get("tribunal") or "-")
    dt = format_date(d.get("data_julgamento") or "")
    score = d.get("_final_score", 0.0)
    sem = d.get("_semantic_score", 0.0)
    lex = d.get("_lexical_score", 0.0)
    rec = d.get("_recency_score", 0.0)
    thesis = d.get("_thesis_score", 0.0)
    procedural = d.get("_procedural_score", 0.0)
    authority_score = d.get("_authority_score", 0.0)
    authority_level = (d.get("_authority_level") or "-").upper()
    authority_label = authority_level_label(authority_level, d.get("_authority_label") or "")
    authority_reason = d.get("_authority_reason") or "-"
    role = role_label(d.get("_document_role") or "")
    url = d.get("url")
    text = sanitize_retrieved_text(d.get("texto_integral") or "")
    orgao = orgao_label(safe_text(d.get("orgao_julgador") or ""))
    relator = safe_text(d.get("relator") or "-")
    ramo = safe_text(d.get("ramo_direito") or "-")

    st.subheader(f"{tipo}: {processo}")
    st.markdown(
        f"**Tribunal/Ã“rgÃ£o:** {tribunal} - {orgao}  \n"
        f"**Relator(a):** {relator}  \n"
        f"**Julgamento:** {dt}  \n"
        f"**Ramo:** {ramo}  \n"
        f"**Forca normativa:** Nivel {authority_level} ({authority_label})  \n"
        f"**Motivo de hierarquia:** {authority_reason}  \n"
        f"**Papel no ranking:** {role}  \n"
        f"**Score:** Final {score:.3f} | SemÃ¢ntico {sem:.3f} | Lexical {lex:.3f} | RecÃªncia {rec:.3f} | "
        f"Hierarquia {authority_score:.3f} | Tese {thesis:.3f} | Processual {procedural:.3f}"
    )
    if url:
        st.markdown(f"**ðŸ”— Inteiro Teor Oficial:** [{url}]({url})")
    
    st.markdown("---")
    st.markdown("**Texto recuperado pelo motor RAG:**")
    st.markdown(f"<div class='evidence-text'>{text}</div>", unsafe_allow_html=True)


def render_sources_panel(docs: list[dict], msg_idx: int) -> None:
    st.markdown("#### Fontes ranqueadas")
    if not docs:
        st.info("Nenhuma fonte retornada.")
        return

    for i, d in enumerate(docs, 1):
        processo = processo_display(d)
        tipo = type_label(d.get("tipo") or "")
        tribunal = safe_text(d.get("tribunal") or "-")
        dt = format_date(d.get("data_julgamento") or "")
        score = d.get("_final_score", 0.0)
        authority_level = (d.get("_authority_level") or "-").upper()
        authority_label = authority_level_label(authority_level, d.get("_authority_label") or "")
        relator = safe_text(d.get("relator") or "")
        orgao = orgao_label(safe_text(d.get("orgao_julgador") or ""))
        if relator != "-" and orgao != "Indefinido":
            relatoria = f"Relator(a): {relator} Â· Ã“rgÃ£o: {orgao}"
        elif relator != "-":
            relatoria = f"Relator(a): {relator}"
        else:
            relatoria = f"Ã“rgÃ£o: {orgao}"

        st.markdown(
            f"""
            <div class="source-mini">
                <div class="source-title">[DOCUMENTO {i}] {tipo}: {processo}</div>
                <p class="source-meta">{tribunal} Â· {dt}</p>
                <p class="source-meta">Forca normativa: Nivel {authority_level} ({authority_label})</p>
                <p class="source-meta">Score de RelevÃ¢ncia: {score:.3f}</p>
                <p class="source-meta">{relatoria}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(f"Ler [DOCUMENTO {i}]", key=f"btn_src_{msg_idx}_{i}_{d.get('doc_id')}", use_container_width=True):
            show_source_dialog(d)


def stop_audio_playback() -> None:
    components.html(
        """
        <script>
        (() => {
            try {
                const doc = (window.parent && window.parent.document) || document;
                doc.querySelectorAll("audio").forEach((a) => {
                    try {
                        a.pause();
                        a.currentTime = 0;
                    } catch (_) {}
                });
            } catch (_) {}
        })();
        </script>
        """,
        height=0,
    )


def render_assistant_message(message: dict, show_logs: bool, msg_idx: int) -> None:
    with st.chat_message("assistant"):
        left, right = st.columns([1.75, 1.05], gap="large")
        msg_key = str(msg_idx)
        answer_text = repair_mojibake(message.get("answer", ""))
        question_text = repair_mojibake(message.get("question", ""))

        with left:
            action_col1, action_col2, action_col3 = st.columns([0.9, 1.1, 0.9], gap="small")
            if action_col1.button("Ouvir", key=f"btn_listen_{msg_idx}", use_container_width=True):
                with st.spinner("Preparando Ã¡udio..."):
                    try:
                        audio_blob = st.session_state["audio_listen_cache"].get(msg_key)
                        if not audio_blob:
                            audio_blob = synthesize_google_tts(answer_text)
                            st.session_state["audio_listen_cache"][msg_key] = audio_blob
                        st.session_state["audio_cache"][msg_key] = audio_blob
                        st.session_state["_autoplay_audio_msg"] = msg_key
                        st.session_state["_audio_mode"][msg_key] = "resposta"
                    except Exception as exc:
                        st.session_state["audio_error"] = str(exc)

            if action_col2.button("Explicar", key=f"btn_explain_{msg_idx}", use_container_width=True):
                with st.spinner("Preparando explicaÃ§Ã£o..."):
                    try:
                        explanation = st.session_state["explain_cache"].get(msg_key)
                        if not explanation:
                            explanation = explain_answer(
                                query=question_text,
                                answer=answer_text,
                                docs=message.get("top_docs") or [],
                            )
                            explanation = repair_mojibake(explanation)
                            st.session_state["explain_cache"][msg_key] = explanation
                        audio_blob = st.session_state["audio_explain_cache"].get(msg_key)
                        if not audio_blob:
                            audio_blob = synthesize_google_tts(explanation)
                            st.session_state["audio_explain_cache"][msg_key] = audio_blob
                        st.session_state["audio_cache"][msg_key] = audio_blob
                        st.session_state["_autoplay_audio_msg"] = msg_key
                        st.session_state["_audio_mode"][msg_key] = "explicacao"
                    except Exception as exc:
                        st.session_state["audio_error"] = str(exc)

            if action_col3.button("Parar", key=f"btn_stop_{msg_idx}", use_container_width=True):
                st.session_state["audio_cache"].pop(msg_key, None)
                st.session_state["_autoplay_audio_msg"] = ""
                st.session_state["_audio_mode"].pop(msg_key, None)
                stop_audio_playback()

            audio_blob = st.session_state["audio_cache"].get(msg_key)
            if audio_blob:
                autoplay = st.session_state.get("_autoplay_audio_msg") == msg_key
                mode = st.session_state["_audio_mode"].get(msg_key, "resposta")
                st.caption(f"Audio atual: {mode}.")
                st.audio(audio_blob, format="audio/mp3", autoplay=autoplay)
                if autoplay:
                    st.session_state["_autoplay_audio_msg"] = ""

            st.markdown(answer_text)

            if st.session_state.get("audio_error"):
                st.warning(f"Falha no TTS: {st.session_state['audio_error']}")
                st.session_state["audio_error"] = ""

            if show_logs and message.get("logs"):
                with st.expander("Logs tecnicos"):
                    st.code(message["logs"])

        with right:
            meta = message.get("meta", {})
            total = meta.get("total_seconds")
            st.markdown("#### Metricas")
            st.markdown(f"- Tempo total: `{total:.2f}s`" if isinstance(total, (int, float)) else "- Tempo total: `-`")
            st.markdown(f"- Candidatos hibridos: `{meta.get('candidates')}`")
            st.markdown(f"- Fontes finais: `{meta.get('returned_docs')}`")
            st.markdown(f"- Priorizar recentes: `{meta.get('prefer_recent')}`")
            st.markdown(f"- Reranker: `{meta.get('reranker_backend', '-')}`")
            render_sources_panel(message.get("top_docs", []), msg_idx)


inject_css()

if "history" not in st.session_state:
    st.session_state.history = []
if "audio_cache" not in st.session_state:
    st.session_state["audio_cache"] = {}
if "audio_listen_cache" not in st.session_state:
    st.session_state["audio_listen_cache"] = {}
if "audio_explain_cache" not in st.session_state:
    st.session_state["audio_explain_cache"] = {}
if "explain_cache" not in st.session_state:
    st.session_state["explain_cache"] = {}
if "audio_prefetch_done" not in st.session_state:
    st.session_state["audio_prefetch_done"] = {}
if "_autoplay_audio_msg" not in st.session_state:
    st.session_state["_autoplay_audio_msg"] = ""
if "_audio_mode" not in st.session_state:
    st.session_state["_audio_mode"] = {}
if "audio_error" not in st.session_state:
    st.session_state["audio_error"] = ""

st.markdown(
    """
    <div class="hero-wrap">
        <h1 class="hero-title">âš–ï¸ Ratio - Pesquisa Jurisprudencial</h1>
        <p class="hero-subtitle">
            Busca semÃ¢ntica avanÃ§ada sobre acervo jurÃ­dico com resposta fundamentada e citaÃ§Ãµes verificadas.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.header("Filtros de pesquisa")

scope_all = st.sidebar.toggle(
    "Pesquisar em toda a base",
    value=True,
    help="Quando ativo, nÃ£o aplica pre-filtro por tribunal/tipo e considera todo o banco vetorial.",
)

st.sidebar.subheader("Tribunal")
col1, col2 = st.sidebar.columns(2)
with col1:
    stf = st.checkbox("STF", value=True, disabled=scope_all)
with col2:
    stj = st.checkbox("STJ", value=True, disabled=scope_all)

tribunais = []
if stf:
    tribunais.append("STF")
if stj:
    tribunais.append("STJ")

st.sidebar.subheader("Tipo de documento")
acordao = st.sidebar.checkbox("AcÃ³rdÃ£os", value=True, disabled=scope_all)
sumula = st.sidebar.checkbox("SÃºmulas", value=True, disabled=scope_all)
sumula_vinculante = st.sidebar.checkbox("SÃºmulas Vinculantes", value=True, disabled=scope_all)
informativo = st.sidebar.checkbox("Informativos", value=True, disabled=scope_all)
tema_repetitivo_stj = st.sidebar.checkbox("Temas Repetitivos STJ", value=True, disabled=scope_all)
monocratica = st.sidebar.checkbox("DecisÃ£o MonocrÃ¡tica", value=True, disabled=scope_all)

tipos = []
if acordao:
    tipos.extend(["acordao", "acordao_sv"])
if sumula:
    tipos.extend(["sumula", "sumula_stj"])
if sumula_vinculante:
    tipos.append("sumula_vinculante")
if informativo:
    tipos.append("informativo")
if tema_repetitivo_stj:
    tipos.append("tema_repetitivo_stj")
if monocratica:
    tipos.extend(["monocratica", "monocratica_sv"])

st.sidebar.markdown("---")
st.sidebar.subheader("Filtros avanÃ§ados")
ramos = st.sidebar.multiselect(
    "Ramo do Direito",
    options=[
        "Constitucional",
        "Administrativo",
        "Civil",
        "Processual Civil",
        "Penal",
        "Processual Penal",
        "TributÃ¡rio",
        "Trabalho",
        "PrevidenciÃ¡rio",
        "Consumidor",
        "Empresarial",
        "Internacional",
        "Ambiental",
        "Eleitoral",
    ],
    disabled=scope_all,
)
orgaos = st.sidebar.multiselect(
    "Ã“rgÃ£o Julgador",
    options=[
        "Tribunal Pleno",
        "PlenÃ¡rio",
        "Primeira Turma",
        "Segunda Turma",
        "Primeira SeÃ§Ã£o",
        "Segunda SeÃ§Ã£o",
        "Terceira SeÃ§Ã£o",
        "Terceira Turma",
        "Quarta Turma",
        "Quinta Turma",
        "Sexta Turma",
        "Corte Especial",
        "DecisÃ£o MonocrÃ¡tica",
    ],
    disabled=scope_all,
)
relator_contains = st.sidebar.text_input("Relator contÃ©m", disabled=scope_all).strip()
date_from = st.sidebar.text_input("Data inicial (YYYY-MM-DD)", disabled=scope_all).strip()
date_to = st.sidebar.text_input("Data final (YYYY-MM-DD)", disabled=scope_all).strip()

st.sidebar.markdown("---")
st.sidebar.subheader("ConfiguraÃ§Ãµes")
prefer_recent = st.sidebar.toggle("Priorizar jurisprudÃªncia recente", value=True)
r_default = "Gemini (maior precisÃ£o, maior custo)" if str(RERANKER_BACKEND).strip().lower() == "gemini" else "Local (baixo custo)"
reranker_mode = st.sidebar.selectbox(
    "Modo de reranker",
    options=[
        "Local (baixo custo)",
        "Gemini (maior precisÃ£o, maior custo)",
    ],
    index=0 if r_default.startswith("Local") else 1,
    help="Local reduz custo e latÃªncia. Gemini tende a maior precisÃ£o em casos difÃ­ceis.",
)
r_backend = "gemini" if reranker_mode.startswith("Gemini") else "local"
show_logs = st.sidebar.toggle("Mostrar logs tÃ©cnicos", value=False)

filter_config = {
    "tribunais": tribunais if not scope_all else None,
    "tipos": tipos if not scope_all else None,
    "ramos": ramos if not scope_all and ramos else None,
    "orgaos": orgaos if not scope_all and orgaos else None,
    "orgaos_query": expand_orgaos_selection(orgaos) if not scope_all and orgaos else None,
    "relator": relator_contains if not scope_all and relator_contains else None,
    "date_from": date_from if not scope_all and date_from else None,
    "date_to": date_to if not scope_all and date_to else None,
}

if (filter_config["date_from"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", filter_config["date_from"])) or (
    filter_config["date_to"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", filter_config["date_to"])
):
    st.sidebar.error("Datas devem seguir o formato YYYY-MM-DD.")

st.markdown(build_active_filter_chips(scope_all, filter_config), unsafe_allow_html=True)

for idx, msg in enumerate(st.session_state.history):
    if msg["role"] == "user":
        st.chat_message("user").write(msg["content"])
    else:
        render_assistant_message(msg, show_logs=show_logs, msg_idx=idx)

query = st.chat_input("FaÃ§a sua pergunta jurÃ­dica...")

if query:
    st.session_state.history.append({"role": "user", "content": query})
    st.chat_message("user").write(query)

    if not scope_all and (not tribunais or not tipos):
        st.error("Selecione pelo menos um Tribunal e um Tipo de documento, ou ative 'Pesquisar em toda a base'.")
    else:
        status_placeholder = st.empty()
        render_pipeline_status(status_placeholder, "embedding_start", {})

        def stage_callback(stage: str, payload: dict) -> None:
            timings = payload.get("timings", {}) if isinstance(payload, dict) else {}
            render_pipeline_status(status_placeholder, stage, timings)

        f = io.StringIO()
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            try:
                answer, top_docs, meta = run_query(
                    query=query,
                    tribunais=filter_config["tribunais"],
                    tipos=filter_config["tipos"],
                    prefer_recent=prefer_recent,
                    reranker_backend=r_backend,
                    ramos=filter_config["ramos"],
                    orgaos=filter_config["orgaos_query"],
                    relator_contains=filter_config["relator"],
                    date_from=filter_config["date_from"],
                    date_to=filter_config["date_to"],
                    stage_callback=stage_callback,
                    return_meta=True,
                )
            except Exception as exc:
                answer, top_docs, meta = None, [], {}
                st.error(f"Erro na pesquisa: {exc}")

        logs = f.getvalue()
        status_placeholder.empty()

        if answer:
            answer = repair_mojibake(answer)
            assistant_msg = {
                "role": "assistant",
                "question": query,
                "answer": answer,
                "top_docs": top_docs,
                "meta": meta,
                "logs": logs,
            }
            assistant_idx = len(st.session_state.history)
            st.session_state.history.append(assistant_msg)
            with st.spinner("PrÃ©-gerando Ã¡udio da resposta e explicaÃ§Ã£o..."):
                prefetch_audio_assets(assistant_msg, str(assistant_idx))
            render_assistant_message(assistant_msg, show_logs=show_logs, msg_idx=assistant_idx)



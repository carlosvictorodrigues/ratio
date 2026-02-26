"""
RAG Query Engine for STF/STJ jurisprudence.

Flow:
1. Embed user query with Gemini.
2. Retrieve candidates in LanceDB (vector + FTS hybrid).
3. Rerank with cross-encoder using a uniform score:
   semantic relevance + lexical overlap + recency.
4. Generate grounded answer with strict citation prompt.
5. Validate minimum citation contract.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import random
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Callable, Optional

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

import lancedb
from dotenv import load_dotenv
from google import genai
from google.genai import types
from sentence_transformers import CrossEncoder

def _resolve_project_root() -> Path:
    raw = (os.getenv("RATIO_PROJECT_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _resolve_project_root()
ENV_CANDIDATES = [
    PROJECT_ROOT / ".env",
    Path.cwd() / ".env",
    Path("D:/dev/.env"),
]

for env_path in ENV_CANDIDATES:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

GEMINI_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
_CLIENT: Optional[genai.Client] = None

SUPPORTED_GENERATION_MODELS: tuple[str, ...] = (
    "gemini-3-pro-preview",
    "gemini-3.1-pro",
    "gemini-3-pro",
    "gemini-3-flash-preview",
    "gemini-3-flash",
    "gemini-2.5-pro",
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)
GEMINI_KEY_VALIDATION_MODEL = os.getenv("GEMINI_KEY_VALIDATION_MODEL", "gemini-2.5-flash")
GEMINI_KEY_VALIDATION_TIMEOUT_MS = int(os.getenv("GEMINI_KEY_VALIDATION_TIMEOUT_MS", "12000"))


def get_supported_generation_models() -> list[str]:
    return list(SUPPORTED_GENERATION_MODELS)


def has_gemini_api_key() -> bool:
    return bool((GEMINI_KEY or "").strip())


def _reset_runtime_model_cache() -> None:
    global _AVAILABLE_MODELS_CACHE
    _RESOLVED_MODEL_CACHE.clear()
    _AVAILABLE_MODELS_CACHE = None


def get_gemini_client() -> genai.Client:
    global _CLIENT
    key = (GEMINI_KEY or "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY ausente. Configure a chave Gemini para usar embeddings e geracao."
        )
    if _CLIENT is None:
        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def configure_gemini_api_key(
    api_key: str,
    *,
    validate: bool = False,
    test_model: Optional[str] = None,
    validation_timeout_ms: int = GEMINI_KEY_VALIDATION_TIMEOUT_MS,
) -> dict[str, Any]:
    global GEMINI_KEY, _CLIENT
    key = str(api_key or "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY ausente. Informe uma chave valida.")

    probe_model = (test_model or GENERATION_MODEL or "gemini-3-flash-preview").strip()
    candidate = genai.Client(api_key=key)
    if validate:
        timeout_ms = max(3000, min(int(validation_timeout_ms or GEMINI_KEY_VALIDATION_TIMEOUT_MS), 120000))
        probe_candidates: list[str] = []
        for model_name in (probe_model, GEMINI_KEY_VALIDATION_MODEL, "gemini-2.5-flash"):
            value = (model_name or "").strip()
            if value and value not in probe_candidates:
                probe_candidates.append(value)

        last_error: Optional[Exception] = None
        validated_model = probe_model
        for model_name in probe_candidates:
            try:
                candidate.models.generate_content(
                    model=model_name,
                    contents="Responda somente: OK",
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        max_output_tokens=8,
                        http_options=types.HttpOptions(
                            timeout=timeout_ms,
                            # Keep onboarding responsive: avoid multi-retry bursts.
                            retry_options=types.HttpRetryOptions(attempts=1),
                        ),
                    ),
                )
                validated_model = model_name
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                norm = str(exc).lower()
                model_not_available = "model" in norm and (
                    "not found" in norm or "unsupported" in norm or "not available" in norm
                )
                if model_not_available:
                    continue
                raise
        if last_error is not None:
            raise last_error
        probe_model = validated_model

    GEMINI_KEY = key
    os.environ["GEMINI_API_KEY"] = key
    _CLIENT = candidate
    _reset_runtime_model_cache()
    return {
        "validated": bool(validate),
        "model": probe_model,
    }

LANCE_DIR = PROJECT_ROOT / "lancedb_store"
USER_ACERVO_TABLE = os.getenv("USER_ACERVO_TABLE", "meu_acervo")
USER_ACERVO_MANIFEST = PROJECT_ROOT / "logs" / "runtime" / "meu_acervo_manifest.json"
EMBED_DIM = 768

# Retrieval limits
TOPK_HYBRID = int(os.getenv("TOPK_HYBRID", "80"))
TOPK_RERANK = int(os.getenv("TOPK_RERANK", "11"))
HYBRID_RRF_K = int(os.getenv("HYBRID_RRF_K", "60"))

# Uniform ranking weights
SEMANTIC_WEIGHT = float(os.getenv("SEMANTIC_WEIGHT", "0.45"))
LEXICAL_WEIGHT = float(os.getenv("LEXICAL_WEIGHT", "0.20"))
RECENCY_WEIGHT = float(os.getenv("RECENCY_WEIGHT", "0.35"))
RECENCY_HALFLIFE_YEARS = float(os.getenv("RECENCY_HALFLIFE_YEARS", "7.0"))
RECENCY_INTENT_MULTIPLIER = float(os.getenv("RECENCY_INTENT_MULTIPLIER", "1.35"))
RECENCY_DOMINANT_MULTIPLIER = float(os.getenv("RECENCY_DOMINANT_MULTIPLIER", "0.45"))
RECENCY_MIN_SEMANTIC_GATE = float(os.getenv("RECENCY_MIN_SEMANTIC_GATE", "0.60"))
RECENCY_MAX_CONTRIBUTION = float(os.getenv("RECENCY_MAX_CONTRIBUTION", "0.14"))
RECENCY_UNKNOWN_SCORE = float(os.getenv("RECENCY_UNKNOWN_SCORE", "0.05"))
THESIS_BONUS_WEIGHT = float(os.getenv("THESIS_BONUS_WEIGHT", "0.16"))
PROCEDURAL_PENALTY_WEIGHT = float(os.getenv("PROCEDURAL_PENALTY_WEIGHT", "0.14"))
PROCEDURAL_INTENT_PENALTY_MULTIPLIER = float(os.getenv("PROCEDURAL_INTENT_PENALTY_MULTIPLIER", "0.30"))
AUTHORITY_BONUS_WEIGHT = float(os.getenv("AUTHORITY_BONUS_WEIGHT", "0.22"))
AUTHORITY_INTENT_MULTIPLIER = float(os.getenv("AUTHORITY_INTENT_MULTIPLIER", "1.20"))
AUTHORITY_A_LEVEL_BOOST = float(os.getenv("AUTHORITY_A_LEVEL_BOOST", "0.14"))
AUTHORITY_B_LEVEL_BOOST = float(os.getenv("AUTHORITY_B_LEVEL_BOOST", "0.08"))
AUTHORITY_C_LEVEL_BOOST = float(os.getenv("AUTHORITY_C_LEVEL_BOOST", "0.03"))
AUTHORITY_D_LEVEL_BOOST = float(os.getenv("AUTHORITY_D_LEVEL_BOOST", "-0.05"))
AUTHORITY_E_LEVEL_BOOST = float(os.getenv("AUTHORITY_E_LEVEL_BOOST", "-0.12"))
COLLEGIAL_BINDING_BONUS = float(os.getenv("COLLEGIAL_BINDING_BONUS", "0.06"))
MONOCRATIC_BINDING_PENALTY = float(os.getenv("MONOCRATIC_BINDING_PENALTY", "0.12"))
USER_SOURCE_PRIORITY_BOOST = float(os.getenv("USER_SOURCE_PRIORITY_BOOST", "0.08"))
EXPLAIN_MODEL = os.getenv("EXPLAIN_MODEL", "gemini-3-pro-preview")
EXPLAIN_DOCS_LIMIT = int(os.getenv("EXPLAIN_DOCS_LIMIT", "4"))
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "gemini-3-flash-preview")
GENERATION_FALLBACK_MODEL = os.getenv("GENERATION_FALLBACK_MODEL", "gemini-2.5-flash")
GENERATION_MAX_OUTPUT_TOKENS = int(os.getenv("GENERATION_MAX_OUTPUT_TOKENS", "3600"))
GENERATION_THINKING_BUDGET = int(os.getenv("GENERATION_THINKING_BUDGET", "128"))
PARAGRAPH_CITATION_MIN_CHARS = int(os.getenv("PARAGRAPH_CITATION_MIN_CHARS", "120"))
PREFER_RECENT_DEFAULT = os.getenv("PREFER_RECENT_DEFAULT", "1").strip() != "0"
CONTEXT_MAX_PASSAGES_PER_DOC = int(os.getenv("CONTEXT_MAX_PASSAGES_PER_DOC", "5"))
CONTEXT_MAX_PASSAGE_CHARS = int(os.getenv("CONTEXT_MAX_PASSAGE_CHARS", "1000"))
CONTEXT_MAX_DOC_CHARS = int(os.getenv("CONTEXT_MAX_DOC_CHARS", "2500"))

RERANKER_BACKEND = os.getenv("RERANKER_BACKEND", "local").strip().lower()
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
GEMINI_RERANK_MODEL = os.getenv("GEMINI_RERANK_MODEL", "gemini-3-pro-preview")
GEMINI_RERANK_BATCH_SIZE = int(os.getenv("GEMINI_RERANK_BATCH_SIZE", "8"))
GEMINI_RERANK_EXCERPT_CHARS = int(os.getenv("GEMINI_RERANK_EXCERPT_CHARS", "1600"))
GEMINI_RERANK_PASSES = int(os.getenv("GEMINI_RERANK_PASSES", "2"))
GEMINI_RERANK_REFINE_TOP = int(os.getenv("GEMINI_RERANK_REFINE_TOP", "24"))
GEMINI_RERANK_REFINE_WEIGHT = float(os.getenv("GEMINI_RERANK_REFINE_WEIGHT", "0.70"))
GEMINI_RERANK_MAX_WORKERS = int(os.getenv("GEMINI_RERANK_MAX_WORKERS", "15"))
GEMINI_RERANK_MAX_RETRIES = int(os.getenv("GEMINI_RERANK_MAX_RETRIES", "5"))
GEMINI_RERANK_RETRY_BASE_SECONDS = float(os.getenv("GEMINI_RERANK_RETRY_BASE_SECONDS", "1.5"))
GEMINI_RERANK_RETRY_MAX_SECONDS = float(os.getenv("GEMINI_RERANK_RETRY_MAX_SECONDS", "20.0"))
RERANK_DEDUP_PROCESS = os.getenv("RERANK_DEDUP_PROCESS", "1").strip() != "0"
_RERANKER: Optional[CrossEncoder] = None
_RESOLVED_MODEL_CACHE: dict[str, str] = {}
_AVAILABLE_MODELS_CACHE: Optional[set[str]] = None

StageCallback = Optional[Callable[[str, dict], None]]
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
TODAY = date.today()
TYPE_LABELS = {
    "acordao": "Acórdão",
    "acordao_sv": "Acórdão (SV)",
    "sumula": "Súmula",
    "sumula_stj": "Súmula STJ",
    "sumula_vinculante": "Súmula Vinculante",
    "informativo": "Informativo",
    "monocratica": "Decisão Monocrática",
    "monocratica_sv": "Decisão Monocrática (SV)",
    "tema_repetitivo_stj": "Tema Repetitivo STJ",
    "acervo_usuario": "Documento do Meu Acervo",
}

THESIS_SIGNAL_TERMS = (
    "tese",
    "tema",
    "repercussao geral",
    "repercussão geral",
    "fixa-se",
    "fixou-se",
    "fixou entendimento",
    "firmou entendimento",
    "assentou",
    "vinculante",
)

PROCEDURAL_SIGNAL_TERMS = (
    "sumula 279",
    "súmula 279",
    "ofensa reflexa",
    "reexame de fatos",
    "reexame do conjunto fatico",
    "inadmiss",
    "não conhecimento",
    "nao conhecimento",
    "legislação infraconstitucional",
    "legislacao infraconstitucional",
    "pressupostos recursais",
)

PROCEDURAL_INTENT_TERMS = (
    "admissibilidade",
    "pressuposto recursal",
    "sumula 279",
    "súmula 279",
    "ofensa reflexa",
    "recurso extraordinario",
    "recurso extraordinário",
    "agravo interno",
    "agravo regimental",
)

BINDING_INTENT_TERMS = (
    "vinculante",
    "obrigatorio",
    "obrigatoria",
    "precedente",
    "art 927",
    "cpc 927",
    "tema repetitivo",
    "repercussao geral",
    "controle concentrado",
    "sumula vinculante",
)

DOMINANT_INTENT_TERMS = (
    "jurisprudencia dominante",
    "entendimento dominante",
    "jurisprudencia consolidada",
    "consolidado",
    "pacifico",
    "pacificada",
    "pacificado",
    "majoritario",
    "majoritaria",
    "precedente dominante",
)

LEGAL_STOP_TOKENS = {
    "art",
    "arts",
    "lei",
    "leis",
    "tema",
    "stf",
    "stj",
    "cpc",
    "cpp",
    "cf",
    "tribunal",
    "jurisprudencia",
    "processo",
    "sumula",
    "sumulas",
    "acordao",
    "acordaos",
    "decisao",
    "decisoes",
    "recurso",
    "direito",
}

AUTHORITY_LEVEL_LABELS = {
    "A": "Vinculante forte",
    "B": "Precedente qualificado (tese/tema)",
    "C": "Observancia qualificada",
    "D": "Nao vinculante (orientativo)",
    "E": "Editorial/consulta",
}

# Runtime-tunable parameters exposed to the UI.
RAG_TUNING_DEFAULTS: dict[str, Any] = {
    # Retrieval
    "topk_hybrid": TOPK_HYBRID,
    "topk_rerank": TOPK_RERANK,
    "hybrid_rrf_k": HYBRID_RRF_K,
    # Ranking weights
    "semantic_weight": SEMANTIC_WEIGHT,
    "lexical_weight": LEXICAL_WEIGHT,
    "recency_weight": RECENCY_WEIGHT,
    "rrf_weight": 0.08,
    "thesis_bonus_weight": THESIS_BONUS_WEIGHT,
    "procedural_penalty_weight": PROCEDURAL_PENALTY_WEIGHT,
    "authority_bonus_weight": AUTHORITY_BONUS_WEIGHT,
    "authority_intent_multiplier": AUTHORITY_INTENT_MULTIPLIER,
    "procedural_intent_penalty_multiplier": PROCEDURAL_INTENT_PENALTY_MULTIPLIER,
    "user_source_priority_boost": USER_SOURCE_PRIORITY_BOOST,
    # Recency behavior
    "recency_half_life_years": RECENCY_HALFLIFE_YEARS,
    "recency_intent_multiplier": RECENCY_INTENT_MULTIPLIER,
    "recency_dominant_multiplier": RECENCY_DOMINANT_MULTIPLIER,
    "recency_min_semantic_gate": RECENCY_MIN_SEMANTIC_GATE,
    "recency_max_contribution": RECENCY_MAX_CONTRIBUTION,
    "recency_unknown_score": RECENCY_UNKNOWN_SCORE,
    # Authority bonuses by level
    "authority_level_a_boost": AUTHORITY_A_LEVEL_BOOST,
    "authority_level_b_boost": AUTHORITY_B_LEVEL_BOOST,
    "authority_level_c_boost": AUTHORITY_C_LEVEL_BOOST,
    "authority_level_d_boost": AUTHORITY_D_LEVEL_BOOST,
    "authority_level_e_boost": AUTHORITY_E_LEVEL_BOOST,
    "collegial_binding_bonus": COLLEGIAL_BINDING_BONUS,
    "monocratic_binding_penalty": MONOCRATIC_BINDING_PENALTY,
    # Context assembly
    "context_max_passages_per_doc": CONTEXT_MAX_PASSAGES_PER_DOC,
    "context_max_passage_chars": CONTEXT_MAX_PASSAGE_CHARS,
    "context_max_doc_chars": CONTEXT_MAX_DOC_CHARS,
    # Validation strictness
    "paragraph_citation_min_chars": PARAGRAPH_CITATION_MIN_CHARS,
    "rerank_dedup_process": RERANK_DEDUP_PROCESS,
    # Generation model controls
    "generation_model": GENERATION_MODEL,
    "generation_fallback_model": GENERATION_FALLBACK_MODEL,
    "gemini_rerank_model": GEMINI_RERANK_MODEL,
    "generation_temperature": 0.1,
    "generation_max_output_tokens": GENERATION_MAX_OUTPUT_TOKENS,
    "generation_thinking_budget": GENERATION_THINKING_BUDGET,
}

_RAG_TUNING_NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
    "topk_hybrid": (10.0, 400.0),
    "topk_rerank": (2.0, 80.0),
    "hybrid_rrf_k": (10.0, 400.0),
    "semantic_weight": (0.0, 2.0),
    "lexical_weight": (0.0, 2.0),
    "recency_weight": (0.0, 2.0),
    "rrf_weight": (0.0, 1.0),
    "thesis_bonus_weight": (0.0, 1.0),
    "procedural_penalty_weight": (0.0, 1.0),
    "authority_bonus_weight": (0.0, 1.5),
    "authority_intent_multiplier": (0.0, 3.0),
    "procedural_intent_penalty_multiplier": (0.0, 2.0),
    "user_source_priority_boost": (0.0, 0.8),
    "recency_half_life_years": (0.5, 30.0),
    "recency_intent_multiplier": (0.0, 3.0),
    "recency_dominant_multiplier": (0.0, 2.0),
    "recency_min_semantic_gate": (0.0, 1.0),
    "recency_max_contribution": (0.0, 1.0),
    "recency_unknown_score": (0.0, 1.0),
    "authority_level_a_boost": (-0.5, 0.8),
    "authority_level_b_boost": (-0.5, 0.8),
    "authority_level_c_boost": (-0.5, 0.8),
    "authority_level_d_boost": (-0.5, 0.8),
    "authority_level_e_boost": (-0.5, 0.8),
    "collegial_binding_bonus": (-0.5, 0.8),
    "monocratic_binding_penalty": (-0.5, 0.8),
    "context_max_passages_per_doc": (1.0, 8.0),
    "context_max_passage_chars": (200.0, 2500.0),
    "context_max_doc_chars": (600.0, 6000.0),
    "paragraph_citation_min_chars": (40.0, 500.0),
    "generation_temperature": (0.0, 1.0),
    "generation_max_output_tokens": (300.0, 12000.0),
    "generation_thinking_budget": (0.0, 8192.0),
}

_RAG_TUNING_INT_KEYS = {
    "topk_hybrid",
    "topk_rerank",
    "hybrid_rrf_k",
    "context_max_passages_per_doc",
    "context_max_passage_chars",
    "context_max_doc_chars",
    "paragraph_citation_min_chars",
    "generation_max_output_tokens",
    "generation_thinking_budget",
}

_RAG_TUNING_BOOL_KEYS = {
    "rerank_dedup_process",
}

_RAG_TUNING_STRING_KEYS = {
    "generation_model",
    "generation_fallback_model",
    "gemini_rerank_model",
}


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"1", "true", "yes", "sim", "on"}:
            return True
        if norm in {"0", "false", "no", "nao", "off"}:
            return False
    return default


def get_rag_tuning_defaults() -> dict[str, Any]:
    return dict(RAG_TUNING_DEFAULTS)


def resolve_rag_tuning(overrides: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = dict(RAG_TUNING_DEFAULTS)
    if not overrides:
        return cfg
    if not isinstance(overrides, dict):
        return cfg

    for key, value in overrides.items():
        if key not in cfg:
            continue
        default = cfg[key]
        if key in _RAG_TUNING_BOOL_KEYS:
            cfg[key] = _as_bool(value, bool(default))
            continue
        if key in _RAG_TUNING_STRING_KEYS:
            txt = str(value or "").strip()
            if txt:
                cfg[key] = txt
            continue

        low, high = _RAG_TUNING_NUMERIC_BOUNDS.get(key, (-1e9, 1e9))
        if key in _RAG_TUNING_INT_KEYS:
            parsed = _as_int(value, int(default))
            cfg[key] = int(_clip(float(parsed), low, high))
        else:
            parsed = _as_float(value, float(default))
            cfg[key] = float(_clip(parsed, low, high))

    # Keep rerank <= hybrid to avoid empty cuts.
    if cfg["topk_rerank"] > cfg["topk_hybrid"]:
        cfg["topk_rerank"] = int(cfg["topk_hybrid"])

    return cfg


def get_rag_tuning_schema() -> list[dict[str, Any]]:
    """UI metadata for advanced runtime-tunable RAG controls."""
    return [
        {
            "key": "topk_hybrid",
            "label": "Candidatos Hibridos (top-k)",
            "group": "Busca e Ranking",
            "type": "int",
            "min": 10,
            "max": 400,
            "step": 1,
            "impact_more": "Aumenta cobertura da busca, com maior custo e latencia.",
            "impact_less": "Responde mais rapido, mas pode perder precedentes relevantes.",
        },
        {
            "key": "topk_rerank",
            "label": "Documentos Finais (top-k rerank)",
            "group": "Busca e Ranking",
            "type": "int",
            "min": 2,
            "max": 80,
            "step": 1,
            "impact_more": "Inclui mais fontes na resposta final.",
            "impact_less": "Resposta mais focada, com menos diversidade de fontes.",
        },
        {
            "key": "gemini_rerank_model",
            "label": "Modelo do Reranker Gemini",
            "group": "Busca e Ranking",
            "type": "string",
            "options": get_supported_generation_models(),
            "help": "Usado apenas quando o reranker da consulta estiver em modo Gemini.",
            "impact_more": "Modelos mais robustos melhoram qualidade do rerank, com maior custo e latencia.",
            "impact_less": "Modelos mais leves reduzem custo e tempo, com possivel queda de qualidade.",
        },
        {
            "key": "semantic_weight",
            "label": "Peso Semantico",
            "group": "Pesos de Relevancia",
            "type": "float",
            "min": 0,
            "max": 2,
            "step": 0.01,
            "impact_more": "Prioriza similaridade de sentido entre pergunta e documento.",
            "impact_less": "Reduz dependencia do embedding semantico.",
        },
        {
            "key": "lexical_weight",
            "label": "Peso Lexical",
            "group": "Pesos de Relevancia",
            "type": "float",
            "min": 0,
            "max": 2,
            "step": 0.01,
            "impact_more": "Prioriza coincidencia literal de termos.",
            "impact_less": "Tolera mais sinonimos/variacoes de redacao.",
        },
        {
            "key": "recency_weight",
            "label": "Peso de Recencia",
            "group": "Pesos de Relevancia",
            "type": "float",
            "min": 0,
            "max": 2,
            "step": 0.01,
            "impact_more": "Favorece decisoes recentes.",
            "impact_less": "Diminui vies temporal, mantendo precedentes antigos.",
        },
        {
            "key": "authority_bonus_weight",
            "label": "Peso de Hierarquia da Fonte",
            "group": "Pesos de Relevancia",
            "type": "float",
            "min": 0,
            "max": 1.5,
            "step": 0.01,
            "impact_more": "Premia documentos com maior forca normativa.",
            "impact_less": "Equilibra melhor com fontes apenas persuasivas.",
        },
        {
            "key": "thesis_bonus_weight",
            "label": "Bonus de Tese Material",
            "group": "Pesos de Relevancia",
            "type": "float",
            "min": 0,
            "max": 1,
            "step": 0.01,
            "impact_more": "Aumenta foco em documentos com enunciado de tese.",
            "impact_less": "Reduz vantagem de documentos explicitamente teseados.",
        },
        {
            "key": "user_source_priority_boost",
            "label": "Bonus de Prioridade do Meu Acervo",
            "group": "Pesos de Relevancia",
            "type": "float",
            "min": 0,
            "max": 0.8,
            "step": 0.01,
            "help": "Aplicado quando a opcao de priorizar documentos do usuario estiver habilitada.",
            "impact_more": "Traz mais documentos do Meu Acervo para o topo quando relevantes.",
            "impact_less": "Deixa o ranking mais neutro entre base Ratio e base do usuario.",
        },
        {
            "key": "procedural_penalty_weight",
            "label": "Penalidade Processual",
            "group": "Pesos de Relevancia",
            "type": "float",
            "min": 0,
            "max": 1,
            "step": 0.01,
            "impact_more": "Filtra melhor textos de obice processual.",
            "impact_less": "Permite mais documentos processuais no topo.",
        },
        {
            "key": "authority_level_a_boost",
            "label": "Bonus Fonte Nivel A",
            "group": "Fontes A-E",
            "type": "float",
            "min": -0.5,
            "max": 0.8,
            "step": 0.01,
            "help": "Nivel A: fontes vinculantes fortes (sumula vinculante e controle concentrado do STF).",
            "impact_more": "Aumenta prioridade de fontes vinculantes fortes.",
            "impact_less": "Diminui dominancia de Nivel A no ranking.",
        },
        {
            "key": "authority_level_b_boost",
            "label": "Bonus Fonte Nivel B",
            "group": "Fontes A-E",
            "type": "float",
            "min": -0.5,
            "max": 0.8,
            "step": 0.01,
            "help": "Nivel B: precedentes qualificados (tema de repercussao geral, tema repetitivo, IRDR, IAC).",
            "impact_more": "Aumenta peso de precedentes qualificados.",
            "impact_less": "Reduz peso relativo de Nivel B.",
        },
        {
            "key": "authority_level_c_boost",
            "label": "Bonus Fonte Nivel C",
            "group": "Fontes A-E",
            "type": "float",
            "min": -0.5,
            "max": 0.8,
            "step": 0.01,
            "help": "Nivel C: sumulas de observancia qualificada (STF/STJ).",
            "impact_more": "Aumenta presenca de fontes de observancia qualificada.",
            "impact_less": "Diminui prioridade de Nivel C.",
        },
        {
            "key": "authority_level_d_boost",
            "label": "Bonus Fonte Nivel D",
            "group": "Fontes A-E",
            "type": "float",
            "min": -0.5,
            "max": 0.8,
            "step": 0.01,
            "help": "Nivel D: acordaos nao vinculantes e decisoes monocraticas (orientativos).",
            "impact_more": "Traz mais fontes nao vinculantes orientativas.",
            "impact_less": "Aumenta seletividade contra fontes orientativas.",
        },
        {
            "key": "authority_level_e_boost",
            "label": "Bonus Fonte Nivel E",
            "group": "Fontes A-E",
            "type": "float",
            "min": -0.5,
            "max": 0.8,
            "step": 0.01,
            "help": "Nivel E: material editorial e compilacoes (informativos e correlatos).",
            "impact_more": "Aumenta participacao de material editorial.",
            "impact_less": "Reduz fontes editoriais no topo.",
        },
        {
            "key": "context_max_passages_per_doc",
            "label": "Passagens por Documento",
            "group": "Contexto da Resposta",
            "type": "int",
            "min": 1,
            "max": 8,
            "step": 1,
            "impact_more": "Fornece mais evidencias por documento ao modelo.",
            "impact_less": "Contexto mais conciso, menor custo e latencia.",
        },
        {
            "key": "context_max_passage_chars",
            "label": "Tamanho Max da Passagem",
            "group": "Contexto da Resposta",
            "type": "int",
            "min": 200,
            "max": 2500,
            "step": 10,
            "impact_more": "Aumenta detalhe textual de cada trecho.",
            "impact_less": "Trechos mais curtos e objetivos.",
        },
        {
            "key": "context_max_doc_chars",
            "label": "Chars Max por Documento",
            "group": "Contexto da Resposta",
            "type": "int",
            "min": 600,
            "max": 6000,
            "step": 50,
            "impact_more": "Permite contexto mais completo por fonte.",
            "impact_less": "Reduz comprimento de contexto e custo.",
        },
        {
            "key": "generation_temperature",
            "label": "Temperatura da Resposta",
            "group": "Modelo de Resposta",
            "type": "float",
            "min": 0,
            "max": 1,
            "step": 0.01,
            "impact_more": "Resposta mais variada e criativa.",
            "impact_less": "Resposta mais deterministica e conservadora.",
        },
        {
            "key": "generation_max_output_tokens",
            "label": "Tokens Max da Resposta",
            "group": "Modelo de Resposta",
            "type": "int",
            "min": 300,
            "max": 12000,
            "step": 50,
            "impact_more": "Permite respostas mais longas e detalhadas.",
            "impact_less": "Respostas mais curtas, com menor custo e latencia.",
        },
        {
            "key": "generation_thinking_budget",
            "label": "Orcamento de Raciocinio (Thinking)",
            "group": "Modelo de Resposta",
            "type": "int",
            "min": 0,
            "max": 8192,
            "step": 32,
            "help": "Controla quantos tokens o modelo pode gastar em raciocinio interno antes de emitir o texto final. Use 0 para manter o padrao do modelo.",
            "impact_more": "Aumenta profundidade de raciocinio, mas pode reduzir texto visivel dentro do mesmo limite de tokens.",
            "impact_less": "Prioriza resposta visivel e reduz risco de corte por MAX_TOKENS.",
        },
        {
            "key": "generation_model",
            "label": "Modelo Principal de Resposta",
            "group": "Modelo de Resposta",
            "type": "string",
            "options": get_supported_generation_models(),
            "help": "Modelo Gemini principal usado para redigir a sintese final.",
            "impact_more": "Modelos mais robustos tendem a melhorar qualidade, com maior custo/latencia.",
            "impact_less": "Modelos mais leves reduzem custo e tempo, com possivel perda de profundidade.",
        },
        {
            "key": "generation_fallback_model",
            "label": "Modelo Fallback de Resposta",
            "group": "Modelo de Resposta",
            "type": "string",
            "options": get_supported_generation_models(),
            "help": "Modelo alternativo usado quando o principal falha por cota, indisponibilidade ou erro.",
            "impact_more": "Define contingencia quando o principal falha.",
            "impact_less": "Sem fallback aumenta risco de erro em indisponibilidade.",
        },
        {
            "key": "paragraph_citation_min_chars",
            "label": "Limiar de Auditoria de Citacao",
            "group": "Validacao",
            "type": "int",
            "min": 40,
            "max": 500,
            "step": 5,
            "impact_more": "Auditoria ignora paragrafos menores.",
            "impact_less": "Auditoria exige citacao em paragrafos mais curtos.",
        },
        {
            "key": "rerank_dedup_process",
            "label": "Deduplicar Processos no Rerank",
            "group": "Validacao",
            "type": "bool",
            "impact_more": "Ativado: evita repeticao de casos semelhantes.",
            "impact_less": "Desativado: pode repetir variantes do mesmo processo.",
        },
    ]


def _emit_stage(stage_callback: StageCallback, stage: str, **payload) -> None:
    if not stage_callback:
        return
    try:
        stage_callback(stage, payload)
    except Exception:
        # Stage callback is UI-only; never break core query flow.
        pass


def type_label(tipo: str) -> str:
    if not tipo:
        return "Documento"
    return TYPE_LABELS.get(tipo, tipo.replace("_", " ").title())


def orgao_label(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return "Indefinido"
    if "monocr" in value.lower():
        return "Decisão Monocrática"
    return value


def clean_retrieved_text(raw: str) -> str:
    text = html.unescape((raw or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h\d|section|article)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def keyword_density(text: str, terms: tuple[str, ...], saturation_hits: float = 4.0) -> float:
    base = normalize_text(text)
    if not base:
        return 0.0
    hits = 0.0
    for term in terms:
        t = normalize_text(term)
        if t and t in base:
            hits += 1.0
    return min(hits / max(saturation_hits, 1.0), 1.0)


def infer_document_role(thesis_signal: float, procedural_signal: float) -> str:
    if thesis_signal >= 0.35 and thesis_signal >= (procedural_signal + 0.08):
        return "tese_material"
    if procedural_signal >= 0.35 and procedural_signal > thesis_signal:
        return "barreira_processual"
    return "aplicacao"


def role_label(role: str) -> str:
    if role == "tese_material":
        return "Tese material"
    if role == "barreira_processual":
        return "Barreira processual"
    return "Aplicação/caso"


def get_reranker() -> CrossEncoder:
    global _RERANKER
    if _RERANKER is None:
        print("Loading reranker model...", file=sys.stderr)
        _RERANKER = CrossEncoder(RERANKER_MODEL, max_length=512)
        print("Reranker ready.", file=sys.stderr)
    return _RERANKER


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(normalize_text(text))


def lexical_overlap_score(query: str, doc_text: str) -> float:
    query_tokens = [t for t in normalize_tokens(query) if t not in LEGAL_STOP_TOKENS]
    if not query_tokens:
        query_tokens = normalize_tokens(query)
    if not query_tokens:
        return 0.0

    query_set = set(query_tokens)
    doc_set = set(normalize_tokens(doc_text))
    if not doc_set:
        return 0.0
    hits = len(query_set.intersection(doc_set))
    return hits / len(query_set)


def has_recency_intent(query: str) -> bool:
    q = normalize_text(query)
    terms = (
        "mais recente",
        "recente",
        "ultim",
        "atual",
        "novo",
        "ultima",
        "ultimas",
        "recentes",
    )
    return any(term in q for term in terms)


def has_dominant_intent(query: str) -> bool:
    q = normalize_text(query)
    return any(term in q for term in DOMINANT_INTENT_TERMS)


def has_procedural_intent(query: str) -> bool:
    q = normalize_text(query)
    return any(term in q for term in PROCEDURAL_INTENT_TERMS)


def has_binding_intent(query: str) -> bool:
    q = normalize_text(query)
    return any(term in q for term in BINDING_INTENT_TERMS)


def _parse_metadata_extra(raw: str) -> dict:
    if not isinstance(raw, str):
        return {}
    value = raw.strip()
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_trueish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = normalize_text(str(value))
    return text in {"1", "true", "yes", "sim"}


def authority_label(level: str) -> str:
    return AUTHORITY_LEVEL_LABELS.get(level, AUTHORITY_LEVEL_LABELS["D"])


def classify_authority(row: dict) -> tuple[float, str, str]:
    tipo = (row.get("tipo") or "").strip().lower()
    tribunal = (row.get("tribunal") or "").strip().upper()
    orgao = normalize_text(row.get("orgao_julgador", ""))
    processo = normalize_text(row.get("processo", ""))
    busca = clean_retrieved_text(row.get("texto_busca", "") or "")
    integral = clean_retrieved_text(row.get("texto_integral", "") or "")
    doc_text = normalize_text(f"{busca}\n{integral[:3000]}")
    corpus = f"{processo}\n{doc_text}"
    meta = _parse_metadata_extra(row.get("metadata_extra", ""))

    if tipo == "sumula_vinculante":
        return 1.00, "A", "Sumula vinculante do STF."

    if tribunal == "STF" and tipo in {"acordao", "acordao_sv"}:
        if re.search(r"\b(adi|adc|adpf)\b", corpus):
            return 0.97, "A", "Controle concentrado no STF."

    if tipo == "tema_repetitivo_stj":
        return 0.92, "B", "Tema repetitivo do STJ."

    if tipo in {"monocratica", "monocratica_sv"}:
        if "repercussao geral" in corpus or "tema " in corpus:
            return 0.56, "D", "Decisao monocratica que aplica tema; nao fixa tese obrigatoria."
        return 0.52, "D", "Decisao monocratica, util como indicio."

    if re.search(r"\b(irdr|iac)\b", corpus):
        return 0.90, "B", "Precedente qualificado (IRDR/IAC)."

    is_rg = _is_trueish(meta.get("is_repercussao_geral"))
    if tribunal == "STF" and tipo in {"acordao", "acordao_sv"} and (is_rg or "repercussao geral" in corpus):
        return 0.89, "B", "Acordao com tema de repercussao geral do STF."

    if tipo in {"sumula", "sumula_stj"}:
        return 0.78, "C", "Sumula de observancia qualificada."

    if tipo == "informativo" or "jurisprudencia em teses" in corpus:
        return 0.18, "E", "Informativo/compilacao editorial nao vinculante."

    if tipo in {"acordao", "acordao_sv"}:
        if "corte especial" in orgao or "plenario" in orgao or "tribunal pleno" in orgao:
            return 0.68, "D", "Acordao colegiado de referencia nao vinculante."
        return 0.64, "D", "Acordao colegiado nao vinculante."

    return 0.45, "D", "Forca nao vinculante padrao."


def parse_date(value: str) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None

    raw = raw.replace("/", "-")

    # Fast path for ISO timestamps.
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    formats = (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%d-%m-%YT%H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def compute_recency_score(
    date_value: str,
    *,
    recency_unknown_score: float = RECENCY_UNKNOWN_SCORE,
    recency_half_life_years: float = RECENCY_HALFLIFE_YEARS,
) -> tuple[float, Optional[float]]:
    parsed = parse_date(date_value)
    if parsed is None:
        return recency_unknown_score, None

    age_years = max((TODAY - parsed).days / 365.25, 0.0)
    recency = math.exp(-age_years / max(recency_half_life_years, 0.1))
    return recency, age_years


def min_max_scale(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if abs(high - low) < 1e-9:
        return [0.5 for _ in values]
    return [(v - low) / (high - low) for v in values]


def embed_query(query: str) -> list[float]:
    result = get_gemini_client().models.embed_content(
        model="gemini-embedding-001",
        contents=query,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBED_DIM,
        ),
    )
    return result.embeddings[0].values


def _quote_sql(value: str) -> str:
    return "'" + (value or "").replace("'", "''") + "'"


def _load_user_source_manifest() -> list[dict[str, Any]]:
    try:
        if not USER_ACERVO_MANIFEST.exists():
            return []
        payload = json.loads(USER_ACERVO_MANIFEST.read_text(encoding="utf-8"))
        sources = payload.get("sources")
        if not isinstance(sources, list):
            return []
        return [item for item in sources if isinstance(item, dict)]
    except Exception:
        return []


def _active_user_source_ids() -> list[str]:
    active: list[str] = []
    for src in _load_user_source_manifest():
        source_id = str(src.get("id") or "").strip()
        if not source_id.startswith("user:"):
            continue
        if src.get("deleted_at"):
            continue
        active.append(source_id)
    return active


def _resolve_query_sources(raw_sources: Optional[list[str]]) -> tuple[bool, list[str], list[str]]:
    values = [str(v or "").strip() for v in (raw_sources or []) if str(v or "").strip()]
    if not values:
        active_user = _active_user_source_ids()
        return True, active_user, ["ratio", *active_user]

    include_ratio = False
    user_ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value == "ratio":
            include_ratio = True
            continue
        if not value.startswith("user:"):
            continue
        if value in seen:
            continue
        seen.add(value)
        user_ids.append(value)
    return include_ratio, user_ids, values


def _build_filter(
    tribunais: Optional[list[str]] = None,
    tipos: Optional[list[str]] = None,
    ramos: Optional[list[str]] = None,
    orgaos: Optional[list[str]] = None,
    relator_contains: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Optional[str]:
    clauses: list[str] = []

    if tribunais:
        clauses.append("tribunal IN (" + ", ".join(_quote_sql(t) for t in tribunais) + ")")
    if tipos:
        clauses.append("tipo IN (" + ", ".join(_quote_sql(t) for t in tipos) + ")")
    if ramos:
        clauses.append("ramo_direito IN (" + ", ".join(_quote_sql(r) for r in ramos) + ")")
    if orgaos:
        clauses.append("orgao_julgador IN (" + ", ".join(_quote_sql(o) for o in orgaos) + ")")
    if relator_contains:
        rel = relator_contains.strip().replace("'", "''")
        if rel:
            clauses.append(f"LOWER(relator) LIKE LOWER('%{rel}%')")
    if date_from:
        clauses.append(f"data_julgamento >= {_quote_sql(date_from)}")
    if date_to:
        clauses.append(f"data_julgamento <= {_quote_sql(date_to)}")

    return " AND ".join(clauses) if clauses else None


def _hybrid_key(row: dict, fallback_idx: int) -> str:
    doc_id = row.get("doc_id")
    if doc_id:
        return str(doc_id)
    tribunal = row.get("tribunal") or "-"
    tipo = row.get("tipo") or "-"
    processo = row.get("processo") or "-"
    return f"{tribunal}|{tipo}|{processo}|{fallback_idx}"


def _rrf(rank: Optional[int], k: int = HYBRID_RRF_K) -> float:
    if rank is None:
        return 0.0
    return 1.0 / (k + max(rank, 1))


def _table_hybrid_rows(
    tbl: Any,
    *,
    query: str,
    query_vector: list[float],
    top_k: int,
    hybrid_rrf_k: int,
    where_str: Optional[str],
) -> list[dict]:
    vec_q = tbl.search(query_vector).limit(top_k)
    if where_str:
        vec_q = vec_q.where(where_str, prefilter=True)
    vec_results = vec_q.to_list()

    try:
        fts_q = tbl.search(query, query_type="fts").limit(top_k)
        if where_str:
            fts_q = fts_q.where(where_str)
        fts_results = fts_q.to_list()
    except Exception as exc:
        print(f"FTS search warning: {exc}", file=sys.stderr)
        fts_results = []

    combined: dict[str, dict] = {}
    for rank, row in enumerate(vec_results, 1):
        key = _hybrid_key(row, rank)
        existing = combined.get(key, {}).copy()
        existing.update(row)
        existing["_rank_vec"] = rank
        combined[key] = existing

    for rank, row in enumerate(fts_results, 1):
        key = _hybrid_key(row, rank + len(vec_results))
        existing = combined.get(key, {}).copy()
        existing.update(row)
        existing["_rank_fts"] = rank
        combined[key] = existing

    fused: list[dict] = []
    for row in combined.values():
        rank_vec = row.get("_rank_vec")
        rank_fts = row.get("_rank_fts")
        row["_rrf_score"] = _rrf(rank_vec, k=hybrid_rrf_k) + _rrf(rank_fts, k=hybrid_rrf_k)
        row["_hybrid_hits"] = int(rank_vec is not None) + int(rank_fts is not None)
        fused.append(row)
    return fused


def search_lancedb(
    query: str,
    query_vector: list[float],
    top_k: int = TOPK_HYBRID,
    hybrid_rrf_k: int = HYBRID_RRF_K,
    sources: Optional[list[str]] = None,
    tribunais: Optional[list[str]] = None,
    tipos: Optional[list[str]] = None,
    ramos: Optional[list[str]] = None,
    orgaos: Optional[list[str]] = None,
    relator_contains: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    db = lancedb.connect(str(LANCE_DIR))
    include_ratio, user_ids, _resolved = _resolve_query_sources(sources)

    merged_rows: list[dict] = []

    if include_ratio:
        try:
            ratio_tbl = db.open_table("jurisprudencia")
            ratio_where = _build_filter(
                tribunais=tribunais,
                tipos=tipos,
                ramos=ramos,
                orgaos=orgaos,
                relator_contains=relator_contains,
                date_from=date_from,
                date_to=date_to,
            )
            ratio_rows = _table_hybrid_rows(
                ratio_tbl,
                query=query,
                query_vector=query_vector,
                top_k=top_k,
                hybrid_rrf_k=hybrid_rrf_k,
                where_str=ratio_where,
            )
            for row in ratio_rows:
                row.setdefault("source_id", "ratio")
                row.setdefault("source_label", "Base Ratio (STF/STJ)")
                row.setdefault("source_kind", "ratio")
            merged_rows.extend(ratio_rows)
        except Exception as exc:
            print(f"Ratio table warning: {exc}", file=sys.stderr)

    if user_ids:
        try:
            user_tbl = db.open_table(USER_ACERVO_TABLE)
            source_clause = "source_id IN (" + ", ".join(_quote_sql(sid) for sid in user_ids) + ")"
            user_rows = _table_hybrid_rows(
                user_tbl,
                query=query,
                query_vector=query_vector,
                top_k=top_k,
                hybrid_rrf_k=hybrid_rrf_k,
                where_str=source_clause,
            )
            for row in user_rows:
                row.setdefault("source_kind", "user")
                row.setdefault("source_id", row.get("source_id") or "user:desconhecido")
                row.setdefault("source_label", row.get("source_label") or "Meu Acervo")
            merged_rows.extend(user_rows)
        except Exception as exc:
            print(f"User table warning: {exc}", file=sys.stderr)

    merged_rows.sort(
        key=lambda x: (
            x.get("_rrf_score", 0.0),
            x.get("_hybrid_hits", 0),
            -(x.get("_rank_vec") or 10_000),
            -(x.get("_rank_fts") or 10_000),
        ),
        reverse=True,
    )
    return merged_rows


def _build_semantic_excerpt(row: dict, max_chars: int = GEMINI_RERANK_EXCERPT_CHARS) -> str:
    tipo = type_label(row.get("tipo", ""))
    processo = row.get("processo") or row.get("doc_id") or "-"
    tribunal = row.get("tribunal") or "-"
    dt = row.get("data_julgamento") or "-"
    authority_score, authority_level, authority_reason = classify_authority(row)
    busca = clean_retrieved_text(row.get("texto_busca", "") or "")
    integral = clean_retrieved_text(row.get("texto_integral", "") or "")
    header = (
        f"Tribunal: {tribunal}\n"
        f"Tipo: {tipo}\n"
        f"Processo: {processo}\n"
        f"Data: {dt}\n"
        f"Forca normativa inferida: Nivel {authority_level} ({authority_label(authority_level)}) | score={authority_score:.2f}\n"
        f"Motivo de hierarquia: {authority_reason}\n"
    )
    text = f"{header}\nResumo:\n{busca}\n\nTrecho:\n{integral}"
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _extract_json_array(raw: str) -> Optional[list]:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[[\s\S]*\]", value)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _fallback_semantic_score(query: str, row: dict) -> float:
    excerpt = _build_semantic_excerpt(row, max_chars=900)
    return _clip01(lexical_overlap_score(query, excerpt))


def _resolve_best_gemini_model(requested: str) -> str:
    requested_clean = (requested or "").strip()
    requested_norm = requested_clean.lower()
    cache_key = requested_norm or "best"
    cached = _RESOLVED_MODEL_CACHE.get(cache_key)
    if cached:
        return cached

    priorities = [
        "gemini-3-pro-preview",
        "gemini-3-pro",
        "gemini-3.1-pro",
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-3-flash",
        "gemini-2.5-pro",
        "gemini-2.5-pro-preview-05-06",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ]

    def available_models() -> set[str]:
        global _AVAILABLE_MODELS_CACHE
        if _AVAILABLE_MODELS_CACHE is not None:
            return _AVAILABLE_MODELS_CACHE
        available: set[str] = set()
        for model in get_gemini_client().models.list():
            name = getattr(model, "name", "") or ""
            if name.startswith("models/"):
                name = name.split("/", 1)[1]
            if name:
                available.add(name)
        _AVAILABLE_MODELS_CACHE = available
        return available

    def candidate_aliases(raw: str) -> list[str]:
        raw = (raw or "").strip()
        if not raw:
            return []
        norm = raw.lower()
        if norm == "gemini-3-pro-preview":
            aliases = [
                "gemini-3-pro-preview",
                "gemini-3-pro",
                "gemini-3.1-pro",
                "gemini-3.1-pro-preview",
                "gemini-2.5-pro",
            ]
        elif norm == "gemini-3.1-pro-preview":
            aliases = [
                "gemini-3-pro-preview",
                "gemini-3-pro",
                "gemini-3.1-pro",
                "gemini-3.1-pro-preview",
                "gemini-2.5-pro",
            ]
        elif norm == "gemini-3.1-pro":
            aliases = [
                "gemini-3-pro-preview",
                "gemini-3-pro",
                "gemini-3.1-pro",
                "gemini-3.1-pro-preview",
                "gemini-2.5-pro",
            ]
        elif norm == "gemini-3-pro":
            aliases = [
                "gemini-3-pro-preview",
                "gemini-3-pro",
                "gemini-3.1-pro",
                "gemini-3.1-pro-preview",
                "gemini-2.5-pro",
            ]
        elif norm == "gemini-3-flash-preview":
            aliases = [
                "gemini-3-flash-preview",
                "gemini-3-flash",
                "gemini-2.5-flash",
            ]
        elif norm == "gemini-3-flash":
            aliases = [
                "gemini-3-flash-preview",
                "gemini-3-flash",
                "gemini-2.5-flash",
            ]
        elif norm in {"auto", "best"}:
            aliases = priorities[:]
        else:
            aliases = [raw]
        return list(dict.fromkeys(aliases))

    try:
        available = available_models()
        candidates = candidate_aliases(requested_clean or "best")
        if requested_norm in {"", "auto", "best"}:
            candidates = priorities
        for candidate in candidates:
            if candidate in available:
                _RESOLVED_MODEL_CACHE[cache_key] = candidate
                return candidate
        for candidate in priorities:
            if candidate in available:
                _RESOLVED_MODEL_CACHE[cache_key] = candidate
                return candidate
    except Exception as exc:
        print(f"Model listing warning: {exc}. Using priority fallback.", file=sys.stderr)

    selected = requested_clean or priorities[0]
    _RESOLVED_MODEL_CACHE[cache_key] = selected
    return selected


def _is_retryable_gemini_error(exc: Exception) -> bool:
    msg = normalize_text(str(exc))
    hints = (
        "429",
        "resource_exhausted",
        "quota",
        "rate limit",
        "timeout",
        "timed out",
        "deadline",
        "503",
        "unavailable",
        "internal",
    )
    return any(h in msg for h in hints)


def _gemini_generate_text_with_retry(model_name: str, prompt: str, temperature: float) -> str:
    last_exc: Optional[Exception] = None
    attempts = max(GEMINI_RERANK_MAX_RETRIES, 1)
    gemini_client = get_gemini_client()
    for attempt in range(1, attempts + 1):
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=temperature),
            )
            return response.text or ""
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_retryable_gemini_error(exc):
                raise
            delay = min(
                GEMINI_RERANK_RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5),
                GEMINI_RERANK_RETRY_MAX_SECONDS,
            )
            sleep(delay)
    if last_exc:
        raise last_exc
    return ""


def _score_from_rerank_item(item: dict) -> Optional[float]:
    raw_score = item.get("score")
    if raw_score is not None:
        try:
            return _clip01(float(raw_score))
        except (TypeError, ValueError):
            pass
    try:
        rel = float(item.get("relevance", 0.0))
        thesis = float(item.get("thesis_density", 0.0))
        authority = float(item.get("authority_alignment", 0.0))
        procedural_noise = float(item.get("procedural_noise", 0.0))
        score = (0.50 * rel) + (0.25 * thesis) + (0.20 * authority) - (0.15 * procedural_noise)
        return _clip01(score)
    except (TypeError, ValueError):
        return None


def _build_batch_rerank_prompt(query: str, batch: list[tuple[int, dict]]) -> str:
    lines: list[str] = []
    for local_id, (_, row) in enumerate(batch, 1):
        lines.append(f"ID={local_id}\n{_build_semantic_excerpt(row)}")
    return (
        "Voce e um reranker juridico senior para pesquisa STF/STJ.\n"
        "Pontue CADA documento com rigor tecnico para responder a pergunta.\n"
        "Rubrica de qualidade:\n"
        "- relevancia juridica direta ao pedido;\n"
        "- densidade de tese (nao apenas obice processual);\n"
        "- alinhamento com forca normativa indicada;\n"
        "- aplicabilidade pratica.\n"
        "Penalize textos perifericos e excesso de processualismo quando nao for foco da pergunta.\n"
        "Retorne SOMENTE JSON valido no formato:\n"
        "[{\"id\": 1, \"score\": 0.0, \"relevance\": 0.0, \"thesis_density\": 0.0, "
        "\"authority_alignment\": 0.0, \"procedural_noise\": 0.0}]\n"
        "Regras:\n"
        "- score e sub-scores entre 0.0 e 1.0\n"
        "- use todos os IDs recebidos\n"
        "- sem markdown, sem texto extra\n\n"
        f"PERGUNTA:\n{query}\n\n"
        "DOCUMENTOS:\n"
        + "\n\n".join(lines)
    )


def _score_single_gemini_batch(
    query: str,
    batch: list[tuple[int, dict]],
    model_name: str,
) -> dict[int, float]:
    prompt = _build_batch_rerank_prompt(query, batch)
    text = _gemini_generate_text_with_retry(model_name=model_name, prompt=prompt, temperature=0.1)
    parsed = _extract_json_array(text or "")

    scores_by_global: dict[int, float] = {}
    assigned: set[int] = set()
    if parsed:
        for item in parsed:
            if not isinstance(item, dict):
                continue
            local_id = item.get("id")
            if not isinstance(local_id, int):
                continue
            if local_id < 1 or local_id > len(batch):
                continue
            score = _score_from_rerank_item(item)
            if score is None:
                continue
            global_idx = batch[local_id - 1][0]
            scores_by_global[global_idx] = score
            assigned.add(local_id)

    for local_id, (global_idx, row) in enumerate(batch, 1):
        if local_id not in assigned:
            scores_by_global[global_idx] = _fallback_semantic_score(query, row)
    return scores_by_global


def _semantic_scores_local(query: str, results: list[dict]) -> list[float]:
    reranker = get_reranker()
    pairs = [[query, clean_retrieved_text(r.get("texto_busca", ""))] for r in results]
    return [float(v) for v in reranker.predict(pairs)]


def _semantic_scores_gemini(
    query: str,
    results: list[dict],
    *,
    model_name_override: Optional[str] = None,
) -> list[float]:
    model_name = _resolve_best_gemini_model(model_name_override or GEMINI_RERANK_MODEL)
    batch_size = max(GEMINI_RERANK_BATCH_SIZE, 1)
    passes = max(GEMINI_RERANK_PASSES, 1)
    indexed = list(enumerate(results))
    score_buckets: list[list[float]] = [[] for _ in results]

    batch_jobs: list[list[tuple[int, dict]]] = []
    batch_bases: list[list[tuple[int, dict]]] = []
    for start in range(0, len(indexed), batch_size):
        batch_base = indexed[start : start + batch_size]
        batch_bases.append(batch_base)
        for pass_idx in range(passes):
            if len(batch_base) > 1:
                shift = pass_idx % len(batch_base)
                batch = batch_base[shift:] + batch_base[:shift]
            else:
                batch = batch_base
            batch_jobs.append(batch)

    max_workers = max(1, min(GEMINI_RERANK_MAX_WORKERS, len(batch_jobs)))
    if max_workers == 1:
        for batch in batch_jobs:
            try:
                scores_map = _score_single_gemini_batch(query=query, batch=batch, model_name=model_name)
            except Exception as exc:
                print(f"Gemini rerank batch warning: {exc}", file=sys.stderr)
                scores_map = {
                    global_idx: _fallback_semantic_score(query, row)
                    for global_idx, row in batch
                }
            for global_idx, score in scores_map.items():
                score_buckets[global_idx].append(_clip01(score))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_score_single_gemini_batch, query, batch, model_name): batch
                for batch in batch_jobs
            }
            for future in as_completed(futures):
                batch = futures[future]
                try:
                    scores_map = future.result()
                except Exception as exc:
                    print(f"Gemini rerank batch warning: {exc}", file=sys.stderr)
                    scores_map = {
                        global_idx: _fallback_semantic_score(query, row)
                        for global_idx, row in batch
                    }
                for global_idx, score in scores_map.items():
                    score_buckets[global_idx].append(_clip01(score))

    for batch_base in batch_bases:
        for global_idx, row in batch_base:
            if not score_buckets[global_idx]:
                score_buckets[global_idx].append(_fallback_semantic_score(query, row))

    scores: list[float] = []
    for idx, bucket in enumerate(score_buckets):
        if not bucket:
            bucket = [_fallback_semantic_score(query, results[idx])]
        mean = sum(bucket) / len(bucket)
        variance = sum((v - mean) ** 2 for v in bucket) / max(len(bucket), 1)
        std = math.sqrt(max(variance, 0.0))
        robust = _clip01(mean - (0.08 * std))
        scores.append(robust)

    refine_top = min(max(GEMINI_RERANK_REFINE_TOP, 0), len(results))
    if refine_top >= 4:
        pool = sorted(range(len(results)), key=lambda i: scores[i], reverse=True)[:refine_top]
        refine_lines: list[str] = []
        for local_id, global_idx in enumerate(pool, 1):
            row = results[global_idx]
            refine_lines.append(f"ID={local_id}\nBaseScore={scores[global_idx]:.4f}\n{_build_semantic_excerpt(row, max_chars=1200)}")
        refine_prompt = (
            "Voce vai recalibrar o ranking global dos melhores candidatos juridicos.\n"
            "Retorne SOMENTE JSON valido no formato:\n"
            "[{\"id\": 1, \"score\": 0.0}]\n"
            "Regras:\n"
            "- score entre 0.0 e 1.0\n"
            "- use todos os IDs\n"
            "- sem texto extra\n\n"
            f"PERGUNTA:\n{query}\n\n"
            "CANDIDATOS:\n"
            + "\n\n".join(refine_lines)
        )
        try:
            refine_response = get_gemini_client().models.generate_content(
                model=model_name,
                contents=refine_prompt,
                config=types.GenerateContentConfig(temperature=0.0),
            )
            refine_parsed = _extract_json_array(refine_response.text or "")
        except Exception:
            refine_parsed = None

        if refine_parsed:
            refined_scores: dict[int, float] = {}
            for item in refine_parsed:
                if not isinstance(item, dict):
                    continue
                local_id = item.get("id")
                raw_score = item.get("score")
                if not isinstance(local_id, int):
                    continue
                if local_id < 1 or local_id > len(pool):
                    continue
                try:
                    refined_scores[local_id] = _clip01(float(raw_score))
                except (TypeError, ValueError):
                    continue

            blend = _clip01(GEMINI_RERANK_REFINE_WEIGHT)
            for local_id, global_idx in enumerate(pool, 1):
                if local_id not in refined_scores:
                    continue
                scores[global_idx] = _clip01((1.0 - blend) * scores[global_idx] + blend * refined_scores[local_id])

    return scores


def compute_semantic_scores(
    query: str,
    results: list[dict],
    reranker_backend: Optional[str] = None,
    gemini_rerank_model: Optional[str] = None,
) -> tuple[list[float], str]:
    backend = (reranker_backend or RERANKER_BACKEND or "local").strip().lower()
    if backend == "gemini":
        model_name = _resolve_best_gemini_model(gemini_rerank_model or GEMINI_RERANK_MODEL)
        try:
            return _semantic_scores_gemini(query, results, model_name_override=model_name), f"gemini:{model_name}"
        except Exception as exc:
            print(f"Gemini reranker warning: {exc}. Falling back to local reranker.", file=sys.stderr)
    return _semantic_scores_local(query, results), "local"


def _ranking_dedupe_key(row: dict) -> str:
    processo = normalize_text(row.get("processo", ""))
    if processo:
        tribunal = normalize_text(row.get("tribunal", ""))
        tipo = normalize_text(row.get("tipo", ""))
        return f"{tribunal}|{tipo}|{processo}"
    doc_id = row.get("doc_id")
    if doc_id:
        return f"id|{doc_id}"
    return f"fallback|{normalize_text(str(row))[:120]}"


def _dedupe_ranked_results(results: list[dict], top_k: int) -> list[dict]:
    selected: list[dict] = []
    selected_indexes: set[int] = set()
    seen_keys: set[str] = set()

    for idx, row in enumerate(results):
        key = _ranking_dedupe_key(row)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected.append(row)
        selected_indexes.add(idx)
        if len(selected) >= top_k:
            return selected[:top_k]

    # Fallback: if dedupe removed too much, complete with remaining rows.
    for idx, row in enumerate(results):
        if idx in selected_indexes:
            continue
        selected.append(row)
        if len(selected) >= top_k:
            break
    return selected[:top_k]


def rerank_results(
    query: str,
    results: list[dict],
    top_k: int = TOPK_RERANK,
    prefer_recent: bool = True,
    prefer_user_sources: bool = True,
    reranker_backend: Optional[str] = None,
    config: Optional[dict[str, Any]] = None,
) -> list[dict]:
    if not results:
        return []

    cfg = config or RAG_TUNING_DEFAULTS

    semantic_raw, semantic_backend = compute_semantic_scores(
        query,
        results,
        reranker_backend=reranker_backend,
        gemini_rerank_model=str(cfg.get("gemini_rerank_model", GEMINI_RERANK_MODEL) or GEMINI_RERANK_MODEL),
    )
    semantic_norm = min_max_scale(semantic_raw)

    semantic_weight = float(cfg.get("semantic_weight", SEMANTIC_WEIGHT))
    lexical_weight = float(cfg.get("lexical_weight", LEXICAL_WEIGHT))
    recency_weight = float(cfg.get("recency_weight", RECENCY_WEIGHT))
    recency_intent_multiplier = float(cfg.get("recency_intent_multiplier", RECENCY_INTENT_MULTIPLIER))
    recency_dominant_multiplier = float(cfg.get("recency_dominant_multiplier", RECENCY_DOMINANT_MULTIPLIER))
    recency_min_semantic_gate = float(cfg.get("recency_min_semantic_gate", RECENCY_MIN_SEMANTIC_GATE))
    recency_max_contribution = float(cfg.get("recency_max_contribution", RECENCY_MAX_CONTRIBUTION))
    recency_unknown_score = float(cfg.get("recency_unknown_score", RECENCY_UNKNOWN_SCORE))
    recency_half_life_years = float(cfg.get("recency_half_life_years", RECENCY_HALFLIFE_YEARS))
    thesis_bonus_weight = float(cfg.get("thesis_bonus_weight", THESIS_BONUS_WEIGHT))
    procedural_penalty_weight = float(cfg.get("procedural_penalty_weight", PROCEDURAL_PENALTY_WEIGHT))
    procedural_intent_penalty_multiplier = float(
        cfg.get("procedural_intent_penalty_multiplier", PROCEDURAL_INTENT_PENALTY_MULTIPLIER)
    )
    authority_weight = float(cfg.get("authority_bonus_weight", AUTHORITY_BONUS_WEIGHT))
    authority_intent_multiplier = float(cfg.get("authority_intent_multiplier", AUTHORITY_INTENT_MULTIPLIER))
    user_source_priority_boost = float(cfg.get("user_source_priority_boost", USER_SOURCE_PRIORITY_BOOST))
    rrf_weight = float(cfg.get("rrf_weight", 0.08))
    authority_level_boost = {
        "A": float(cfg.get("authority_level_a_boost", AUTHORITY_A_LEVEL_BOOST)),
        "B": float(cfg.get("authority_level_b_boost", AUTHORITY_B_LEVEL_BOOST)),
        "C": float(cfg.get("authority_level_c_boost", AUTHORITY_C_LEVEL_BOOST)),
        "D": float(cfg.get("authority_level_d_boost", AUTHORITY_D_LEVEL_BOOST)),
        "E": float(cfg.get("authority_level_e_boost", AUTHORITY_E_LEVEL_BOOST)),
    }
    collegial_binding_bonus = float(cfg.get("collegial_binding_bonus", COLLEGIAL_BINDING_BONUS))
    monocratic_binding_penalty = float(cfg.get("monocratic_binding_penalty", MONOCRATIC_BINDING_PENALTY))

    recency_intent = has_recency_intent(query)
    dominant_intent = has_dominant_intent(query)
    if recency_intent:
        recency_weight *= recency_intent_multiplier
    elif dominant_intent:
        recency_weight *= recency_dominant_multiplier
    procedural_intent = has_procedural_intent(query)
    binding_intent = has_binding_intent(query)
    if procedural_intent:
        procedural_penalty_weight *= procedural_intent_penalty_multiplier
    if binding_intent:
        authority_weight *= authority_intent_multiplier

    for idx, row in enumerate(results):
        tipo = (row.get("tipo") or "").strip().lower()
        clean_busca = clean_retrieved_text(row.get("texto_busca", "") or "")
        clean_integral = clean_retrieved_text(row.get("texto_integral", "") or "")
        doc_text = f"{row.get('processo', '')}\n{clean_busca}\n{clean_integral[:2500]}"
        lexical = lexical_overlap_score(query, doc_text)
        recency, age_years = compute_recency_score(
            row.get("data_julgamento", ""),
            recency_unknown_score=recency_unknown_score,
            recency_half_life_years=recency_half_life_years,
        )
        thesis_signal = keyword_density(doc_text, THESIS_SIGNAL_TERMS)
        procedural_signal = keyword_density(doc_text, PROCEDURAL_SIGNAL_TERMS)
        role = infer_document_role(thesis_signal, procedural_signal)
        authority_score, authority_level, authority_reason = classify_authority(row)
        source_kind = str(row.get("source_kind") or "").strip().lower()

        final = (semantic_weight * semantic_norm[idx]) + (lexical_weight * lexical)
        recency_contrib = 0.0
        if prefer_recent:
            if recency_intent:
                recency_contrib = recency_weight * recency
            elif semantic_norm[idx] >= recency_min_semantic_gate:
                recency_contrib = min(recency_weight * recency, recency_max_contribution)
        final += recency_contrib
        final += thesis_bonus_weight * thesis_signal
        final += authority_weight * authority_score
        final += rrf_weight * float(row.get("_rrf_score", 0.0))
        source_priority_contrib = 0.0
        if prefer_user_sources and source_kind == "user":
            source_priority_contrib = user_source_priority_boost
            final += source_priority_contrib
        final += authority_level_boost.get(authority_level, 0.0)
        if binding_intent:
            if tipo in {"acordao", "acordao_sv", "sumula", "sumula_stj", "sumula_vinculante", "tema_repetitivo_stj"}:
                final += collegial_binding_bonus
            if tipo in {"monocratica", "monocratica_sv"}:
                final -= monocratic_binding_penalty
        if not procedural_intent:
            final -= procedural_penalty_weight * procedural_signal

        row["_semantic_raw"] = semantic_raw[idx]
        row["_semantic_score"] = semantic_norm[idx]
        row["_semantic_backend"] = semantic_backend
        row["_lexical_score"] = lexical
        row["_recency_score"] = recency
        row["_recency_contrib"] = recency_contrib
        row["_thesis_score"] = thesis_signal
        row["_procedural_score"] = procedural_signal
        row["_document_role"] = role
        row["_document_role_label"] = role_label(role)
        row["_authority_score"] = authority_score
        row["_authority_level"] = authority_level
        row["_authority_label"] = authority_label(authority_level)
        row["_authority_reason"] = authority_reason
        row["_age_years"] = age_years
        row["_source_priority_contrib"] = source_priority_contrib
        row["_final_score"] = final

    results.sort(
        key=lambda x: (
            x.get("_final_score", 0.0),
            x.get("_authority_score", 0.0),
            x.get("_thesis_score", 0.0),
            x.get("_semantic_score", 0.0),
            x.get("_lexical_score", 0.0),
        ),
        reverse=True,
    )
    if bool(cfg.get("rerank_dedup_process", RERANK_DEDUP_PROCESS)):
        return _dedupe_ranked_results(results, top_k=top_k)
    return results[:top_k]


def _truncate_text(value: str, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _extract_labeled_line(text: str, labels: tuple[str, ...]) -> str:
    content = clean_retrieved_text(text or "")
    if not content:
        return ""
    for label in labels:
        pattern = re.compile(rf"(?im)\b{re.escape(label)}\s*:\s*(.+)")
        match = pattern.search(content)
        if not match:
            continue
        candidate = clean_retrieved_text(match.group(1))
        if candidate:
            return candidate
    return ""


def _extract_normative_statement(row: dict, max_chars: int = 260) -> str:
    tipo = (row.get("tipo") or "").strip().lower()
    busca = clean_retrieved_text(row.get("texto_busca", "") or "")
    integral = clean_retrieved_text(row.get("texto_integral", "") or "")
    joined_text = f"{busca}\n{integral}".strip()
    corpus_norm = normalize_text(f"{row.get('processo', '')}\n{joined_text}")
    meta = _parse_metadata_extra(row.get("metadata_extra", ""))

    structural_tipo = {"sumula", "sumula_stj", "sumula_vinculante", "tema_repetitivo_stj"}
    is_structural = tipo in structural_tipo
    if tipo in {"acordao", "acordao_sv"}:
        is_structural = (
            _is_trueish(meta.get("is_repercussao_geral"))
            or "repercussao geral" in corpus_norm
            or bool(re.search(r"\btema\s+\d+\b", corpus_norm))
        )

    if not is_structural:
        return ""

    candidates: list[str] = []

    for key in ("tese_tema", "tema", "assunto", "titulo"):
        raw = meta.get(key)
        txt = clean_retrieved_text(str(raw or ""))
        if len(txt) >= 26:
            candidates.append(txt)

    labeled = _extract_labeled_line(
        joined_text,
        labels=("Enunciado", "Tese", "Ementa", "Tema", "Tese fixada", "Tese firmada"),
    )
    if labeled:
        candidates.append(labeled)

    for line in joined_text.splitlines():
        item = clean_retrieved_text(line)
        if len(item) < 28:
            continue
        item_norm = normalize_text(item)
        if item_norm.startswith(("origem:", "processo:", "relator:", "orgao julgador:", "ramo:", "data:")):
            continue
        if re.match(r"(?i)^(stf|stj)\s+", item):
            continue
        candidates.append(item)
        break

    if not candidates:
        return ""

    seen: set[str] = set()
    for candidate in candidates:
        compact = re.sub(r"\s+", " ", candidate).strip(" -:")
        compact = re.sub(
            r"(?i)^(sumula(?:\s+stj)?\s*\d+|sumula vinculante\s*\d+|tema repetitivo\s*\d+|tema\s*\d+)\s*[:\-]\s*",
            "",
            compact,
        )
        if len(compact) < 24:
            continue
        norm = normalize_text(compact)
        if norm in seen:
            continue
        seen.add(norm)
        return _truncate_text(compact, max_chars=max_chars)
    return ""


def _split_passage_candidates(text: str) -> list[str]:
    base = (text or "").strip()
    if not base:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", base) if len(p.strip()) >= 80]
    if len(paragraphs) >= 3:
        return paragraphs

    sentences = [s.strip() for s in re.split(r"(?<=[\.\!\?;])\s+", base) if len(s.strip()) >= 80]
    return sentences if sentences else [base]


def _extract_context_passages(
    query: str,
    row: dict,
    *,
    context_max_passages_per_doc: int = CONTEXT_MAX_PASSAGES_PER_DOC,
    context_max_passage_chars: int = CONTEXT_MAX_PASSAGE_CHARS,
    context_max_doc_chars: int = CONTEXT_MAX_DOC_CHARS,
) -> list[str]:
    busca = clean_retrieved_text(row.get("texto_busca", "") or "")
    integral = clean_retrieved_text(row.get("texto_integral", "") or "")
    query_tokens = [t for t in normalize_tokens(query) if t not in LEGAL_STOP_TOKENS]
    query_tokens = query_tokens or normalize_tokens(query)

    selected: list[str] = []
    seen: set[str] = set()
    total_chars = 0

    if busca:
        resumo = _truncate_text(busca, context_max_passage_chars)
        selected.append(resumo)
        seen.add(normalize_text(resumo[:140]))
        total_chars += len(resumo)

    candidates = _split_passage_candidates(integral)
    scored: list[tuple[float, str]] = []
    for p in candidates:
        p_norm = normalize_text(p)
        query_hits = sum(1 for t in set(query_tokens) if t and t in p_norm)
        thesis_signal = keyword_density(p, THESIS_SIGNAL_TERMS)
        procedural_signal = keyword_density(p, PROCEDURAL_SIGNAL_TERMS)
        score = (1.20 * query_hits) + (1.80 * thesis_signal) + (0.80 * procedural_signal)
        if score > 0:
            scored.append((score, p))

    if not scored and integral:
        scored = [(0.01, p) for p in _split_passage_candidates(integral[:context_max_doc_chars])]

    scored.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
    for _, passage in scored:
        norm_key = normalize_text(passage[:140])
        if norm_key in seen:
            continue
        clipped = _truncate_text(passage, context_max_passage_chars)
        if not clipped:
            continue
        projected = total_chars + len(clipped)
        if projected > context_max_doc_chars:
            continue
        selected.append(clipped)
        seen.add(norm_key)
        total_chars = projected
        if len(selected) >= context_max_passages_per_doc:
            break

    return selected


def format_context(
    docs: list[dict],
    query: str = "",
    *,
    context_max_passages_per_doc: int = CONTEXT_MAX_PASSAGES_PER_DOC,
    context_max_passage_chars: int = CONTEXT_MAX_PASSAGE_CHARS,
    context_max_doc_chars: int = CONTEXT_MAX_DOC_CHARS,
) -> str:
    chunks: list[str] = []
    for i, d in enumerate(docs, 1):
        label = type_label(d.get("tipo", ""))
        passages = _extract_context_passages(
            query,
            d,
            context_max_passages_per_doc=context_max_passages_per_doc,
            context_max_passage_chars=context_max_passage_chars,
            context_max_doc_chars=context_max_doc_chars,
        )
        authority_label_value = d.get("_authority_label", authority_label("D"))
        chunk = [
            f"[DOC. {i}]",
            f"Origem: {d.get('tribunal', '')} - {label}",
            f"Qualificacao do precedente: {authority_label_value}",
            f"Fundamento da qualificacao: {d.get('_authority_reason', 'Nao classificado.')}",
            f"Processo/Informativo: {d.get('processo', '')} (ID: {d.get('doc_id', '')})",
            f"Ramo: {d.get('ramo_direito', '')}",
            f"Data: {d.get('data_julgamento', '')}",
            f"Relator/Orgao: {d.get('relator', '')} / {orgao_label(d.get('orgao_julgador', ''))}",
        ]
        normative_statement = _extract_normative_statement(d)
        if normative_statement:
            chunk.append(f"Enunciado/Tese-chave: {normative_statement}")
        chunk.append("TRECHOS SELECIONADOS:")
        for p_idx, passage in enumerate(passages, 1):
            chunk.append(f"- [Trecho {p_idx}] {passage}")
        if not passages:
            chunk.append("- [Trecho] Sem texto util extraido.")
        chunk.extend([
            "-" * 50,
            "",
        ])
        chunks.append("\n".join(chunk))
    return "\n".join(chunks)


def generate_answer(
    query: str,
    context: str,
    use_reasoning: bool = False,
    *,
    generation_model: str = GENERATION_MODEL,
    generation_fallback_model: str = GENERATION_FALLBACK_MODEL,
    generation_temperature: float = 0.1,
    generation_max_output_tokens: int = GENERATION_MAX_OUTPUT_TOKENS,
    generation_thinking_budget: int = GENERATION_THINKING_BUDGET,
    return_diagnostics: bool = False,
) -> str | tuple[str, dict[str, Any]]:
    def _build_generation_config(*, system_instruction: str, thinking_budget: int) -> types.GenerateContentConfig:
        kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": max(0.0, min(float(generation_temperature), 1.0)),
            "max_output_tokens": max(300, int(generation_max_output_tokens)),
        }
        if hasattr(types, "ThinkingConfig") and int(thinking_budget) > 0:
            try:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=int(thinking_budget))
            except Exception:
                pass
        return types.GenerateContentConfig(**kwargs)

    def _finish_reason_name(response_obj: Any) -> str:
        candidates = getattr(response_obj, "candidates", None) or []
        if not candidates:
            return ""
        raw = getattr(candidates[0], "finish_reason", "")
        return str(raw or "").upper()

    system_prompt = (
        "Voce e um assistente juridico especialista na jurisprudencia do STF e STJ.\n"
        "REGRA 1: Escreva uma narrativa fluida integrando a explicacao e a fundamentacao em um unico texto.\n"
        "REGRA 2: Responda com base EXCLUSIVA nos [DOCS] recuperados no acervo.\n"
        "REGRA 3: Diferencie claramente (a) precedentes que definem o merito da controversia e "
        "(b) precedentes que tratam de matéria processual.\n"
        "REGRA 3B: Priorize precedentes qualificados e vinculantes "
        "(sumula vinculante, tema de repercussao geral, tema repetitivo, controle concentrado). "
        "Use acordaos ordinarios, decisoes monocraticas e informativos apenas como apoio.\n"
        "REGRA 3C: O texto pode ser lido por TTS. Evite formato que dependa de visao "
        "(tabelas, setas, markdown complexo, abreviacoes opacas sem expandir).\n"
        "REGRA 3D: Nao escreva numeros por extenso. Preserve numeros de processo, tema, sumula, artigo e data no formato numerico original.\n"
        "REGRA 3E: Use a forma 'tema de repercussao geral' e nunca 'tema da repercussao geral'.\n"
        "REGRA 3F: Ao citar sumula, sumula vinculante, tema de repercussao geral ou tema repetitivo, explique o enunciado/tese correspondente (com trecho literal quando possivel); nao cite apenas o numero.\n"
        "REGRA 3G: Nao mencione classificacoes internas do sistema de ranking. "
        "Em vez disso, identifique explicitamente o tipo do precedente "
        "(tema, sumula, acordao, habeas corpus, decisao monocratica, entre outros).\n"
        "REGRA 3H: Nao gere secoes finais de inventario de fontes "
        "(ex.: 'Documentos citados' ou JSON de documentos). "
        "Mantenha as referencias apenas no corpo do texto com [DOC. N].\n"
        "REGRA 4: Toda afirmacao juridica central deve trazer citacao explicita no formato [DOC. N].\n"
        "REGRA 4B: Todo paragrafo analitico deve terminar com pelo menos uma citacao [DOC. N].\n"
        "REGRA 5: Inclua trechos literais curtos, quando cabíveis, em formato de citacao direta markdown: "
        "> \"texto literal\" [DOC. N].\n"
        "REGRA 6: Nao invente orgao julgador, data ou tese. Se faltar prova textual, diga que faltou.\n\n"
        "REGRA 6B: Ao final, traga uma sintese conclusiva respondendo objetivamente ao que foi perguntado.\n\n"
        "====== CONTEXTO RECUPERADO ======\n"
        f"{context}\n"
        "=================================\n"
    )

    diagnostics: dict[str, Any] = {
        "attempts": [],
        "primary_hit_max_tokens": False,
        "used_fallback": False,
        "selected_model": "",
        "selected_hit_max_tokens": False,
    }

    def _record_attempt(model_name: str, finish_reason: str, text: str) -> bool:
        hit_max = "MAX_TOKENS" in (finish_reason or "")
        diagnostics["attempts"].append(
            {
                "model": model_name,
                "finish_reason": finish_reason or "",
                "hit_max_tokens": bool(hit_max),
                "text_chars": len(text or ""),
            }
        )
        return bool(hit_max)

    def _result(value: str) -> str | tuple[str, dict[str, Any]]:
        if return_diagnostics:
            return value, diagnostics
        return value

    primary_model = _resolve_best_gemini_model(generation_model)
    fallback_model = (
        _resolve_best_gemini_model(generation_fallback_model)
        if generation_fallback_model
        else ""
    )
    primary_text = ""
    primary_hit_max_tokens = False

    try:
        response = get_gemini_client().models.generate_content(
            model=primary_model,
            contents=query,
            config=_build_generation_config(
                system_instruction=system_prompt,
                thinking_budget=int(generation_thinking_budget),
            ),
        )
        finish_reason = _finish_reason_name(response)
        primary_text = (response.text or "").strip()
        primary_hit_max_tokens = _record_attempt(primary_model, finish_reason, primary_text)
        diagnostics["primary_hit_max_tokens"] = bool(primary_hit_max_tokens)
        if primary_hit_max_tokens:
            print(
                f"Generation notice ({primary_model}): response hit MAX_TOKENS "
                f"(thinking_budget={int(generation_thinking_budget)}).",
                file=sys.stderr,
            )
        if primary_text and not primary_hit_max_tokens:
            diagnostics["selected_model"] = primary_model
            diagnostics["used_fallback"] = False
            diagnostics["selected_hit_max_tokens"] = False
            return _result(primary_text)
    except Exception as exc:
        print(f"Generation warning ({primary_model}): {exc}", file=sys.stderr)

    should_try_fallback = (not primary_text) or primary_hit_max_tokens
    if should_try_fallback and fallback_model and fallback_model != primary_model:
        try:
            fallback = get_gemini_client().models.generate_content(
                model=fallback_model,
                contents=query,
                config=_build_generation_config(
                    system_instruction=system_prompt,
                    thinking_budget=int(generation_thinking_budget),
                ),
            )
            fallback_finish_reason = _finish_reason_name(fallback)
            text = (fallback.text or "").strip()
            fallback_hit_max_tokens = _record_attempt(fallback_model, fallback_finish_reason, text)
            if fallback_hit_max_tokens:
                print(
                    f"Generation notice ({fallback_model}): response hit MAX_TOKENS "
                    f"(thinking_budget={int(generation_thinking_budget)}).",
                    file=sys.stderr,
                )
            if text:
                diagnostics["selected_model"] = fallback_model
                diagnostics["used_fallback"] = True
                diagnostics["selected_hit_max_tokens"] = bool(fallback_hit_max_tokens)
                return _result(text)
        except Exception as exc:
            print(f"Generation fallback warning ({fallback_model}): {exc}", file=sys.stderr)
    if primary_text:
        diagnostics["selected_model"] = primary_model
        diagnostics["used_fallback"] = False
        diagnostics["selected_hit_max_tokens"] = bool(primary_hit_max_tokens)
        return _result(primary_text)

    diagnostics["selected_model"] = ""
    diagnostics["used_fallback"] = False
    diagnostics["selected_hit_max_tokens"] = False
    return _result("Nao foi possivel gerar resposta.")


CITATION_PATTERN = re.compile(r"\[[^\]]*(?:DOC(?:UMENTO)?\.?)\s*\d+[^\]]*\]", flags=re.IGNORECASE)
DOC_NUM_PATTERN = re.compile(r"(?:DOC(?:UMENTO)?\.?)\s*(\d+)", flags=re.IGNORECASE)
QUOTE_PATTERN = re.compile(r"[\"\u201c][^\"\u201d]{8,1200}[\"\u201d]")
DIRECT_QUOTE_WITH_CITATION_PATTERN = re.compile(
    r"(?:>\s*)?(?P<quote>[\"\u201c][^\"\u201d]{8,1200}[\"\u201d])\s*(?P<citation>\[[^\]]*(?:DOC(?:UMENTO)?\.?)\s*\d+[^\]]*\])",
    flags=re.IGNORECASE,
)
THEME_OR_SUMULA_PATTERN = re.compile(
    r"(?i)\b(?:tema(?:\s+de\s+repercuss(?:ao|ão)\s+geral)?\s+\d+|s[úu]mula(?:\s+vinculante|(?:\s+stj)?)\s+\d+)\b"
)


def _strip_outer_quotes(text: str) -> str:
    value = (text or "").strip()
    if value.startswith(("“", "\"")):
        value = value[1:]
    if value.endswith(("”", "\"")):
        value = value[:-1]
    return value.strip()


def _normalize_literal_match_text(text: str) -> str:
    base = normalize_text(clean_retrieved_text(text or ""))
    base = re.sub(r"[^a-z0-9\s]", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base


def _citation_doc_number(citation: str) -> Optional[int]:
    m = DOC_NUM_PATTERN.search(citation or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _is_literal_quote_for_citation(quote: str, citation: str, docs: list[dict]) -> bool:
    num = _citation_doc_number(citation)
    if not num or num < 1 or num > len(docs):
        return False
    doc = docs[num - 1]
    quote_raw = _strip_outer_quotes(quote)
    quote_norm = _normalize_literal_match_text(quote_raw)
    if len(quote_norm) < 12:
        return False

    source = (doc.get("texto_integral") or "") + "\n" + (doc.get("texto_busca") or "")
    source_norm = _normalize_literal_match_text(source)
    return bool(source_norm and quote_norm in source_norm)


def _count_literal_quotes(answer: str, docs: list[dict]) -> int:
    count = 0
    for m in DIRECT_QUOTE_WITH_CITATION_PATTERN.finditer(answer or ""):
        if _is_literal_quote_for_citation(m.group("quote"), m.group("citation"), docs):
            count += 1
    return count


def _extract_quote_candidate(text: str, max_len: int = 220) -> str:
    clean = clean_retrieved_text(text)
    if not clean:
        return ""
    clean = re.sub(r"(?i)^\s*ementa\s*[:\-]?\s*", "", clean).strip()
    # Prefer sentence-like snippets.
    parts = re.split(r"(?<=[\.\!\?;])\s+", clean)
    for part in parts:
        p = part.strip()
        if len(p) >= 35:
            return p[:max_len].rstrip(" ,;")
    return clean[:max_len].rstrip(" ,;")


def _extract_ementa_literal(
    row: dict,
    max_chars: int = 900,
    *,
    require_marker: bool = True,
) -> str:
    merged = "\n".join(
        [
            str(row.get("texto_integral") or ""),
            str(row.get("texto_busca") or ""),
        ]
    )
    clean = clean_retrieved_text(merged)
    if not clean:
        return ""

    patterns = (
        r"(?is)\bementa\s*:\s*(.+?)(?:\n\s*\n|(?:acordam|decisao|decisão|relatorio|relatório|voto)\b|$)",
        r"(?is)\bementa\b\s*\n+(.+?)(?:\n\s*\n|(?:acordam|decisao|decisão|relatorio|relatório|voto)\b|$)",
    )
    for pattern in patterns:
        m = re.search(pattern, clean)
        if not m:
            continue
        candidate = re.sub(r"\s+", " ", m.group(1)).strip(" -:")
        if len(candidate) >= 24:
            return _truncate_text(candidate, max_chars=max_chars)

    if require_marker:
        return ""

    candidate = _extract_normative_statement(row, max_chars=max_chars)
    return candidate or ""


def _build_theme_sumula_ementa_enrichment(
    answer: str,
    docs: list[dict],
    *,
    max_items: int = 3,
) -> str:
    if not answer or not docs:
        return ""
    if "Ementas literais para temas/sumulas citados:" in answer:
        return ""
    if not THEME_OR_SUMULA_PATTERN.search(answer):
        return ""

    cited_numbers = _extract_cited_doc_numbers(answer)
    if not cited_numbers:
        cited_numbers = list(range(1, min(len(docs), max_items) + 1))

    lines: list[str] = []
    seen: set[str] = set()
    for num in cited_numbers:
        idx = num - 1
        if idx < 0 or idx >= len(docs):
            continue
        doc = docs[idx]
        literal = _extract_ementa_literal(doc, require_marker=True)
        if not literal:
            continue
        key = normalize_text(literal[:180])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f'> "{literal}" [DOC. {num}]')
        if len(lines) >= max_items:
            break

    if not lines:
        return ""
    return "\n\nEmentas literais para temas/sumulas citados:\n" + "\n\n".join(lines)


def _build_citation_fallback(docs: list[dict], max_items: int = 3) -> str:
    lines: list[str] = []
    for i, doc in enumerate(docs[:max_items], 1):
        quote = _extract_quote_candidate(doc.get("texto_integral", "") or doc.get("texto_busca", ""))
        if not quote:
            continue
        lines.append(f'> "{quote}" [DOC. {i}]')
    if not lines:
        return ""
    return "\n\nTrechos literais de apoio:\n" + "\n\n".join(lines)


def _extract_cited_doc_numbers(answer: str) -> list[int]:
    nums = {int(m.group(1)) for m in DOC_NUM_PATTERN.finditer(answer or "")}
    return sorted(nums)


def _count_uncited_paragraphs(answer: str, paragraph_citation_min_chars: int = PARAGRAPH_CITATION_MIN_CHARS) -> int:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", answer or "") if p.strip()]
    uncited = 0
    for p in paragraphs:
        if p.endswith(":") or p.startswith(">"):
            continue
        body = DOC_NUM_PATTERN.sub("", p).strip()
        if len(body) < paragraph_citation_min_chars:
            continue
        if not CITATION_PATTERN.search(p):
            uncited += 1
    return uncited



def _format_direct_quotes_markdown(answer: str, docs: list[dict]) -> str:
    if not answer:
        return answer

    def repl(match: re.Match) -> str:
        quote = match.group("quote").strip()
        citation = match.group("citation").strip()
        if not _is_literal_quote_for_citation(quote, citation, docs):
            # Keep the analytical text, but do not render as literal quotation.
            return f"{_strip_outer_quotes(quote)} {citation}"
        return f"\n> {quote} {citation}\n"

    formatted = DIRECT_QUOTE_WITH_CITATION_PATTERN.sub(repl, answer)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted).strip()
    return formatted


def _cleanup_quote_markdown_noise(answer: str) -> str:
    text = answer or ""
    if not text:
        return text

    # Force blockquote marker to start on a new line when generation outputs
    # inline forms like "a tese determina que > "texto"".
    text = re.sub(r"(?m)([^\n])\s+>\s*(?=[\"\u201c])", r"\1\n> ", text)
    text = re.sub(r"(?m)([^\n])\s+>\s*$", r"\1\n>", text)
    # Remove empty blockquote lines that often appear before a direct quote.
    text = re.sub(r"(?m)^>\s*$\n?", "", text)
    # Remove orphan punctuation lines produced by generation formatting.
    text = re.sub(r"(?m)^\s*\.\s*$\n?", "", text)
    # Ensure headings do not remain glued to previous citations.
    text = re.sub(
        r"(?im)(\[[^\]]*(?:DOC(?:UMENTO)?\.?)\s*\d+[^\]]*\])\s*(Trechos literais de apoio:)",
        r"\1\n\n\2",
        text,
    )
    text = re.sub(
        r"(?im)(\[[^\]]*(?:DOC(?:UMENTO)?\.?)\s*\d+[^\]]*\])\s*(Ementas literais para temas/sumulas citados:)",
        r"\1\n\n\2",
        text,
    )
    text = re.sub(
        r"(?m)(\[[^\]]*(?:DOC(?:UMENTO)?\.?)\s*\d+[^\]]*\])(?=[\"“])",
        r"\1\n\n",
        text,
    )
    # Normalize excessive blank lines after cleanup.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _normalize_doc_citation_labels(answer: str) -> str:
    text = answer or ""
    if not text:
        return text

    def repl(match: re.Match) -> str:
        return f"[DOC. {match.group(1)}]"

    return re.sub(
        r"\[\s*(?:DOC(?:UMENTO)?\.?)\s*(\d+)\s*\]",
        repl,
        text,
        flags=re.IGNORECASE,
    )


def _build_document_map(docs: list[dict], cited_numbers: list[int]) -> str:
    def _is_redundant_text_pair(first: str, second: str) -> bool:
        a = _normalize_literal_match_text(first)
        b = _normalize_literal_match_text(second)
        if not a or not b:
            return False
        if a == b:
            return True
        short, long = (a, b) if len(a) <= len(b) else (b, a)
        if len(short) < 80:
            return False
        if short in long and (len(short) / max(len(long), 1)) >= 0.85:
            return True
        return False

    items: list[dict[str, Any]] = []
    for num in cited_numbers:
        idx = num - 1
        if idx < 0 or idx >= len(docs):
            continue
        d = docs[idx]
        label = type_label(d.get("tipo", ""))
        processo = d.get("processo") or d.get("doc_id") or "-"
        tribunal = d.get("tribunal") or "-"
        dt = d.get("data_julgamento") or "-"
        normative_statement = _extract_normative_statement(d, max_chars=1200)
        ementa_literal = _extract_ementa_literal(d, max_chars=1400, require_marker=True)
        if normative_statement and ementa_literal and _is_redundant_text_pair(normative_statement, ementa_literal):
            normative_statement = ""
        item: dict[str, Any] = {
            "documento": f"DOCUMENTO {num}",
            "tribunal": tribunal,
            "tipo": label,
            "processo": processo,
            "data": dt,
        }
        if normative_statement:
            item["enunciado_tese"] = normative_statement
        if ementa_literal:
            item["ementa_literal"] = ementa_literal
        items.append(item)

    if not items:
        return ""
    return "```json\n" + json.dumps(items, ensure_ascii=False, indent=2) + "\n```"


def _build_generation_config_notice(generation_meta: Optional[dict[str, Any]]) -> dict[str, Any]:
    meta = generation_meta or {}
    attempts = meta.get("attempts") if isinstance(meta, dict) else None
    if not isinstance(attempts, list) or not attempts:
        return {}

    primary = attempts[0] if isinstance(attempts[0], dict) else {}
    if not bool(primary.get("hit_max_tokens")):
        return {}

    primary_model = str(primary.get("model") or "modelo principal")
    selected_model = str(meta.get("selected_model") or "")
    used_fallback = bool(meta.get("used_fallback"))
    if used_fallback and selected_model:
        message = (
            f"O modelo Gemini principal ({primary_model}) encerrou por MAX_TOKENS. "
            f"A resposta final foi concluida com o fallback ({selected_model}). "
            "Para reduzir recorrencia, aumente 'Tokens Max da Resposta' e/ou reduza "
            "'Orcamento de Raciocinio (Thinking)'."
        )
        return {
            "code": "gemini_max_tokens_fallback",
            "message": message,
            "primary_model": primary_model,
            "selected_model": selected_model,
            "used_fallback": True,
        }

    message = (
        f"O modelo Gemini principal ({primary_model}) encerrou por MAX_TOKENS e a resposta pode ter ficado curta. "
        "Ajuste 'Tokens Max da Resposta' e/ou reduza 'Orcamento de Raciocinio (Thinking)'."
    )
    return {
        "code": "gemini_max_tokens_primary_only",
        "message": message,
        "primary_model": primary_model,
        "selected_model": selected_model,
        "used_fallback": False,
    }


def _validate_answer(
    answer: str,
    docs: list[dict],
    *,
    paragraph_citation_min_chars: int = PARAGRAPH_CITATION_MIN_CHARS,
) -> str:
    normalized = normalize_text(answer)
    has_refusal = "nao encontrei" in normalized
    has_citation = bool(CITATION_PATTERN.search(answer))
    literal_quotes = _count_literal_quotes(answer, docs)

    if has_refusal:
        return "Não encontrei documentos relevantes no acervo para estruturar uma resposta."

    if not has_citation or literal_quotes < 2:
        fallback = _build_citation_fallback(docs)
        if fallback:
            answer = answer.rstrip() + fallback

    answer = _format_direct_quotes_markdown(answer, docs)
    answer = _cleanup_quote_markdown_noise(answer)
    answer = _normalize_doc_citation_labels(answer)

    cited_numbers = [n for n in _extract_cited_doc_numbers(answer) if 1 <= n <= len(docs)]

    ementa_enrichment = _build_theme_sumula_ementa_enrichment(answer, docs)
    if ementa_enrichment:
        answer = answer.rstrip() + ementa_enrichment
        answer = _normalize_doc_citation_labels(answer)

    return answer


def explain_answer(
    query: str,
    answer: str,
    docs: Optional[list[dict]] = None,
    model_name: str = EXPLAIN_MODEL,
) -> str:
    """Generate a didactic explanation of an existing answer for end users."""
    docs = docs or []

    evidence_lines: list[str] = []
    for i, doc in enumerate(docs[:EXPLAIN_DOCS_LIMIT], 1):
        label = type_label(doc.get("tipo", ""))
        processo = doc.get("processo") or doc.get("doc_id") or "-"
        authority = doc.get("_authority_level", "-")
        quote = _extract_quote_candidate(doc.get("texto_integral", "") or doc.get("texto_busca", ""))
        if not quote:
            quote = "-"
        evidence_lines.append(
            f"[DOC. {i}] {doc.get('tribunal', '-')} | {label} | {processo} | Nivel {authority} | Trecho: \"{quote}\""
        )

    evidence_block = "\n".join(evidence_lines) if evidence_lines else "(sem fontes adicionais)"
    user_prompt = (
        "PERGUNTA ORIGINAL:\n"
        f"{query.strip() or '-'}\n\n"
        "RESPOSTA BASE:\n"
        f"{(answer or '').strip()}\n\n"
        "FONTES RECUPERADAS:\n"
        f"{evidence_block}"
    )

    system_prompt = (
        "Voce e um professor de direito brasileiro. "
        "Explique em linguagem simples, precisa e sem juridiques desnecessario.\n"
        "Regras:\n"
        "1) Entregue em 3 blocos curtos: (a) ideia central, (b) por que isso importa no processo, (c) aplicacao pratica.\n"
        "2) Sempre diferencie o que e vinculante/obrigatorio do que e nao vinculante.\n"
        "3) Se houver incerteza na resposta base, aponte de forma objetiva.\n"
        "4) O texto sera ouvido por TTS: use frases naturais e evite elementos que so fazem sentido visualmente.\n"
        "5) Nao converter numeros para extenso; manter identificadores numericos como no texto original.\n"
        "6) Use no maximo 220 palavras.\n"
        "7) Nao invente fontes."
    )

    primary_model = _resolve_best_gemini_model(model_name)
    fallback_model = _resolve_best_gemini_model(GENERATION_FALLBACK_MODEL)

    try:
        response = get_gemini_client().models.generate_content(
            model=primary_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
            ),
        )
        text = (response.text or "").strip()
        if text:
            return text
    except Exception as exc:
        print(f"Explain warning ({primary_model}): {exc}", file=sys.stderr)

    if fallback_model and fallback_model != primary_model:
        try:
            fallback = get_gemini_client().models.generate_content(
                model=fallback_model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                ),
            )
            text = (fallback.text or "").strip()
            if text:
                return text
        except Exception as exc:
            print(f"Explain fallback warning ({fallback_model}): {exc}", file=sys.stderr)

    return "Nao foi possivel gerar explicacao no momento."


def run_query(
    query: str,
    tribunais: Optional[list[str]] = None,
    tipos: Optional[list[str]] = None,
    sources: Optional[list[str]] = None,
    trace: bool = False,
    prefer_recent: bool = PREFER_RECENT_DEFAULT,
    prefer_user_sources: bool = True,
    reranker_backend: Optional[str] = None,
    ramos: Optional[list[str]] = None,
    orgaos: Optional[list[str]] = None,
    relator_contains: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    rag_config: Optional[dict[str, Any]] = None,
    stage_callback: StageCallback = None,
    return_meta: bool = False,
):
    timings: dict[str, float] = {}
    started = perf_counter()
    cfg = resolve_rag_tuning(rag_config)

    if trace:
        print("=" * 30 + " TRACE ON " + "=" * 30, file=sys.stderr)

    include_ratio, user_source_ids, resolved_sources = _resolve_query_sources(sources)
    print(f"\nSearching: '{query}'")
    if any([tribunais, tipos, ramos, orgaos, relator_contains, date_from, date_to, resolved_sources]):
        print(
            "Filters -> "
            f"Tribunais: {tribunais} | Tipos: {tipos} | Ramos: {ramos} | "
            f"Orgaos: {orgaos} | Relator: {relator_contains} | Data: {date_from}..{date_to} | "
            f"Sources: {resolved_sources} | IncludeRatio: {include_ratio} | UserSources: {user_source_ids}"
        )
    else:
        print("Filters -> none (full database scope)")

    _emit_stage(stage_callback, "embedding_start", timings=timings)
    t0 = perf_counter()
    q_vec = embed_query(query)
    timings["embedding"] = perf_counter() - t0
    _emit_stage(stage_callback, "embedding_done", timings=timings)

    _emit_stage(stage_callback, "retrieval_start", timings=timings)
    t0 = perf_counter()
    raw_results = search_lancedb(
        query=query,
        query_vector=q_vec,
        top_k=int(cfg["topk_hybrid"]),
        hybrid_rrf_k=int(cfg["hybrid_rrf_k"]),
        sources=resolved_sources,
        tribunais=tribunais,
        tipos=tipos,
        ramos=ramos,
        orgaos=orgaos,
        relator_contains=relator_contains,
        date_from=date_from,
        date_to=date_to,
    )
    timings["retrieval"] = perf_counter() - t0
    _emit_stage(stage_callback, "retrieval_done", timings=timings, candidates=len(raw_results))

    print(f"Retrieved {len(raw_results)} unique candidates (hybrid top_k={int(cfg['topk_hybrid'])}).")

    if not raw_results:
        answer = "Nao encontrei documentos relevantes no acervo."
        meta = {
            "timings": timings,
            "total_seconds": perf_counter() - started,
            "candidates": 0,
            "returned_docs": 0,
            "prefer_recent": prefer_recent,
            "prefer_user_sources": bool(prefer_user_sources),
            "sources": resolved_sources,
            "weights": cfg,
        }
        _emit_stage(stage_callback, "done", timings=timings, candidates=0, returned_docs=0)
        return (answer, [], meta) if return_meta else (answer, [])

    _emit_stage(stage_callback, "rerank_start", timings=timings, candidates=len(raw_results))
    t0 = perf_counter()
    top_docs = rerank_results(
        query,
        raw_results,
        top_k=int(cfg["topk_rerank"]),
        prefer_recent=prefer_recent,
        prefer_user_sources=prefer_user_sources,
        reranker_backend=reranker_backend,
        config=cfg,
    )
    timings["rerank"] = perf_counter() - t0
    _emit_stage(stage_callback, "rerank_done", timings=timings, returned_docs=len(top_docs))

    _emit_stage(stage_callback, "generation_start", timings=timings)
    t0 = perf_counter()
    context = format_context(
        top_docs,
        query=query,
        context_max_passages_per_doc=int(cfg["context_max_passages_per_doc"]),
        context_max_passage_chars=int(cfg["context_max_passage_chars"]),
        context_max_doc_chars=int(cfg["context_max_doc_chars"]),
    )
    answer = generate_answer(
        query,
        context,
        generation_model=str(cfg["generation_model"]),
        generation_fallback_model=str(cfg["generation_fallback_model"]),
        generation_temperature=float(cfg["generation_temperature"]),
        generation_max_output_tokens=int(cfg["generation_max_output_tokens"]),
        generation_thinking_budget=int(cfg["generation_thinking_budget"]),
        return_diagnostics=True,
    )
    generation_diagnostics: dict[str, Any]
    if isinstance(answer, tuple):
        answer, generation_diagnostics = answer
    else:
        generation_diagnostics = {}
    timings["generation"] = perf_counter() - t0
    _emit_stage(stage_callback, "generation_done", timings=timings)

    _emit_stage(stage_callback, "validation_start", timings=timings)
    t0 = perf_counter()
    answer = _validate_answer(
        answer,
        top_docs,
        paragraph_citation_min_chars=int(cfg["paragraph_citation_min_chars"]),
    )
    generation_warning = _build_generation_config_notice(generation_diagnostics)
    if generation_warning:
        answer = answer.rstrip() + "\n\n[AVISO DE CONFIGURACAO] " + generation_warning.get("message", "")
    timings["validation"] = perf_counter() - t0
    timings["total"] = perf_counter() - started
    _emit_stage(stage_callback, "done", timings=timings, candidates=len(raw_results), returned_docs=len(top_docs))

    print("\n" + "=" * 80)
    print("AI ANSWER")
    print("=" * 80)
    print(answer)
    print("=" * 80)

    print("\nSOURCES (TOP RANKED):")
    for i, doc in enumerate(top_docs, 1):
        title = doc.get("processo") or doc.get("doc_id")
        label = type_label(doc.get("tipo", ""))
        role = doc.get("_document_role_label", "-")
        print(
            f"{i}. {label}: {title} | "
            f"Final={doc.get('_final_score', 0.0):.3f} | "
            f"Sem={doc.get('_semantic_score', 0.0):.3f}({doc.get('_semantic_backend', '-')}) | "
            f"Lex={doc.get('_lexical_score', 0.0):.3f} | "
            f"Rec={doc.get('_recency_score', 0.0):.3f}(+{doc.get('_recency_contrib', 0.0):.3f}) | "
            f"RRF={doc.get('_rrf_score', 0.0):.4f} | "
            f"Hier={doc.get('_authority_score', 0.0):.3f}({doc.get('_authority_level', '-')}) | "
            f"Tese={doc.get('_thesis_score', 0.0):.3f} | "
            f"Proc={doc.get('_procedural_score', 0.0):.3f} | "
            f"Papel={role} | "
            f"Date={doc.get('data_julgamento', '')}"
        )

    meta = {
        "timings": timings,
        "total_seconds": timings.get("total"),
        "candidates": len(raw_results),
        "returned_docs": len(top_docs),
        "prefer_recent": prefer_recent,
        "prefer_user_sources": bool(prefer_user_sources),
        "sources": resolved_sources,
        "reranker_backend": (top_docs[0].get("_semantic_backend") if top_docs else "n/a"),
        "weights": cfg,
        "generation": generation_diagnostics,
        "generation_warning": generation_warning,
    }

    if trace:
        print("=" * 30 + " TRACE OFF " + "=" * 30, file=sys.stderr)

    return (answer, top_docs, meta) if return_meta else (answer, top_docs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query STF/STJ RAG engine")
    parser.add_argument("query", type=str, help="Pergunta juridica")
    parser.add_argument("--trace", action="store_true", help="Enable detailed logs")
    parser.add_argument("--no-recent", action="store_true", help="Disable recency priority")
    args = parser.parse_args()

    run_query(
        query=args.query,
        trace=args.trace,
        prefer_recent=not args.no_recent,
    )

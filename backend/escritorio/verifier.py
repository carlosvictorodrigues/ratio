from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from backend.escritorio.models import RatioEscritorioState

_TRIBUNAL_ALIASES = {
    "s.t.j.": "stj",
    "superior tribunal de justica": "stj",
    "superior tribunal de justiça": "stj",
    "s.t.f.": "stf",
    "supremo tribunal federal": "stf",
}

_CLASS_ALIASES = {
    "resp": "RESP",
    "recurso especial": "RESP",
    "re": "RE",
    "recurso extraordinario": "RE",
    "recurso extraordinário": "RE",
    "agint": "AGINT",
    "agrg": "AGRG",
    "edcl": "EDCL",
    "earesp": "EARESP",
    "eresp": "ERESP",
    "aresp": "ARESP",
    "cnj": "CNJ",
}

_ARTICLE_PATTERN = re.compile(
    r"(?i)\bart\.?\s*(\d+[a-z\-]*)\s*(?:do|da|de)?\s*(cc|cpc|cpp|cf|cdc)\b"
)
_SUMULA_PATTERN = re.compile(
    r"(?i)\bs[uú]mula(?:\s+vinculante)?\s+(\d+)\s*(?:do|da)?\s*(stj|stf)?\b"
)
_RESP_PATTERN = re.compile(
    r"(?i)\b(resp|recurso especial)\s*(\d[\d\.\-]*)\s*(?:/[a-z]{2})?\b"
)
_CNJ_PATTERN = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
_TEMA_PATTERN = re.compile(
    r"(?i)\btema(?:\s+repetitivo)?\s+(?:n[ºo]?\s*)?(\d+(?:\.\d+)?)(?:\s+(?:do|/)\s*(stj|stf))?"
)
_LEI_PATTERN = re.compile(
    r"(?i)\blei\s+(?:n[ºo]?\s*)?(\d+(?:[.,/]\d+)*)"
)
_CASO_COMPOSTO_PATTERN = re.compile(
    r"(?i)\b(AgInt|AgRg|EDcl|EAREsp|EREsp|AREsp)\s+(?:no|na)\s+"
    r"(REsp|HC|MS|RMS|ARE|AI)\s+(\d[\d\.\-/A-Z]*)"
)


class CitationCandidate(BaseModel):
    kind: Literal["jurisprudencia", "sumula", "legislacao", "tema_repetitivo"]
    raw_text: str
    normalized_text: str
    tribunal: str | None = None
    class_name: str | None = None
    number: str | None = None
    article: str | None = None
    diploma: str | None = None
    canonical_key: str | None = None


class MatchResult(BaseModel):
    exists: bool
    level: Literal["exact_match", "strong_match", "weak_match", "unverified"]
    row: dict | None = None


def normalize_legal_text(raw_text: str) -> str:
    text = unicodedata.normalize("NFKD", str(raw_text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("-", " ").replace("—", " ").replace("–", " ")
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    for alias, canonical in _TRIBUNAL_ALIASES.items():
        text = text.replace(alias, canonical)
    return text


def _normalize_tribunal(raw_text: str | None) -> str | None:
    if not raw_text:
        return None
    normalized = normalize_legal_text(raw_text)
    return _TRIBUNAL_ALIASES.get(normalized, normalized)


def _normalize_class_name(raw_text: str | None) -> str | None:
    if not raw_text:
        return None
    normalized = normalize_legal_text(raw_text)
    return _CLASS_ALIASES.get(normalized, normalized.upper())


def validar_cnj(numero_cnj: str) -> bool:
    limpo = re.sub(r"[\-\.]", "", str(numero_cnj or ""))
    if len(limpo) != 20 or not limpo.isdigit():
        return False
    n, dd, aaaa, j, tr, oooo = (
        limpo[0:7],
        limpo[7:9],
        limpo[9:13],
        limpo[13:14],
        limpo[14:16],
        limpo[16:20],
    )
    valor = int(n + aaaa + j + tr + oooo + dd)
    return valor % 97 == 1


def canonicalize_candidate(candidate: CitationCandidate) -> CitationCandidate:
    canonical_key: str | None = None

    if candidate.kind == "legislacao" and candidate.article and candidate.diploma:
        canonical_key = f"art_{candidate.article.lower()}_{candidate.diploma.lower()}"
    elif candidate.kind == "legislacao" and candidate.diploma == "LEI" and candidate.number:
        canonical_key = f"lei_{candidate.number.replace('/', '_').replace('.', '_').replace(',', '_')}"
    elif candidate.kind == "sumula" and candidate.number:
        tribunal = (candidate.tribunal or "sem_tribunal").lower()
        canonical_key = f"sumula_{candidate.number}_{tribunal}"
    elif candidate.kind == "tema_repetitivo" and candidate.number:
        tribunal = (candidate.tribunal or "sem_tribunal").lower()
        canonical_key = f"tema_{candidate.number}_{tribunal}"
    elif candidate.kind == "jurisprudencia" and candidate.class_name and candidate.number:
        canonical_key = f"{candidate.class_name.lower()}_{candidate.number}"

    return candidate.model_copy(update={"canonical_key": canonical_key})


def extract_citation_candidates(text: str) -> list[CitationCandidate]:
    raw_text = str(text or "")
    candidates: list[CitationCandidate] = []

    for match in _ARTICLE_PATTERN.finditer(raw_text):
        citation = match.group(0)
        candidates.append(
            CitationCandidate(
                kind="legislacao",
                raw_text=citation,
                normalized_text=normalize_legal_text(citation),
                article=match.group(1),
                diploma=match.group(2).upper(),
            )
        )

    for match in _SUMULA_PATTERN.finditer(raw_text):
        citation = match.group(0)
        candidates.append(
            CitationCandidate(
                kind="sumula",
                raw_text=citation,
                normalized_text=normalize_legal_text(citation),
                tribunal=_normalize_tribunal(match.group(2)),
                number=match.group(1),
            )
        )

    for match in _RESP_PATTERN.finditer(raw_text):
        citation = match.group(0)
        candidates.append(
            CitationCandidate(
                kind="jurisprudencia",
                raw_text=citation,
                normalized_text=normalize_legal_text(citation),
                class_name=_normalize_class_name(match.group(1)),
                number=re.sub(r"[^\d]", "", match.group(2)),
            )
        )

    for match in _CNJ_PATTERN.finditer(raw_text):
        citation = match.group(0)
        candidates.append(
            CitationCandidate(
                kind="jurisprudencia",
                raw_text=citation,
                normalized_text=normalize_legal_text(citation),
                class_name="CNJ",
                number=re.sub(r"[^\d]", "", citation),
            )
        )

    for match in _TEMA_PATTERN.finditer(raw_text):
        citation = match.group(0)
        candidates.append(
            CitationCandidate(
                kind="tema_repetitivo",
                raw_text=citation,
                normalized_text=normalize_legal_text(citation),
                tribunal=_normalize_tribunal(match.group(2)),
                number=match.group(1),
            )
        )

    for match in _LEI_PATTERN.finditer(raw_text):
        citation = match.group(0)
        candidates.append(
            CitationCandidate(
                kind="legislacao",
                raw_text=citation,
                normalized_text=normalize_legal_text(citation),
                diploma="LEI",
                number=match.group(1),
            )
        )

    for match in _CASO_COMPOSTO_PATTERN.finditer(raw_text):
        citation = match.group(0)
        candidates.append(
            CitationCandidate(
                kind="jurisprudencia",
                raw_text=citation,
                normalized_text=normalize_legal_text(citation),
                class_name=_normalize_class_name(match.group(1)),
                number=re.sub(r"[^\d]", "", match.group(3)),
            )
        )

    return [canonicalize_candidate(candidate) for candidate in candidates]


def match_against_rows(candidate: CitationCandidate, rows: list[dict]) -> MatchResult:
    if candidate.canonical_key:
        for row in rows:
            if str(row.get("canonical_key") or "") == candidate.canonical_key:
                return MatchResult(exists=True, level="exact_match", row=row)

    if candidate.class_name and candidate.number:
        for row in rows:
            same_class = str(row.get("class_name") or "").upper() == candidate.class_name
            same_number = str(row.get("number") or "") == candidate.number
            if same_class and same_number:
                return MatchResult(exists=True, level="strong_match", row=row)

    if candidate.number:
        for row in rows:
            if str(row.get("number") or "") == candidate.number:
                return MatchResult(exists=True, level="weak_match", row=row)

    return MatchResult(exists=False, level="unverified", row=None)


def validate_provenance(canonical_key: str | None, section_evidence_pack: list[str]) -> bool:
    key = str(canonical_key or "").strip()
    if not key:
        return False
    return key in {str(item or "").strip() for item in section_evidence_pack}


def match_against_lancedb(
    candidate: CitationCandidate,
    *,
    registry,
    lance_dir: str | Path,
    table_name: str = "jurisprudencia",
) -> MatchResult:
    table = registry.open_table(lance_dir, table_name)
    rows: list[dict]

    if hasattr(table, "search") and candidate.number:
        try:
            rows = list(table.search(candidate.number).limit(20).to_list())
        except Exception:
            rows = []
    else:
        rows = []

    if not rows:
        lance_ds = table.to_lance()
        available_cols = set(getattr(lance_ds.schema, "names", []))
        select_cols = [
            column
            for column in ("canonical_key", "class_name", "number", "processo", "tribunal", "tipo", "doc_id")
            if column in available_cols
        ]
        rows = lance_ds.to_table(columns=select_cols).to_pylist()
    return match_against_rows(candidate, rows)


def verify_citation_reference(
    referencia: str,
    *,
    registry,
    lance_dir: str | Path,
    table_name: str = "jurisprudencia",
) -> dict:
    candidates = extract_citation_candidates(referencia)
    if not candidates:
        return {"exists": False, "level": "unverified", "referencia": referencia, "candidates": []}

    ranked = [
        match_against_lancedb(
            candidate,
            registry=registry,
            lance_dir=lance_dir,
            table_name=table_name,
        )
        for candidate in candidates
    ]
    priority = {"exact_match": 3, "strong_match": 2, "weak_match": 1, "unverified": 0}
    best_index = max(range(len(ranked)), key=lambda idx: priority[ranked[idx].level])
    best_match = ranked[best_index]
    best_candidate = candidates[best_index]

    return {
        "exists": best_match.exists,
        "level": best_match.level,
        "referencia": referencia,
        "best_candidate": best_candidate.model_dump(),
        "best_row": best_match.row,
        "candidates": [candidate.model_dump() for candidate in candidates],
    }


def verify_sections(
    state: RatioEscritorioState,
    *,
    registry,
    lance_dir: str | Path,
    table_name: str = "jurisprudencia",
) -> list[dict]:
    results: list[dict] = []

    for section_name, content in state.peca_sections.items():
        evidence_pack = list(state.evidence_pack.get(section_name, [])) or list(state.proveniencia.get(section_name, []))
        seen: set[tuple[str, str]] = set()
        for candidate in extract_citation_candidates(content):
            dedupe_key = (section_name, candidate.canonical_key or candidate.raw_text)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            match = match_against_lancedb(
                candidate,
                registry=registry,
                lance_dir=lance_dir,
                table_name=table_name,
            )
            results.append(
                {
                    "section": section_name,
                    "referencia": candidate.raw_text,
                    "canonical_key": candidate.canonical_key,
                    "level": match.level,
                    "exists": match.exists,
                    "provenance_ok": validate_provenance(candidate.canonical_key, evidence_pack),
                    "match_row": match.row,
                }
            )

    return results

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import math
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import lancedb
import requests
from google.genai import types

# Lazy imports — only needed at runtime for scraping / PDF extraction
fitz = None  # type: ignore[assignment]

def _get_fitz():
    global fitz
    if fitz is None:
        import fitz as _fitz
        fitz = _fitz
    return fitz

STF_API_URL = "https://jurisprudencia.stf.jus.br/api/search/search"
STF_SEARCH_URL = "https://jurisprudencia.stf.jus.br/pages/search?base=acordaos"
STJ_BASE_URL = "https://processo.stj.jus.br"
STJ_LIST_URL = f"{STJ_BASE_URL}/jurisprudencia/externo/informativo/"
STJ_EDITION_QUERY_URL = (
    f"{STJ_BASE_URL}/jurisprudencia/externo/informativo/"
    "?acao=pesquisarumaedicao&livre='{edition:04d}'.cod."
)
STJ_EDITION_PDF_URL = f"{STJ_BASE_URL}/SCON/GetPDFINFJ?edicao={{edition:04d}}"
LANCE_TABLE_NAME = "jurisprudencia"
EMBED_DIM = 768
DEFAULT_EMBED_BATCH_SIZE = 16
MAX_ES_WINDOW = 10000
ES_SAFE_WINDOW = 9500
PAGE_SIZE = 250
DEFAULT_STJ_REPAIR_MODEL = "gemini-3-flash-preview"
DEFAULT_STJ_REPAIR_MAX_RECORDS_PER_PDF = 24
DEFAULT_STJ_REPAIR_MIN_CONFIDENCE = 0.62
DEFAULT_STRICT_COMPLETENESS = True

STF_ACORDAO_FIELDS = [
    "id",
    "dg_unique",
    "titulo",
    "processo_numero",
    "processo_classe_processual_unificada_classe_sigla",
    "julgamento_data",
    "publicacao_data",
    "relator_processo_nome",
    "relator_acordao_nome",
    "orgao_julgador",
    "ementa_texto",
    "inteiro_teor_url",
    "documental_tese_texto",
    "documental_tese_tema_texto",
    "documental_indexacao_texto",
    "documental_legislacao_citada_texto",
    "is_repercussao_geral",
]

STF_MONOCRATICA_FIELDS = [
    "id",
    "dg_unique",
    "titulo",
    "processo_numero",
    "processo_classe_processual_unificada_classe_sigla",
    "julgamento_data",
    "publicacao_data",
    "relator_processo_nome",
    "decisao_texto",
    "resumo_estruturado",
    "inteiro_teor_url",
]

STF_INFORMATIVO_FIELDS = [
    "id",
    "dg_unique",
    "titulo",
    "informativo_numero",
    "informativo_titulo",
    "informativo_data",
    "informativo_resumo_texto",
    "informativo_observacao_texto",
    "processo_codigo_completo",
    "processo_numero",
    "processo_classe_processual_unificada_classe_sigla",
    "orgao_julgador",
    "relator_processo_nome",
    "relator_acordao_nome",
    "julgamento_data",
    "publicacao_data",
    "ementa_texto",
    "inteiro_teor_url",
    "documental_tese_texto",
]

ProgressCallback = Callable[[str, str, dict[str, Any]], None]
LogCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class UpdateDocument:
    doc_id: str
    tribunal: str
    tipo: str
    processo: str
    relator: str
    ramo_direito: str
    data_julgamento: str
    orgao_julgador: str
    texto_busca: str
    texto_integral: str
    url: str
    metadata_extra: str
    source_key: str


def _clean_legal_text(raw: Any) -> str:
    text = html.unescape(str(raw or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h\d|section|article)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _normalize_external_url(raw: Any, *, base_url: str = "") -> str:
    value = _normalize_space(str(raw or ""))
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    if re.match(r"(?i)^https?://", value):
        return value
    if base_url and value.startswith("/"):
        return base_url.rstrip("/") + value
    if base_url and not re.match(r"(?i)^[a-z][a-z0-9+.-]*:", value):
        return base_url.rstrip("/") + "/" + value.lstrip("/")
    return value


def _remove_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _classify_ramo(raw_ramo: str) -> str:
    text = _remove_accents(raw_ramo).upper()
    categories: list[str] = []

    if "PROCESSUAL PENAL" in text or "EXECUCAO PENAL" in text:
        categories.append("Processual Penal")
    if ("DIREITO PENAL" in text or (" PENAL" in text and "PROCESSUAL PENAL" not in text and "EXECUCAO PENAL" not in text)):
        categories.append("Penal")
    if "PROCESSUAL CIVIL" in text:
        categories.append("Processual Civil")
    if "TRIBUTAR" in text:
        categories.append("Tributario")
    if "PREVIDENCI" in text:
        categories.append("Previdenciario")
    if "TRABALH" in text:
        categories.append("Trabalho")
    if "ADMINISTRAT" in text or "IMPROBIDADE" in text or "URBANIST" in text:
        categories.append("Administrativo")
    if "CONSTITUCION" in text:
        categories.append("Constitucional")
    if "CONSUMIDOR" in text:
        categories.append("Consumidor")
    if "EMPRESARIAL" in text or "FALIMENTAR" in text or "BANCAR" in text or "SOCIETAR" in text:
        categories.append("Empresarial")
    if "AMBIENT" in text:
        categories.append("Ambiental")
    if "INTERNACIONAL" in text or "DIREITOS HUMANOS" in text:
        categories.append("Internacional")
    if "ELEITORAL" in text:
        categories.append("Eleitoral")
    if ("DIREITO CIVIL" in text or "FAMILIA" in text or "SUCESSO" in text or "CRIANCA E DO ADOLESCENTE" in text):
        categories.append("Civil")

    return "; ".join(categories) if categories else "Outros"


def _to_iso_date(raw: str) -> str:
    value = _normalize_space(raw)
    if not value:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", value)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return ""


def _extract_year(raw: str) -> int | None:
    iso = _to_iso_date(raw)
    if iso:
        try:
            return int(iso[:4])
        except Exception:
            return None
    match = re.search(r"\b(20\d{2})\b", str(raw or ""))
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def _max_date_str(values: list[str]) -> str:
    cleaned = [_to_iso_date(v) for v in values if _to_iso_date(v)]
    return max(cleaned) if cleaned else ""


def _resolve_stf_start_date(*, year: int, since_date: str) -> date:
    start = date(int(year), 1, 1)
    iso = _to_iso_date(since_date or "")
    if not iso:
        return start
    try:
        parsed = date.fromisoformat(iso)
    except Exception:
        return start
    if parsed.year != int(year):
        return start
    if parsed < start:
        return start
    return parsed


def _to_tag(text: str) -> str:
    slug = _remove_accents(_normalize_space(text or "")).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    if len(slug) < 2:
        return ""
    return slug[:40]


def _split_mark_sources(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_split_mark_sources(item))
        return out
    raw = _normalize_space(str(value))
    if not raw:
        return []
    parts = [piece.strip() for piece in re.split(r"[;|\n]+", raw) if piece.strip()]
    if parts:
        return parts
    return [raw]


def _build_marcacoes(*values: Any, max_tags: int = 16) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in _split_mark_sources(value):
            token = _to_tag(part)
            if not token or token in seen:
                continue
            seen.add(token)
            tags.append(token)
            if len(tags) >= max(1, int(max_tags or 16)):
                return tags
    return tags


def _stj_pdf_url_from_info_num(info_num: str) -> str:
    match = re.search(r"\d+", str(info_num or ""))
    if not match:
        return ""
    try:
        edition = int(match.group(0))
    except Exception:
        return ""
    if edition <= 0:
        return ""
    return STJ_EDITION_PDF_URL.format(edition=edition)


def _emit(progress_cb: ProgressCallback | None, stage: str, message: str, **fields: Any) -> None:
    if progress_cb is None:
        return
    progress_cb(stage, message, fields)


def _log(log_cb: LogCallback | None, event: str, **fields: Any) -> None:
    if log_cb is None:
        return
    log_cb(event, fields)


def _stf_build_query(
    *,
    base: str,
    source_fields: list[str],
    start: date,
    end: date,
    offset: int,
    size: int,
) -> dict[str, Any]:
    return {
        "query": {
            "bool": {
                "filter": [
                    {
                        "range": {
                            "julgamento_data": {
                                "gte": start.strftime("%Y-%m-%d"),
                                "lte": end.strftime("%Y-%m-%d"),
                                "format": "yyyy-MM-dd",
                            }
                        }
                    }
                ],
                "must": [{"term": {"base": base}}],
                "should": [],
            }
        },
        "_source": source_fields,
        "from": int(max(0, offset)),
        "size": int(max(0, size)),
        "sort": [{"julgamento_data": "asc"}],
        "track_total_hits": True,
    }


def _stf_total_from_payload(payload: dict[str, Any]) -> int:
    result = payload.get("result", payload)
    total = result.get("hits", {}).get("total", {}).get("value")
    if isinstance(total, int):
        return total
    try:
        return int(total or 0)
    except Exception:
        return 0


def _stf_hits_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result", payload)
    raw = result.get("hits", {}).get("hits", [])
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


async def _stf_fetch_api(page: Any, query: dict[str, Any]) -> dict[str, Any]:
    last_status = 0
    last_text = ""
    for attempt in range(4):
        result = await page.evaluate(
            """
            async (payload) => {
              const controller = new AbortController();
              const timeoutId = setTimeout(() => controller.abort(), 45000);
              try {
                const response = await fetch("https://jurisprudencia.stf.jus.br/api/search/search", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(payload),
                  signal: controller.signal
                });
                const text = await response.text();
                return { ok: response.ok, status: response.status, text };
              } catch (error) {
                return { ok: false, status: -1, text: String(error || "") };
              } finally {
                clearTimeout(timeoutId);
              }
            }
            """,
            query,
        )
        if not isinstance(result, dict):
            raise RuntimeError("Resposta inesperada da API STF.")
        status = int(result.get("status") or 0)
        text = str(result.get("text") or "").strip()
        last_status = status
        last_text = text
        if status == 202 and not text and attempt < 3:
            await asyncio.sleep(2.0 + attempt)
            continue
        if not text:
            break
        try:
            return json.loads(text)
        except Exception:
            if attempt < 3:
                await asyncio.sleep(1.5 + attempt)
                continue
            preview = text[:200].replace("\n", " ").strip()
            raise RuntimeError(f"JSON invalido da API STF (status={status}): {preview}")

    if last_status == 202 and not last_text:
        raise RuntimeError(
            "STF retornou status 202 sem conteudo. A janela do Chromium precisa ficar aberta para validacao no site."
        )
    raise RuntimeError(f"Resposta vazia da API STF (status={last_status}).")


async def _stf_collect_base_hits(
    *,
    page: Any,
    base: str,
    source_fields: list[str],
    year: int,
    since_date: str,
    progress_cb: ProgressCallback | None,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    start_year = _resolve_stf_start_date(year=year, since_date=since_date)
    end_year = date(year, 12, 31)

    async def process_range(start: date, end: date) -> None:
        count_query = _stf_build_query(
            base=base,
            source_fields=source_fields,
            start=start,
            end=end,
            offset=0,
            size=0,
        )
        payload = await _stf_fetch_api(page, count_query)
        total = _stf_total_from_payload(payload)
        if total <= 0:
            return

        if total > ES_SAFE_WINDOW and start < end:
            mid = start + timedelta(days=(end - start).days // 2)
            await process_range(start, mid)
            await process_range(mid + timedelta(days=1), end)
            return

        capped = min(total, MAX_ES_WINDOW)
        offset = 0
        while offset < capped:
            page_query = _stf_build_query(
                base=base,
                source_fields=source_fields,
                start=start,
                end=end,
                offset=offset,
                size=PAGE_SIZE,
            )
            page_payload = await _stf_fetch_api(page, page_query)
            page_hits = _stf_hits_from_payload(page_payload)
            if not page_hits:
                break
            hits.extend(page_hits)
            offset += len(page_hits)
            _emit(
                progress_cb,
                "stf_fetch",
                f"STF {base}: {len(hits)} itens coletados.",
                stf_base=base,
                stf_collected=len(hits),
                stf_offset=offset,
                stf_total=capped,
            )

    await process_range(start_year, end_year)
    return hits


def _stf_doc_from_acordao(source: dict[str, Any]) -> UpdateDocument | None:
    raw_id = _normalize_space(str(source.get("id") or ""))
    if not raw_id:
        return None
    ementa = _clean_legal_text(source.get("ementa_texto") or "")
    tese = _clean_legal_text(source.get("documental_tese_texto") or "")
    tese_tema = _clean_legal_text(source.get("documental_tese_tema_texto") or "")
    indexacao = _clean_legal_text(source.get("documental_indexacao_texto") or "")
    legislacao_citada = _clean_legal_text(source.get("documental_legislacao_citada_texto") or "")
    titulo = _clean_legal_text(source.get("titulo") or "")
    classe = _normalize_space(str(source.get("processo_classe_processual_unificada_classe_sigla") or ""))
    numero = _normalize_space(str(source.get("processo_numero") or ""))
    processo = _normalize_space(f"{classe} {numero}") or titulo
    relator = _clean_legal_text(source.get("relator_processo_nome") or source.get("relator_acordao_nome") or "")
    url = _normalize_external_url(
        source.get("inteiro_teor_url"),
        base_url="https://jurisprudencia.stf.jus.br",
    )
    julgamento_data = _to_iso_date(str(source.get("julgamento_data") or ""))
    publicacao_data = _to_iso_date(str(source.get("publicacao_data") or ""))
    is_rg = bool(source.get("is_repercussao_geral"))
    marcacoes = _build_marcacoes(
        "stf",
        "acordao",
        classe,
        source.get("orgao_julgador"),
        tese_tema,
        indexacao,
        "repercussao_geral" if is_rg else "",
    )
    metadata = json.dumps(
        {
            "id": raw_id,
            "dg_unique": _normalize_space(str(source.get("dg_unique") or "")),
            "titulo": titulo,
            "classe": classe,
            "numero_processo": numero,
            "processo": processo,
            "julgamento_data": julgamento_data,
            "publicacao_data": publicacao_data,
            "orgao_julgador": _clean_legal_text(source.get("orgao_julgador") or ""),
            "relator_processo": _clean_legal_text(source.get("relator_processo_nome") or ""),
            "relator_acordao": _clean_legal_text(source.get("relator_acordao_nome") or ""),
            "tese_texto": tese,
            "tese_tema": tese_tema,
            "indexacao": indexacao,
            "legislacao_citada": legislacao_citada,
            "is_repercussao_geral": is_rg,
            "inteiro_teor_url": url,
            "marcacoes": marcacoes,
        },
        ensure_ascii=False,
    )
    return UpdateDocument(
        doc_id=f"stf-ac-{raw_id}",
        tribunal="STF",
        tipo="acordao",
        processo=processo,
        relator=relator,
        ramo_direito="",
        data_julgamento=julgamento_data,
        orgao_julgador=_clean_legal_text(source.get("orgao_julgador") or ""),
        texto_busca=f"{processo}\n{titulo}\n{tese_tema}\n{tese}\n{ementa}\n{indexacao}"[:8000],
        texto_integral=f"{ementa}\n\n{tese}"[:30000],
        url=url,
        metadata_extra=metadata,
        source_key="stf_acordaos",
    )


def _stf_doc_from_monocratica(source: dict[str, Any]) -> UpdateDocument | None:
    raw_id = _normalize_space(str(source.get("id") or ""))
    if not raw_id:
        return None
    decisao = _clean_legal_text(source.get("decisao_texto") or source.get("resumo_estruturado") or "")
    if not decisao:
        return None
    titulo = _clean_legal_text(source.get("titulo") or "")
    classe = _normalize_space(str(source.get("processo_classe_processual_unificada_classe_sigla") or ""))
    numero = _normalize_space(str(source.get("processo_numero") or ""))
    processo = _normalize_space(f"{classe} {numero}") or titulo
    url = _normalize_external_url(
        source.get("inteiro_teor_url"),
        base_url="https://jurisprudencia.stf.jus.br",
    )
    julgamento_data = _to_iso_date(str(source.get("julgamento_data") or ""))
    publicacao_data = _to_iso_date(str(source.get("publicacao_data") or ""))
    marcacoes = _build_marcacoes(
        "stf",
        "monocratica",
        classe,
        source.get("orgao_julgador") or "Decisao Monocratica",
        titulo,
    )
    metadata = json.dumps(
        {
            "id": raw_id,
            "dg_unique": _normalize_space(str(source.get("dg_unique") or "")),
            "titulo": titulo,
            "classe": classe,
            "numero_processo": numero,
            "processo": processo,
            "julgamento_data": julgamento_data,
            "publicacao_data": publicacao_data,
            "resumo_estruturado": _clean_legal_text(source.get("resumo_estruturado") or ""),
            "inteiro_teor_url": url,
            "marcacoes": marcacoes,
        },
        ensure_ascii=False,
    )
    return UpdateDocument(
        doc_id=f"stf-mon-{raw_id}",
        tribunal="STF",
        tipo="monocratica",
        processo=processo,
        relator=_clean_legal_text(source.get("relator_processo_nome") or ""),
        ramo_direito="",
        data_julgamento=julgamento_data or publicacao_data,
        orgao_julgador="Decisao Monocratica",
        texto_busca=f"{titulo}\n{decisao}"[:8000],
        texto_integral=decisao[:30000],
        url=url,
        metadata_extra=metadata,
        source_key="stf_monocraticas",
    )


def _stf_doc_from_informativo(source: dict[str, Any]) -> UpdateDocument | None:
    raw_id = _normalize_space(str(source.get("id") or ""))
    if not raw_id:
        return None
    resumo = _clean_legal_text(source.get("informativo_resumo_texto") or "")
    ementa = _clean_legal_text(source.get("ementa_texto") or "")
    tese = _clean_legal_text(source.get("documental_tese_texto") or "")
    titulo = _clean_legal_text(source.get("titulo") or "")
    classe = _normalize_space(str(source.get("processo_classe_processual_unificada_classe_sigla") or ""))
    numero = _normalize_space(str(source.get("processo_numero") or ""))
    processo = _clean_legal_text(source.get("processo_codigo_completo") or _normalize_space(f"{classe} {numero}") or titulo)
    relator = _clean_legal_text(source.get("relator_processo_nome") or source.get("relator_acordao_nome") or "")
    url = _normalize_external_url(
        source.get("inteiro_teor_url"),
        base_url="https://jurisprudencia.stf.jus.br",
    )
    data_julgamento = _to_iso_date(str(source.get("julgamento_data") or ""))
    data_publicacao = _to_iso_date(str(source.get("publicacao_data") or ""))
    if not data_julgamento:
        data_julgamento = data_publicacao
    marcacoes = _build_marcacoes(
        "stf",
        "informativo",
        classe,
        source.get("orgao_julgador"),
        source.get("informativo_numero"),
        source.get("informativo_titulo"),
        source.get("documental_tese_texto"),
    )
    metadata = json.dumps(
        {
            "id": raw_id,
            "dg_unique": _normalize_space(str(source.get("dg_unique") or "")),
            "titulo": titulo,
            "classe": classe,
            "numero_processo": numero,
            "processo_codigo_completo": _clean_legal_text(source.get("processo_codigo_completo") or ""),
            "informativo_numero": source.get("informativo_numero"),
            "informativo_titulo": source.get("informativo_titulo"),
            "informativo_data": source.get("informativo_data"),
            "informativo_observacao_texto": _clean_legal_text(source.get("informativo_observacao_texto") or ""),
            "julgamento_data": data_julgamento,
            "publicacao_data": data_publicacao,
            "orgao_julgador": _clean_legal_text(source.get("orgao_julgador") or ""),
            "relator_processo": _clean_legal_text(source.get("relator_processo_nome") or ""),
            "relator_acordao": _clean_legal_text(source.get("relator_acordao_nome") or ""),
            "tese_texto": tese,
            "inteiro_teor_url": url,
            "marcacoes": marcacoes,
        },
        ensure_ascii=False,
    )
    return UpdateDocument(
        doc_id=f"stf-info-{raw_id}",
        tribunal="STF",
        tipo="informativo",
        processo=processo,
        relator=relator,
        ramo_direito="",
        data_julgamento=data_julgamento,
        orgao_julgador=_clean_legal_text(source.get("orgao_julgador") or ""),
        texto_busca=f"{processo}\n{titulo}\n{tese}\n{ementa}\n{resumo}"[:8000],
        texto_integral=f"{ementa}\n\n{resumo}"[:30000],
        url=url,
        metadata_extra=metadata,
        source_key="stf_informativos",
    )


async def _collect_stf_documents_async(
    *,
    year: int,
    since_date: str,
    visible_browser: bool,
    chromium_executable_path: str | None,
    progress_cb: ProgressCallback | None,
    log_cb: LogCallback | None,
) -> tuple[list[UpdateDocument], dict[str, Any]]:
    docs: list[UpdateDocument] = []
    summary: dict[str, Any] = {
        "fetched_hits": 0,
        "candidate_docs": 0,
        "from_date": _resolve_stf_start_date(year=year, since_date=since_date).isoformat(),
        "latest_date": "",
        "by_base": {
            "acordaos": 0,
            "monocraticas": 0,
            "informativos": 0,
        },
    }
    launch_kwargs: dict[str, Any] = {
        "headless": not bool(visible_browser),
    }
    if chromium_executable_path:
        launch_kwargs["executable_path"] = chromium_executable_path

    _emit(
        progress_cb,
        "stf_bootstrap",
        "STF: abrindo Chromium para coletar jurisprudencia de 2026+.",
        stf_visible_browser=bool(visible_browser),
    )
    _log(log_cb, "stf_browser_launch", visible_browser=bool(visible_browser), executable_path=chromium_executable_path or "")

    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        try:
            await page.goto(STF_SEARCH_URL, wait_until="networkidle", timeout=90000)
            await page.wait_for_timeout(4000)

            acordao_hits = await _stf_collect_base_hits(
                page=page,
                base="acordaos",
                source_fields=STF_ACORDAO_FIELDS,
                year=year,
                since_date=summary["from_date"],
                progress_cb=progress_cb,
            )
            monocratica_hits = await _stf_collect_base_hits(
                page=page,
                base="decisoes",
                source_fields=STF_MONOCRATICA_FIELDS,
                year=year,
                since_date=summary["from_date"],
                progress_cb=progress_cb,
            )
            informativo_hits = await _stf_collect_base_hits(
                page=page,
                base="novo_informativo",
                source_fields=STF_INFORMATIVO_FIELDS,
                year=year,
                since_date=summary["from_date"],
                progress_cb=progress_cb,
            )
        finally:
            await context.close()
            await browser.close()

    all_dates: list[str] = []
    for hit in acordao_hits:
        source = hit.get("_source", {})
        if not isinstance(source, dict):
            continue
        doc = _stf_doc_from_acordao(source)
        if doc is None:
            continue
        if _extract_year(doc.data_julgamento or "") != year:
            continue
        docs.append(doc)
        all_dates.append(doc.data_julgamento)
    for hit in monocratica_hits:
        source = hit.get("_source", {})
        if not isinstance(source, dict):
            continue
        doc = _stf_doc_from_monocratica(source)
        if doc is None:
            continue
        if _extract_year(doc.data_julgamento or "") != year:
            continue
        docs.append(doc)
        all_dates.append(doc.data_julgamento)
    for hit in informativo_hits:
        source = hit.get("_source", {})
        if not isinstance(source, dict):
            continue
        doc = _stf_doc_from_informativo(source)
        if doc is None:
            continue
        info_year = _extract_year(doc.data_julgamento or "") or _extract_year(str(source.get("publicacao_data") or ""))
        if info_year != year:
            continue
        docs.append(doc)
        if doc.data_julgamento:
            all_dates.append(doc.data_julgamento)

    summary["fetched_hits"] = int(len(acordao_hits) + len(monocratica_hits) + len(informativo_hits))
    summary["candidate_docs"] = int(len(docs))
    summary["latest_date"] = _max_date_str(all_dates)
    summary["by_base"] = {
        "acordaos": len([d for d in docs if d.source_key == "stf_acordaos"]),
        "monocraticas": len([d for d in docs if d.source_key == "stf_monocraticas"]),
        "informativos": len([d for d in docs if d.source_key == "stf_informativos"]),
    }
    return docs, summary


def _collect_stf_documents(
    *,
    year: int,
    since_date: str,
    visible_browser: bool,
    chromium_executable_path: str | None,
    progress_cb: ProgressCallback | None,
    log_cb: LogCallback | None,
) -> tuple[list[UpdateDocument], dict[str, Any]]:
    return asyncio.run(
        _collect_stf_documents_async(
            year=year,
            since_date=since_date,
            visible_browser=visible_browser,
            chromium_executable_path=chromium_executable_path,
            progress_cb=progress_cb,
            log_cb=log_cb,
        )
    )


def _stj_parse_pt_br_date(raw: str) -> date | None:
    value = _normalize_space(_remove_accents(raw).lower())
    match = re.search(r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})", value)
    if not match:
        return None
    day = int(match.group(1))
    month_name = match.group(2)
    year = int(match.group(3))
    months = {
        "janeiro": 1,
        "fevereiro": 2,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    }
    month = months.get(month_name)
    if month is None:
        return None
    try:
        return date(year, month, day)
    except Exception:
        return None


def _stj_latest_edition(session: requests.Session) -> int:
    response = session.get(STJ_LIST_URL, timeout=60)
    response.raise_for_status()
    html_text = response.text
    editions = [int(x) for x in re.findall(r"GetPDFINFJ\?edicao=(\d{3,5})", html_text, flags=re.IGNORECASE)]
    if not editions:
        editions.extend(
            int(x)
            for x in re.findall(
                r"Informativo\s+de\s+Jurisprud[êe]ncia\s*n\.\s*(\d{3,5})",
                html_text,
                flags=re.IGNORECASE,
            )
        )
    if not editions:
        editions.extend(
            int(x)
            for x in re.findall(
                r"Informativo\s*n[ºo]?\s*(\d{3,5})",
                html_text,
                flags=re.IGNORECASE,
            )
        )
    if not editions:
        raise RuntimeError("Nao foi possivel identificar a ultima edicao do STJ.")
    return max(editions)


def _stj_fetch_edition_meta(session: requests.Session, edition: int) -> dict[str, Any]:
    url = STJ_EDITION_QUERY_URL.format(edition=edition)
    response = session.get(url, timeout=60)
    response.raise_for_status()
    html_text = response.text
    if "Nenhum documento encontrado" in html_text or "nenhum documento encontrado" in html_text.lower():
        return {"edition": edition, "found": False, "edition_date": ""}
    title_match = re.search(r"<title>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    title = _normalize_space(html.unescape(title_match.group(1) if title_match else ""))
    date_match = re.search(r"(\d{1,2}\s+de\s+[a-zA-Z\u00C0-\u017F]+\s+de\s+\d{4})", title)
    edition_date = _stj_parse_pt_br_date(date_match.group(1) if date_match else "")
    return {
        "edition": edition,
        "found": True,
        "title": title,
        "edition_date": edition_date.isoformat() if edition_date else "",
        "raw_html_len": len(html_text),
    }


def _stj_download_pdf(session: requests.Session, edition: int, target_path: Path) -> bool:
    url = STJ_EDITION_PDF_URL.format(edition=edition)
    response = session.get(url, timeout=90)
    response.raise_for_status()
    payload = response.content or b""
    if len(payload) < 1000:
        return False
    if not payload.startswith(b"%PDF-"):
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(payload)
    return True


def _stj_clean_pdf_text(raw_text: str) -> str:
    lines: list[str] = []
    for line in raw_text.splitlines():
        line = _normalize_space(line)
        if not line:
            lines.append("")
            continue
        lower = line.lower()
        if "processo.stj.jus.br/jurisprudencia/externo/informativo/" in lower:
            continue
        if re.fullmatch(r"\d+/\d+", line):
            continue
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _stj_extract_text(pdf_path: Path) -> str:
    with _get_fitz().open(pdf_path) as doc:
        pages = [doc.load_page(i).get_text("text") for i in range(doc.page_count)]
    return _stj_clean_pdf_text("\n".join(pages))


STJ_PROCESSO_RE = re.compile(
    r"\b((?:R?E?Sp|HC|RHC|RMS|CC|AgRg|AgInt|EDcl|AREsp|REsp|Pet|MC|RCL|Rcl|MS|EREsp|AI|AR|SE|CR|SD|RPV|SS|SLS)\b[^,\n]{0,60}?)",
    re.IGNORECASE,
)
STJ_RELATOR_RE = re.compile(
    r"Rel(?:ator)?\.?\s*(?:p/?\s*)?(?:[Aa]c[óo]rd[ãa]o\s*)?Min\.?\s*([A-ZÀ-ÖØ-öø-ÿ\s\.]+?)(?:,|\n|$)",
    re.IGNORECASE,
)
STJ_JULGAMENTO_RE = re.compile(r"julgado\s+em\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)
STJ_DJE_RE = re.compile(r"DJE(?:N)?(?:\s+de)?\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)
STJ_ORGAO_RE = re.compile(
    r"\b(Primeira\s+Turma|Segunda\s+Turma|Terceira\s+Turma|Quarta\s+Turma|Quinta\s+Turma|Sexta\s+Turma|Primeira\s+Se[cç][ãa]o|Segunda\s+Se[cç][ãa]o|Terceira\s+Se[cç][ãa]o|Corte\s+Especial)\b",
    re.IGNORECASE,
)
STJ_LEGACY_HEADING_RE = re.compile(r"\b(DIREITO\s+[A-ZÀ-ÖØ-öø-ÿ0-9,\-/\s]{3,220}?)\.(?=\s)")
STJ_RAMO_CHOICES = (
    "Administrativo",
    "Ambiental",
    "Civil",
    "Constitucional",
    "Consumidor",
    "Eleitoral",
    "Empresarial",
    "Internacional",
    "Outros",
    "Penal",
    "Previdenciario",
    "Processual Civil",
    "Processual Penal",
    "Trabalho",
    "Tributario",
)
STJ_RAMO_ALIAS = {
    "tributario": "Tributario",
    "previdenciario": "Previdenciario",
    "processual civil": "Processual Civil",
    "processual penal": "Processual Penal",
    "civil": "Civil",
    "penal": "Penal",
    "constitucional": "Constitucional",
    "administrativo": "Administrativo",
    "ambiental": "Ambiental",
    "consumidor": "Consumidor",
    "eleitoral": "Eleitoral",
    "empresarial": "Empresarial",
    "internacional": "Internacional",
    "trabalho": "Trabalho",
    "outros": "Outros",
}

STJ_PROCESS_CLASS_PATTERN = (
    r"(?:ProAfR|AgRg|AgInt|Ag|EDcl|EAREsp|EREsp|AREsp|REsp|RHC|HC|RMS|CC|Pet|MC|RCL|Rcl|MS|AI|AR|SE|CR|SD|RPV|SS|SLS|RO|APn|IDC|QC|TutCautAnt|PUIL|AC|RvCr|IF|Inq|HDE|MI|ExSusp|ExeMS|SEC|SIRDR)"
)
STJ_SECRET_PROCESSO_RE = re.compile(
    r"\bProcesso em segredo (?:(?:de )?justi[cç]a+|judicial)\b",
    re.IGNORECASE,
)
STJ_PROCESSO_RE = re.compile(
    rf"\b(({STJ_PROCESS_CLASS_PATTERN})(?:\s+(?:no|na|nos|nas)\s+{STJ_PROCESS_CLASS_PATTERN}){{0,2}}\s+\d[\d\.\-/A-Z]*)",
    re.IGNORECASE,
)
STJ_RELATOR_RE = re.compile(
    r"Rel(?:ator)?\.?\s*(?:p/?\s*)?(?:para\s+ac[óo]rd[ãa]o\s*)?"
    r"((?:Min\.?|Ministro|Ministra)\s+[A-ZÀ-ÖØ-öø-ÿ][A-ZÀ-ÖØ-öø-ÿ\s\.'-]+?)(?=\s*(?:,|\(|\n|$))",
    re.IGNORECASE,
)


def _clamp01(value: Any) -> float:
    try:
        num = float(value)
    except Exception:
        return 0.0
    if num < 0:
        return 0.0
    if num > 1:
        return 1.0
    return num


def _extract_first_json_object(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("Saida vazia do modelo.")
    start = text.find("{")
    if start < 0:
        raise ValueError(f"JSON nao encontrado na resposta do modelo: {text[:200]}")
    payload, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(payload, dict):
        raise ValueError(f"Resposta nao eh objeto JSON: {text[:200]}")
    return payload


def _is_quota_or_rate_limit_error(exc: Exception) -> bool:
    norm = _remove_accents(str(exc or "")).lower()
    indicators = (
        "resource_exhausted",
        "quota",
        "rate limit",
        "too many requests",
        "429",
        "401",
        "403",
        "permission_denied",
        "unauthenticated",
        "invalid api key",
        "api key not valid",
        "api_key_invalid",
        "billing",
        "disabled",
    )
    return any(token in norm for token in indicators)


def _stj_fix_common_ocr_glitches(name: str) -> str:
    clean = _normalize_space(name)
    if not clean:
        return ""
    lower = _remove_accents(clean).lower()
    if lower.startswith("min. "):
        return "Min. " + clean[5:].strip()
    if lower.startswith("ministro "):
        return "Ministro " + clean[9:].strip()
    if lower.startswith("ministra "):
        return "Ministra " + clean[9:].strip()
    if lower.startswith("istro "):
        return "Min" + clean
    if lower.startswith("inistro "):
        return "M" + clean
    if lower.startswith("inistra "):
        return "M" + clean
    return clean


def _stj_is_suspicious_processo(value: str) -> bool:
    text = _normalize_space(value)
    if not text:
        return True
    if any(ch.isdigit() for ch in text):
        return False
    tokens = text.split()
    if len(tokens) <= 2 and len(text) <= 16:
        return True
    return len(text) < 7


def _stj_is_suspicious_relator(value: str) -> bool:
    text = _normalize_space(value)
    if not text:
        return True
    normalized = _remove_accents(text).lower()
    if normalized.startswith(("istro ", "inistro ", "inistra ")):
        return True
    if len(text) < 8:
        return True
    return not bool(re.search(r"[A-Za-z]{3,}", text))


def _stj_normalize_ramo_value(value: str) -> str:
    text = _normalize_space(value)
    if not text:
        return ""
    normalized = _remove_accents(text).lower()
    mapped = STJ_RAMO_ALIAS.get(normalized)
    if mapped:
        return mapped
    classified = _classify_ramo(text)
    if classified in STJ_RAMO_CHOICES:
        return classified
    return ""


def _stj_sanitize_record_fields(record: dict[str, str]) -> dict[str, str]:
    safe = dict(record)
    safe["processo"] = _normalize_space(str(safe.get("processo") or ""))[:120]
    safe["ramo_direito"] = _normalize_space(str(safe.get("ramo_direito") or ""))[:60]
    safe["tema"] = _normalize_space(str(safe.get("tema") or ""))[:500]
    safe["destaque"] = _normalize_space(str(safe.get("destaque") or ""))[:2000]
    safe["relator"] = _stj_fix_common_ocr_glitches(str(safe.get("relator") or ""))[:100]
    safe["orgao_julgador"] = _normalize_space(str(safe.get("orgao_julgador") or ""))[:180]
    safe["data_julgamento"] = _normalize_space(str(safe.get("data_julgamento") or ""))[:20]
    safe["data_publicacao"] = _normalize_space(str(safe.get("data_publicacao") or ""))[:20]
    safe["texto_integral"] = str(safe.get("texto_integral") or "")[:120000]
    return safe


def _stj_record_needs_gemini_repair(record: dict[str, str]) -> bool:
    if _stj_is_suspicious_processo(str(record.get("processo") or "")):
        return True
    if _stj_is_suspicious_relator(str(record.get("relator") or "")):
        return True
    if not _normalize_space(str(record.get("orgao_julgador") or "")):
        return True
    if not _normalize_space(str(record.get("data_julgamento") or "")) and not _normalize_space(str(record.get("data_publicacao") or "")):
        return True
    ramo = _normalize_space(str(record.get("ramo_direito") or ""))
    if ramo in {"", "Outros"} and len(_normalize_space(str(record.get("texto_integral") or ""))) >= 1200:
        return True
    return False


def _stj_repair_prompt(record: dict[str, str]) -> str:
    excerpt = _clean_legal_text(record.get("texto_integral") or "")[:7000]
    snapshot = {
        "processo": record.get("processo"),
        "ramo_direito": record.get("ramo_direito"),
        "tema": record.get("tema"),
        "destaque": record.get("destaque"),
        "relator": record.get("relator"),
        "orgao_julgador": record.get("orgao_julgador"),
        "data_julgamento": record.get("data_julgamento"),
        "data_publicacao": record.get("data_publicacao"),
    }
    return (
        "Extraia e normalize os campos do informativo STJ abaixo. "
        "Retorne apenas JSON valido, sem markdown e sem comentarios.\n"
        "Regras:\n"
        "1) Use somente dados presentes no texto.\n"
        "2) Datas no formato DD/MM/AAAA quando existirem.\n"
        "3) ramo_direito deve ser um destes valores: "
        + ", ".join(STJ_RAMO_CHOICES)
        + ".\n"
        "4) Se nao souber, retorne string vazia.\n"
        "Formato JSON estrito:\n"
        "{"
        "\"processo\":\"\","
        "\"ramo_direito\":\"\","
        "\"tema\":\"\","
        "\"destaque\":\"\","
        "\"relator\":\"\","
        "\"orgao_julgador\":\"\","
        "\"data_julgamento\":\"\","
        "\"data_publicacao\":\"\","
        "\"confidence\":0.0"
        "}\n\n"
        f"Snapshot atual: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        f"Texto fonte:\n{excerpt}"
    )


def _stj_call_gemini_json(
    gemini_client: Any,
    *,
    model: str,
    prompt: str,
    max_retries: int = 2,
) -> dict[str, Any]:
    attempt = 0
    while True:
        try:
            response = gemini_client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.0),
            )
            return _extract_first_json_object(response.text or "")
        except Exception:
            if attempt >= max_retries:
                raise
            attempt += 1
            wait_s = min(2**attempt, 8)
            time.sleep(wait_s)


def _stj_merge_repair_payload(
    record: dict[str, str],
    payload: dict[str, Any],
    *,
    min_confidence: float,
) -> tuple[dict[str, str], bool]:
    confidence = _clamp01(payload.get("confidence"))
    if confidence < max(0.0, float(min_confidence or 0.0)):
        return record, False

    updated = dict(record)
    changed = False

    def get_text(key: str, max_chars: int) -> str:
        return _normalize_space(str(payload.get(key) or ""))[:max_chars]

    processo_new = get_text("processo", 120)
    if processo_new and (_stj_is_suspicious_processo(updated.get("processo", "")) or len(processo_new) > len(updated.get("processo", "")) + 4):
        updated["processo"] = processo_new
        changed = True

    relator_new = _stj_fix_common_ocr_glitches(get_text("relator", 100))
    if relator_new and (_stj_is_suspicious_relator(updated.get("relator", "")) or len(relator_new) > len(updated.get("relator", "")) + 2):
        updated["relator"] = relator_new
        changed = True

    orgao_new = get_text("orgao_julgador", 180)
    if orgao_new and not _normalize_space(updated.get("orgao_julgador", "")):
        updated["orgao_julgador"] = orgao_new
        changed = True

    data_julg_new = get_text("data_julgamento", 20)
    if data_julg_new and not _normalize_space(updated.get("data_julgamento", "")):
        updated["data_julgamento"] = data_julg_new
        changed = True

    data_pub_new = get_text("data_publicacao", 20)
    if data_pub_new and not _normalize_space(updated.get("data_publicacao", "")):
        updated["data_publicacao"] = data_pub_new
        changed = True

    tema_new = get_text("tema", 500)
    if tema_new and (not _normalize_space(updated.get("tema", "")) or len(tema_new) > len(updated.get("tema", "")) + 12):
        updated["tema"] = tema_new
        changed = True

    destaque_new = get_text("destaque", 2000)
    if destaque_new and (not _normalize_space(updated.get("destaque", "")) or len(destaque_new) > len(updated.get("destaque", "")) + 20):
        updated["destaque"] = destaque_new
        changed = True

    ramo_new = _stj_normalize_ramo_value(get_text("ramo_direito", 60))
    ramo_old = _normalize_space(updated.get("ramo_direito", ""))
    if ramo_new and (ramo_old in {"", "Outros"}):
        updated["ramo_direito"] = ramo_new
        changed = True

    return _stj_sanitize_record_fields(updated), changed


def _stj_repair_records_with_gemini(
    *,
    records: list[dict[str, str]],
    gemini_client: Any | None,
    model: str,
    min_confidence: float,
    max_records: int,
    progress_cb: ProgressCallback | None,
    log_cb: LogCallback | None,
    source_pdf: str,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    if not records:
        return records, {"attempted": 0, "applied": 0, "failed": 0}
    sanitized = [_stj_sanitize_record_fields(item) for item in records]
    if gemini_client is None:
        return sanitized, {"attempted": 0, "applied": 0, "failed": 0}

    attempted = 0
    applied = 0
    failed = 0
    capped_max = max(0, int(max_records or 0))
    repaired: list[dict[str, str]] = []

    for idx, record in enumerate(sanitized, 1):
        current = dict(record)
        if not _stj_record_needs_gemini_repair(current):
            repaired.append(current)
            continue
        if attempted >= capped_max:
            repaired.append(current)
            continue
        attempted += 1
        _emit(
            progress_cb,
            "stj_repair",
            f"STJ: reparo Gemini (3-flash) no item {idx}/{len(sanitized)} de {source_pdf}.",
            stj_repair_index=idx,
            stj_repair_total=len(sanitized),
            stj_repair_attempted=attempted,
        )
        try:
            payload = _stj_call_gemini_json(
                gemini_client,
                model=model,
                prompt=_stj_repair_prompt(current),
            )
            merged, changed = _stj_merge_repair_payload(
                current,
                payload,
                min_confidence=min_confidence,
            )
            if changed:
                applied += 1
            repaired.append(merged)
        except Exception as exc:
            failed += 1
            _log(
                log_cb,
                "stj_repair_failed",
                source_pdf=source_pdf,
                item_index=idx,
                error=str(exc),
            )
            repaired.append(current)

    return repaired, {"attempted": attempted, "applied": applied, "failed": failed}


def _stj_extract_processo(text: str) -> str:
    normalized = _normalize_space(text or "")
    if not normalized:
        return ""
    if STJ_SECRET_PROCESSO_RE.search(normalized):
        return "Processo em segredo de justiça"
    match = STJ_PROCESSO_RE.search(normalized)
    if not match:
        return ""
    return _normalize_space(re.sub(r"[,\.\s]+$", "", match.group(1)))[:120]


def _stj_extract_relator(text: str) -> str:
    match = STJ_RELATOR_RE.search(_normalize_space(text or ""))
    if not match:
        return ""
    clean = _normalize_space(re.sub(r"[,\.\s]+$", "", match.group(1)))[:100]
    return _stj_fix_common_ocr_glitches(clean)


def _stj_extract_julgamento(text: str) -> str:
    match = STJ_JULGAMENTO_RE.search(text or "")
    return _normalize_space(match.group(1)) if match else ""


def _stj_extract_publicacao(text: str) -> str:
    match = STJ_DJE_RE.search(text or "")
    return _normalize_space(match.group(1)) if match else ""


def _stj_extract_orgao(text: str) -> str:
    match = STJ_ORGAO_RE.search(text or "")
    return _normalize_space(match.group(1)) if match else ""


def _stj_parse_new_format(text: str, source_pdf: str, info_num: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    markers = list(re.finditer(r"(?m)^PROCESSO\s*$", text))
    for idx, marker in enumerate(markers):
        start = marker.start()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
        block = text[start:end].strip()
        if len(block.split()) < 40:
            continue
        proc_match = re.search(
            r"^PROCESSO\s*\n(.*?)(?=\nRAMO DO DIREITO\b|\nTEMA\b|\nDESTAQUE\b|$)",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        processo_line = _normalize_space(proc_match.group(1) if proc_match else "")
        ramo_match = re.search(
            r"RAMO DO DIREITO\s*(.*?)(?:\nTEMA\b|\nDESTAQUE\b|\nINFORMA[ÇC][ÕO]ES\b|$)",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        ramo_raw = _normalize_space(ramo_match.group(1) if ramo_match else "")
        tema_match = re.search(
            r"\bTEMA\s*\n(.*?)(?=\nDESTAQUE\b|\nINFORMA[ÇC][ÕO]ES\b|$)",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        tema = _normalize_space(tema_match.group(1) if tema_match else "")
        destaque_match = re.search(
            r"\bDESTAQUE\s*\n(.*?)(?=\nINFORMA[ÇC][ÕO]ES DO INTEIRO TEOR\b|$)",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        destaque = _normalize_space(destaque_match.group(1) if destaque_match else "")
        records.append(
            {
                "informativo_numero": info_num,
                "source_pdf": source_pdf,
                "processo": _stj_extract_processo(processo_line) or _stj_extract_processo(block),
                "ramo_direito": _classify_ramo(ramo_raw),
                "tema": tema[:500],
                "destaque": destaque[:2000],
                "relator": _stj_extract_relator(processo_line) or _stj_extract_relator(block),
                "orgao_julgador": _stj_extract_orgao(block),
                "data_julgamento": _stj_extract_julgamento(processo_line) or _stj_extract_julgamento(block),
                "data_publicacao": _stj_extract_publicacao(processo_line) or _stj_extract_publicacao(block),
                "texto_integral": block[:120000],
            }
        )
    return records


def _stj_parse_legacy_format(text: str, source_pdf: str, info_num: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    matches = list(STJ_LEGACY_HEADING_RE.finditer(text))
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if len(block.split()) < 40:
            continue
        ramo_raw = _normalize_space(match.group(1))
        records.append(
            {
                "informativo_numero": info_num,
                "source_pdf": source_pdf,
                "processo": _stj_extract_processo(block),
                "ramo_direito": _classify_ramo(ramo_raw),
                "tema": "",
                "destaque": "",
                "relator": _stj_extract_relator(block),
                "orgao_julgador": _stj_extract_orgao(block),
                "data_julgamento": _stj_extract_julgamento(block),
                "data_publicacao": _stj_extract_publicacao(block),
                "texto_integral": block[:120000],
            }
        )
    return records


def _stj_extract_info_number(filename: str) -> str:
    match = re.search(r"Informativo_(\d+)\.pdf$", filename, flags=re.IGNORECASE)
    if not match:
        return "N_D"
    try:
        return str(int(match.group(1)))
    except Exception:
        return match.group(1)


def _ensure_stj_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stj_informativos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            informativo_numero TEXT,
            source_pdf TEXT,
            processo TEXT,
            ramo_direito TEXT,
            tema TEXT,
            destaque TEXT,
            relator TEXT,
            orgao_julgador TEXT,
            data_julgamento TEXT,
            data_publicacao TEXT,
            texto_integral TEXT,
            tribunal TEXT DEFAULT 'STJ',
            extracted_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stj_info_source_pdf ON stj_informativos(source_pdf)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stj_info_num ON stj_informativos(informativo_numero)")
    conn.commit()


def _insert_stj_pdf_records(
    conn: sqlite3.Connection,
    pdf_path: Path,
    *,
    gemini_client: Any | None,
    repair_model: str,
    repair_min_confidence: float,
    repair_max_records: int,
    progress_cb: ProgressCallback | None,
    log_cb: LogCallback | None,
) -> tuple[list[int], dict[str, int]]:
    source_pdf = pdf_path.name
    exists = conn.execute(
        "SELECT COUNT(*) FROM stj_informativos WHERE source_pdf = ?",
        (source_pdf,),
    ).fetchone()
    if int(exists[0] or 0) > 0:
        return [], {"attempted": 0, "applied": 0, "failed": 0}

    text = _stj_extract_text(pdf_path)
    info_num = _stj_extract_info_number(source_pdf)
    records = _stj_parse_new_format(text, source_pdf, info_num) if "RAMO DO DIREITO" in text else _stj_parse_legacy_format(text, source_pdf, info_num)
    if not records and text.strip():
        records = [
            {
                "informativo_numero": info_num,
                "source_pdf": source_pdf,
                "processo": _stj_extract_processo(text),
                "ramo_direito": "Outros",
                "tema": "",
                "destaque": "",
                "relator": _stj_extract_relator(text),
                "orgao_julgador": _stj_extract_orgao(text),
                "data_julgamento": _stj_extract_julgamento(text),
                "data_publicacao": _stj_extract_publicacao(text),
                "texto_integral": text[:120000],
            }
        ]
    if not records:
        return [], {"attempted": 0, "applied": 0, "failed": 0}

    records = [_stj_sanitize_record_fields(row) for row in records]
    repaired_records, repair_stats = _stj_repair_records_with_gemini(
        records=records,
        gemini_client=gemini_client,
        model=repair_model or DEFAULT_STJ_REPAIR_MODEL,
        min_confidence=float(repair_min_confidence or DEFAULT_STJ_REPAIR_MIN_CONFIDENCE),
        max_records=int(repair_max_records or DEFAULT_STJ_REPAIR_MAX_RECORDS_PER_PDF),
        progress_cb=progress_cb,
        log_cb=log_cb,
        source_pdf=source_pdf,
    )

    now = datetime.now().isoformat()
    inserted_ids: list[int] = []
    cursor = conn.cursor()
    for row in repaired_records:
        cursor.execute(
            """
            INSERT INTO stj_informativos (
                informativo_numero, source_pdf, processo, ramo_direito, tema, destaque,
                relator, orgao_julgador, data_julgamento, data_publicacao, texto_integral,
                tribunal, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STJ', ?)
            """,
            (
                row["informativo_numero"],
                row["source_pdf"],
                row["processo"],
                row["ramo_direito"],
                row["tema"],
                row["destaque"],
                row["relator"],
                row["orgao_julgador"],
                row["data_julgamento"],
                row["data_publicacao"],
                row["texto_integral"],
                now,
            ),
        )
        inserted_ids.append(int(cursor.lastrowid))
    conn.commit()
    return inserted_ids, repair_stats


def _stj_verify_expected_editions(
    conn: sqlite3.Connection,
    *,
    expected_editions: list[int],
) -> dict[str, Any]:
    expected = sorted({int(x) for x in expected_editions if int(x) > 0})
    missing: list[int] = []
    present: list[int] = []
    for edition in expected:
        source_pdf = f"Informativo_{edition:04d}.pdf"
        row = conn.execute(
            "SELECT COUNT(*) FROM stj_informativos WHERE source_pdf = ?",
            (source_pdf,),
        ).fetchone()
        count = int(row[0] or 0) if row else 0
        if count > 0:
            present.append(edition)
        else:
            missing.append(edition)
    return {
        "expected_total": len(expected),
        "present_total": len(present),
        "missing_total": len(missing),
        "missing_editions": missing,
    }


def _load_stj_docs_by_ids(conn: sqlite3.Connection, row_ids: list[int]) -> list[UpdateDocument]:
    if not row_ids:
        return []
    placeholders = ",".join("?" for _ in row_ids)
    rows = conn.execute(
        f"SELECT * FROM stj_informativos WHERE id IN ({placeholders}) ORDER BY id",
        tuple(row_ids),
    ).fetchall()
    docs: list[UpdateDocument] = []
    for row in rows:
        r = dict(row)
        destaque = _clean_legal_text(r.get("destaque") or "")
        tema = _clean_legal_text(r.get("tema") or "")
        texto_integral = _clean_legal_text(r.get("texto_integral") or "")
        processo = _clean_legal_text(r.get("processo") or "")
        relator = _clean_legal_text(r.get("relator") or "")
        orgao = _clean_legal_text(r.get("orgao_julgador") or "")
        ramo = _clean_legal_text(r.get("ramo_direito") or "")
        info_num = _normalize_space(str(r.get("informativo_numero") or ""))
        source_pdf = _normalize_space(str(r.get("source_pdf") or ""))
        pdf_url = _stj_pdf_url_from_info_num(info_num) or _stj_pdf_url_from_info_num(_stj_extract_info_number(source_pdf))
        data_julgamento = _to_iso_date(str(r.get("data_julgamento") or ""))
        data_publicacao = _to_iso_date(str(r.get("data_publicacao") or ""))
        if not data_julgamento:
            data_julgamento = data_publicacao
        marcacoes = _build_marcacoes(
            "stj",
            "informativo",
            ramo,
            tema,
            orgao,
            f"informativo_{info_num}" if info_num else "",
        )
        texto_busca_parts = [processo, tema, destaque]
        if destaque:
            texto_busca_parts.append(texto_integral[:4000])
        else:
            texto_busca_parts.append(texto_integral[:8000])
        texto_busca = "\n".join(part for part in texto_busca_parts if part).strip()[:8000]
        metadata = json.dumps(
            {
                "informativo_numero": info_num,
                "source_pdf": source_pdf,
                "edicao": info_num,
                "tema": tema,
                "destaque": destaque,
                "processo": processo,
                "relator": relator,
                "orgao_julgador": orgao,
                "ramo_direito": ramo,
                "data_julgamento": data_julgamento,
                "data_publicacao": data_publicacao,
                "pdf_url": pdf_url,
                "marcacoes": marcacoes,
            },
            ensure_ascii=False,
        )
        docs.append(
            UpdateDocument(
                doc_id=f"stj-info-{r.get('id')}",
                tribunal="STJ",
                tipo="informativo",
                processo=processo,
                relator=relator,
                ramo_direito=ramo,
                data_julgamento=data_julgamento,
                orgao_julgador=orgao,
                texto_busca=texto_busca,
                texto_integral=texto_integral[:30000],
                url=pdf_url,
                metadata_extra=metadata,
                source_key="stj_informativos",
            )
        )
    return docs


def _collect_stj_documents(
    *,
    project_root: Path,
    year: int,
    gemini_client: Any | None,
    repair_with_gemini: bool,
    repair_model: str,
    repair_min_confidence: float,
    repair_max_records_per_pdf: int,
    strict_completeness: bool,
    progress_cb: ProgressCallback | None,
    log_cb: LogCallback | None,
) -> tuple[list[UpdateDocument], dict[str, Any]]:
    docs: list[UpdateDocument] = []
    summary: dict[str, Any] = {
        "latest_edition": 0,
        "latest_date": "",
        "downloaded_editions": 0,
        "inserted_rows": 0,
        "candidate_docs": 0,
        "repair_attempted": 0,
        "repair_applied": 0,
        "repair_failed": 0,
        "repair_model": repair_model if repair_with_gemini else "",
        "expected_editions_total": 0,
        "missing_editions_total": 0,
        "missing_editions": [],
        "strict_completeness": bool(strict_completeness),
    }
    _internal = project_root / "_internal"
    data_base = _internal / "data" if (_internal / "data").is_dir() else project_root / "data"
    data_dir = data_base / "stj_informativos"
    docs_dir = data_dir / "docs"
    db_path = data_dir / "stj_informativos.db"
    data_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            )
        }
    )
    # Bundled Python (PyInstaller) may lack proper CA certs for Cloudflare-protected
    # sites like STJ.  Try with default certs first; on SSL error fall back to
    # verify=False so the pipeline isn't blocked.
    try:
        session.get("https://processo.stj.jus.br/", timeout=15)
    except requests.exceptions.SSLError:
        _log(log_cb, "stj_ssl_fallback", hint="SSL verification disabled for STJ requests (bundled cert issue)")
        session.verify = False

    _emit(progress_cb, "stj_discovery", "STJ: verificando ultima edicao publicada.")
    latest_edition = _stj_latest_edition(session)
    summary["latest_edition"] = int(latest_edition)
    try:
        latest_meta = _stj_fetch_edition_meta(session, latest_edition)
        latest_meta_date = str(latest_meta.get("edition_date") or "")
        if _extract_year(latest_meta_date) == year:
            summary["latest_date"] = latest_meta_date
    except Exception:
        pass

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_stj_schema(conn)
        max_in_db_row = conn.execute(
            "SELECT MAX(CAST(informativo_numero AS INTEGER)) FROM stj_informativos"
        ).fetchone()
        max_in_db = int(max_in_db_row[0] or 0)
        start_edition = max(max_in_db + 1, 1)
        all_row_ids: list[int] = []
        latest_dates: list[str] = []
        expected_editions: list[int] = []

        for edition in range(start_edition, latest_edition + 1):
            meta = _stj_fetch_edition_meta(session, edition)
            if not meta.get("found"):
                continue
            edition_date = str(meta.get("edition_date") or "")
            if _extract_year(edition_date) != year:
                continue
            expected_editions.append(int(edition))
            latest_dates.append(edition_date)
            pdf_path = docs_dir / f"Informativo_{edition:04d}.pdf"
            _emit(
                progress_cb,
                "stj_download",
                f"STJ: baixando edicao {edition:04d}.",
                stj_edition=edition,
            )
            ok = _stj_download_pdf(session, edition, pdf_path)
            if not ok:
                _log(log_cb, "stj_pdf_missing", edition=edition)
                continue
            summary["downloaded_editions"] = int(summary["downloaded_editions"] or 0) + 1
            row_ids, repair_stats = _insert_stj_pdf_records(
                conn,
                pdf_path,
                gemini_client=gemini_client if repair_with_gemini else None,
                repair_model=repair_model,
                repair_min_confidence=repair_min_confidence,
                repair_max_records=repair_max_records_per_pdf,
                progress_cb=progress_cb,
                log_cb=log_cb,
            )
            if not row_ids:
                continue
            all_row_ids.extend(row_ids)
            summary["inserted_rows"] = int(summary["inserted_rows"] or 0) + len(row_ids)
            summary["repair_attempted"] = int(summary.get("repair_attempted") or 0) + int(repair_stats.get("attempted") or 0)
            summary["repair_applied"] = int(summary.get("repair_applied") or 0) + int(repair_stats.get("applied") or 0)
            summary["repair_failed"] = int(summary.get("repair_failed") or 0) + int(repair_stats.get("failed") or 0)

        completeness = _stj_verify_expected_editions(conn, expected_editions=expected_editions)
        summary["expected_editions_total"] = int(completeness.get("expected_total") or 0)
        summary["missing_editions_total"] = int(completeness.get("missing_total") or 0)
        summary["missing_editions"] = list(completeness.get("missing_editions") or [])

        if bool(strict_completeness) and summary["missing_editions_total"] > 0:
            missing_preview = ", ".join(f"{int(x):04d}" for x in summary["missing_editions"][:12])
            raise RuntimeError(
                "Coleta STJ incompleta: edicoes esperadas sem registros no banco "
                f"({summary['missing_editions_total']} faltando). Edicoes: {missing_preview}"
            )

        docs = _load_stj_docs_by_ids(conn, all_row_ids)

        # ── Reconciliation: include orphan records (in SQLite but not in LanceDB) ──
        # This handles cases where a previous run downloaded editions to SQLite
        # but the embedding/upsert step failed (e.g., API quota, crash).
        try:
            all_sqlite_rows = conn.execute(
                "SELECT id FROM stj_informativos ORDER BY id"
            ).fetchall()
            all_sqlite_ids = [int(r[0]) for r in all_sqlite_rows]
            already_loaded = {int(d.doc_id.replace("stj-info-", "")) for d in docs if d.doc_id.startswith("stj-info-")}
            orphan_ids = [rid for rid in all_sqlite_ids if rid not in already_loaded]
            if orphan_ids:
                orphan_docs = _load_stj_docs_by_ids(conn, orphan_ids)
                docs.extend(orphan_docs)
                _log(log_cb, "stj_reconcile", orphan_count=len(orphan_docs),
                     hint=f"Reconciling {len(orphan_docs)} orphan STJ records from SQLite")
        except Exception as exc:
            _log(log_cb, "stj_reconcile_error", error=str(exc))

        summary["candidate_docs"] = int(len(docs))
        summary["latest_date"] = _max_date_str(latest_dates + [str(summary.get("latest_date") or "")])
    finally:
        conn.close()

    return docs, summary


def _lancedb_open_ratio_table(project_root: Path):
    _internal = project_root / "_internal"
    lance_dir = _internal / "lancedb_store" if (_internal / "lancedb_store").is_dir() else project_root / "lancedb_store"
    db = lancedb.connect(str(lance_dir))
    return db.open_table(LANCE_TABLE_NAME)


def _quote_sql_literal(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _existing_doc_ids(table: Any, candidate_ids: list[str]) -> set[str]:
    existing: set[str] = set()
    if not candidate_ids:
        return existing
    chunk_size = 120
    for start in range(0, len(candidate_ids), chunk_size):
        batch = candidate_ids[start : start + chunk_size]
        if not batch:
            continue
        where_clause = "doc_id IN (" + ", ".join(_quote_sql_literal(x) for x in batch) + ")"
        try:
            rows = table.search().where(where_clause, prefilter=True).limit(len(batch)).to_list()
        except Exception:
            rows = []
            for doc_id in batch:
                probe = "doc_id = " + _quote_sql_literal(doc_id)
                try:
                    single = table.search().where(probe, prefilter=True).limit(1).to_list()
                except Exception:
                    single = []
                rows.extend(single)
        for row in rows:
            raw = _normalize_space(str(row.get("doc_id") or ""))
            if raw:
                existing.add(raw)
    return existing


def _missing_doc_ids(table: Any, candidate_ids: list[str]) -> list[str]:
    ordered_unique = list(dict.fromkeys([str(x or "").strip() for x in candidate_ids if str(x or "").strip()]))
    if not ordered_unique:
        return []
    existing = _existing_doc_ids(table, ordered_unique)
    return [doc_id for doc_id in ordered_unique if doc_id not in existing]


_TOKEN_HASH_RE = re.compile(r"[a-z0-9]{2,}")


def _tokenize_for_hash_embedding(text: str) -> list[str]:
    normalized = _remove_accents(_normalize_space(text).lower())
    return _TOKEN_HASH_RE.findall(normalized)


def _hash_embed_text(text: str, *, dim: int = EMBED_DIM) -> list[float]:
    tokens = _tokenize_for_hash_embedding(text)
    vec = [0.0] * dim
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
        idx = int.from_bytes(digest[:4], "big", signed=False) % dim
        sign = 1.0 if (digest[4] % 2 == 0) else -1.0
        weight = 1.0 + ((digest[5] % 9) / 10.0)
        vec[idx] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0:
        return vec
    return [float(v / norm) for v in vec]


def _records_from_docs_with_vectors(
    *,
    docs: list[UpdateDocument],
    vectors: list[list[float]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for doc, vector in zip(docs, vectors):
        records.append(
            {
                "vector": vector,
                "doc_id": doc.doc_id,
                "tribunal": doc.tribunal,
                "tipo": doc.tipo,
                "processo": doc.processo,
                "relator": doc.relator,
                "ramo_direito": doc.ramo_direito,
                "data_julgamento": doc.data_julgamento,
                "orgao_julgador": doc.orgao_julgador,
                "texto_busca": doc.texto_busca,
                "texto_integral": doc.texto_integral,
                "url": doc.url,
                "metadata_extra": doc.metadata_extra,
            }
        )
    return records


def _embed_docs(
    *,
    docs: list[UpdateDocument],
    gemini_client: Any,
    embed_model: str,
    embed_batch_size: int,
    fallback_on_quota: bool,
    progress_cb: ProgressCallback | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    stats = {"gemini": 0, "hash": 0}
    total = len(docs)
    batch_size = max(1, min(int(embed_batch_size or DEFAULT_EMBED_BATCH_SIZE), 64))
    for start in range(0, total, batch_size):
        batch = docs[start : start + batch_size]
        texts = [doc.texto_busca for doc in batch]
        backend = "gemini"
        try:
            result = gemini_client.models.embed_content(
                model=embed_model,
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=EMBED_DIM,
                ),
            )
            vectors = [list(item.values) for item in (result.embeddings or [])]
            if len(vectors) != len(batch):
                raise RuntimeError("Falha ao gerar embeddings de todos os documentos do lote.")
        except Exception as exc:
            if not fallback_on_quota or not _is_quota_or_rate_limit_error(exc):
                raise
            backend = "hash"
            vectors = [_hash_embed_text(text, dim=EMBED_DIM) for text in texts]
            _emit(
                progress_cb,
                "embed_fallback",
                "Cota de embeddings Gemini atingida; aplicando fallback hash para nao interromper a atualizacao.",
                embed_backend="hash",
                embed_batch_start=start,
            )
        records.extend(_records_from_docs_with_vectors(docs=batch, vectors=vectors))
        stats[backend] = int(stats.get(backend) or 0) + len(batch)
        _emit(
            progress_cb,
            "embed",
            f"Embeddings: {min(total, start + batch_size)}/{total}.",
            embedded=min(total, start + batch_size),
            embed_total=total,
            embed_backend=backend,
        )
    return records, stats


def _upsert_ratio_records(table: Any, records: list[dict[str, Any]]) -> dict[str, int]:
    if not records:
        return {"inserted": 0, "updated": 0}
    before = int(table.count_rows())
    (
        table.merge_insert("doc_id")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .execute(records)
    )
    after = int(table.count_rows())
    inserted = max(0, after - before)
    updated = max(0, len(records) - inserted)
    try:
        table.create_fts_index("texto_busca", use_tantivy=False, replace=True)
    except Exception:
        pass
    return {"inserted": inserted, "updated": updated}


def run_jurisprudencia_incremental_update(
    *,
    project_root: Path,
    gemini_client: Any,
    year: int = 2026,
    include_stf: bool = True,
    include_stj: bool = True,
    stf_visible_browser: bool = True,
    chromium_executable_path: str | None = None,
    stf_since_date: str = "",
    embed_model: str = "gemini-embedding-001",
    embed_batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
    stj_repair_with_gemini: bool = True,
    stj_repair_model: str = DEFAULT_STJ_REPAIR_MODEL,
    stj_repair_min_confidence: float = DEFAULT_STJ_REPAIR_MIN_CONFIDENCE,
    stj_repair_max_records_per_pdf: int = DEFAULT_STJ_REPAIR_MAX_RECORDS_PER_PDF,
    strict_completeness: bool = DEFAULT_STRICT_COMPLETENESS,
    embed_fallback_on_quota: bool = True,
    progress_cb: ProgressCallback | None = None,
    log_cb: LogCallback | None = None,
) -> dict[str, Any]:
    started_at = datetime.now().isoformat()
    summary: dict[str, Any] = {
        "year": int(year),
        "started_at": started_at,
        "finished_at": "",
        "include_stf": bool(include_stf),
        "include_stj": bool(include_stj),
        "stf_visible_browser": bool(stf_visible_browser),
        "stj_repair_with_gemini": bool(stj_repair_with_gemini),
        "stj_repair_model": stj_repair_model if stj_repair_with_gemini else "",
        "strict_completeness": bool(strict_completeness),
        "embed_fallback_on_quota": bool(embed_fallback_on_quota),
        "stf": {},
        "stj": {},
        "upsert": {"inserted": 0, "updated": 0, "embedded": 0, "embedded_gemini": 0, "embedded_hash": 0},
        "latest_dates": {"stf": "", "stj": ""},
        "since_dates": {"stf": _resolve_stf_start_date(year=year, since_date=stf_since_date).isoformat()},
        "message": "",
    }

    table = _lancedb_open_ratio_table(project_root)
    all_candidate_docs: list[UpdateDocument] = []

    if include_stf:
        _emit(
            progress_cb,
            "stf_start",
            "Iniciando coleta STF (janela Chromium visivel).",
            stf_visible_browser=bool(stf_visible_browser),
        )
        stf_docs, stf_summary = _collect_stf_documents(
            year=year,
            since_date=summary["since_dates"]["stf"],
            visible_browser=stf_visible_browser,
            chromium_executable_path=chromium_executable_path,
            progress_cb=progress_cb,
            log_cb=log_cb,
        )
        summary["stf"] = stf_summary
        summary["latest_dates"]["stf"] = str(stf_summary.get("latest_date") or "")
        all_candidate_docs.extend(stf_docs)
        _emit(
            progress_cb,
            "stf_done",
            f"STF concluido: {len(stf_docs)} candidatos de {year}.",
            stf_candidates=len(stf_docs),
            stf_latest_date=summary["latest_dates"]["stf"],
        )

    if include_stj:
        _emit(progress_cb, "stj_start", "Iniciando coleta STJ (informativos 2026+).")
        stj_docs, stj_summary = _collect_stj_documents(
            project_root=project_root,
            year=year,
            gemini_client=gemini_client,
            repair_with_gemini=bool(stj_repair_with_gemini),
            repair_model=stj_repair_model or DEFAULT_STJ_REPAIR_MODEL,
            repair_min_confidence=float(stj_repair_min_confidence or DEFAULT_STJ_REPAIR_MIN_CONFIDENCE),
            repair_max_records_per_pdf=int(stj_repair_max_records_per_pdf or DEFAULT_STJ_REPAIR_MAX_RECORDS_PER_PDF),
            strict_completeness=bool(strict_completeness),
            progress_cb=progress_cb,
            log_cb=log_cb,
        )
        summary["stj"] = stj_summary
        summary["latest_dates"]["stj"] = str(stj_summary.get("latest_date") or "")
        all_candidate_docs.extend(stj_docs)
        _emit(
            progress_cb,
            "stj_done",
            f"STJ concluido: {len(stj_docs)} candidatos de {year}.",
            stj_candidates=len(stj_docs),
            stj_latest_date=summary["latest_dates"]["stj"],
        )

    unique_by_id: dict[str, UpdateDocument] = {}
    for doc in all_candidate_docs:
        unique_by_id[doc.doc_id] = doc
    deduped_docs = list(unique_by_id.values())
    existing_ids = _existing_doc_ids(table, list(unique_by_id.keys()))
    docs_to_index = [doc for doc in deduped_docs if doc.doc_id not in existing_ids]

    if not docs_to_index:
        summary["message"] = (
            f"Nenhum novo documento de {year} para indexar. "
            "A base ja esta atualizada para os itens encontrados no STF/STJ."
        )
        summary["finished_at"] = datetime.now().isoformat()
        return summary

    _emit(
        progress_cb,
        "embed_start",
        f"Gerando embeddings para {len(docs_to_index)} documento(s) novos.",
        docs_new=len(docs_to_index),
    )
    records, embed_stats = _embed_docs(
        docs=docs_to_index,
        gemini_client=gemini_client,
        embed_model=embed_model,
        embed_batch_size=embed_batch_size,
        fallback_on_quota=bool(embed_fallback_on_quota),
        progress_cb=progress_cb,
    )
    summary["upsert"]["embedded"] = int(len(records))
    summary["upsert"]["embedded_gemini"] = int(embed_stats.get("gemini") or 0)
    summary["upsert"]["embedded_hash"] = int(embed_stats.get("hash") or 0)

    _emit(
        progress_cb,
        "upsert_start",
        f"Gravando {len(records)} documento(s) no LanceDB.",
        records=len(records),
    )
    upsert_stats = _upsert_ratio_records(table, records)
    summary["upsert"]["inserted"] = int(upsert_stats.get("inserted") or 0)
    summary["upsert"]["updated"] = int(upsert_stats.get("updated") or 0)

    expected_ids = list(unique_by_id.keys())
    missing_ids = _missing_doc_ids(table, expected_ids)
    integrity: dict[str, Any] = {
        "expected_docs": len(expected_ids),
        "missing_after_first_upsert": len(missing_ids),
        "missing_after_retry": 0,
        "reconcile_retry_docs": 0,
        "missing_doc_ids_preview": list(missing_ids[:25]),
    }
    summary["integrity"] = integrity

    if missing_ids:
        _emit(
            progress_cb,
            "integrity_reconcile",
            f"Integridade: {len(missing_ids)} doc(s) ausentes apos upsert inicial. Reprocessando.",
            missing_docs=len(missing_ids),
        )
        retry_docs = [unique_by_id[doc_id] for doc_id in missing_ids if doc_id in unique_by_id]
        integrity["reconcile_retry_docs"] = int(len(retry_docs))
        if retry_docs:
            retry_records, retry_embed_stats = _embed_docs(
                docs=retry_docs,
                gemini_client=gemini_client,
                embed_model=embed_model,
                embed_batch_size=embed_batch_size,
                fallback_on_quota=bool(embed_fallback_on_quota),
                progress_cb=progress_cb,
            )
            summary["upsert"]["embedded"] = int(summary["upsert"]["embedded"] + len(retry_records))
            summary["upsert"]["embedded_gemini"] = int(summary["upsert"]["embedded_gemini"] + int(retry_embed_stats.get("gemini") or 0))
            summary["upsert"]["embedded_hash"] = int(summary["upsert"]["embedded_hash"] + int(retry_embed_stats.get("hash") or 0))
            retry_upsert_stats = _upsert_ratio_records(table, retry_records)
            summary["upsert"]["inserted"] = int(summary["upsert"]["inserted"] + int(retry_upsert_stats.get("inserted") or 0))
            summary["upsert"]["updated"] = int(summary["upsert"]["updated"] + int(retry_upsert_stats.get("updated") or 0))

        still_missing = _missing_doc_ids(table, expected_ids)
        integrity["missing_after_retry"] = int(len(still_missing))
        integrity["missing_doc_ids_preview"] = list(still_missing[:25])
        if bool(strict_completeness) and still_missing:
            preview = ", ".join(still_missing[:12])
            raise RuntimeError(
                "Integridade incompleta apos reconcile: "
                f"{len(still_missing)} documento(s) sem materializacao no banco. Exemplos: {preview}"
            )

    summary["finished_at"] = datetime.now().isoformat()
    summary["message"] = (
        f"Atualizacao concluida: {summary['upsert']['inserted']} novo(s), "
        f"{summary['upsert']['updated']} atualizado(s)."
    )
    if int(summary["upsert"].get("embedded_hash") or 0) > 0:
        summary["message"] += (
            f" Embeddings em fallback hash: {summary['upsert']['embedded_hash']}."
        )
    return summary

"""
RAG Pipeline: Ingests STF/STJ data into LanceDB with Gemini embeddings.

Phases:
  1. Reads structured records from SQLite databases
  2. Creates searchable text chunks with metadata
  3. Embeds via Gemini text-embedding-004
  4. Stores in LanceDB with FTS (Full-Text Search) index

Usage:
    py rag/ingest.py --source sumulas       # Quick test (736 records)
    py rag/ingest.py --source stj           # STJ informativos (4,903 records)
    py rag/ingest.py --source stj_sumulas   # STJ sumulas (641 records)
    py rag/ingest.py --source stj_repetitivos  # STJ temas repetitivos (689 records)
    py rag/ingest.py --source informativos  # STF informativos (11,385 records)
    py rag/ingest.py --source acordaos      # STF acórdãos (223k — runs overnight)
    py rag/ingest.py --source all           # Everything
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from google import genai
from google.genai import types
import lancedb
import pyarrow as pa
from dotenv import load_dotenv

# Avoid Windows cp1252 crashes when logs contain Unicode.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Load API key
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_CANDIDATES = [PROJECT_ROOT / ".env", Path("D:/dev/.env")]
for env_path in ENV_CANDIDATES:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY not found. Configure .env in project root or D:/dev/.env."
    )

# Initialize new SDK client
client = genai.Client(api_key=GEMINI_KEY)

# Paths
DATA_DIR = PROJECT_ROOT / "data"
LANCE_DIR = PROJECT_ROOT / "lancedb_store"

# Embedding config
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "100"))
EMBED_DELAY = float(os.getenv("EMBED_DELAY", "0.0"))
EMBED_DIM = 768  # We enforce 768 dimension to save space
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")


@dataclass
class Document:
    """A single searchable document for the RAG store."""
    doc_id: str
    tribunal: str       # "STF" or "STJ"
    tipo: str           # "acordao", "sumula", "informativo", "monocratica"
    processo: str
    relator: str
    ramo_direito: str
    data_julgamento: str
    orgao_julgador: str
    texto_busca: str    # Text used for embedding (ementa + tese, or full text)
    texto_integral: str # Full text for display in results
    url: str
    metadata_extra: str # JSON with any extra fields


# ---------------------------------------------------------------------------
# Source readers
# ---------------------------------------------------------------------------

def clean_legal_text(raw: str) -> str:
    text = html.unescape((raw or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h\d|section|article)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)<[^>]+>", "", text)
    text = re.sub(
        r"(?im)^\s*(supremo tribunal federal|superior tribunal de justiça|página \d+|p. \d+).*$",
        "",
        text,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def read_sumulas() -> List[Document]:
    db = DATA_DIR / "sumulas" / "sumulas.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM sumulas").fetchall()
    conn.close()

    docs = []
    for r in rows:
        titulo = clean_legal_text(r["titulo"] or "")
        enunciado = clean_legal_text(r["enunciado"] or "")
        jurisprudencia = clean_legal_text(r["jurisprudencia"] or "")
        texto = f"{titulo}\n\n{enunciado}"
        docs.append(Document(
            doc_id=f"sumula-{r['numero']}",
            tribunal="STF",
            tipo="sumula",
            processo=titulo,
            relator="",
            ramo_direito="",
            data_julgamento=r["data_aprovacao"] or "",
            orgao_julgador="Plenário",
            texto_busca=texto[:8000],
            texto_integral=(texto + "\n\n" + jurisprudencia)[:30000],
            url=r["url"] or "",
            metadata_extra=json.dumps({
                "status": r["status"],
                "observacoes": r["observacoes"]
            }, ensure_ascii=False),
        ))
    return docs


def read_stj_informativos() -> List[Document]:
    db = DATA_DIR / "stj_informativos" / "stj_informativos.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM stj_informativos").fetchall()
    conn.close()

    docs = []
    for r in rows:
        destaque = clean_legal_text(r["destaque"] or "")
        tema = clean_legal_text(r["tema"] or "")
        texto_integral = clean_legal_text(r["texto_integral"] or "")

        # Build search text: prioritize destaque (tese) + tema, fall back to full text
        if destaque:
            texto_busca = f"{tema}\n{destaque}\n{texto_integral[:4000]}"
        else:
            texto_busca = texto_integral[:8000]

        docs.append(Document(
            doc_id=f"stj-info-{r['id']}",
            tribunal="STJ",
            tipo="informativo",
            processo=clean_legal_text(r["processo"] or ""),
            relator=clean_legal_text(r["relator"] or ""),
            ramo_direito=clean_legal_text(r["ramo_direito"] or ""),
            data_julgamento=r["data_julgamento"] or "",
            orgao_julgador=clean_legal_text(r["orgao_julgador"] or ""),
            texto_busca=texto_busca[:8000],
            texto_integral=texto_integral[:30000],
            url="",
            metadata_extra=json.dumps({
                "informativo_numero": r["informativo_numero"],
                "source_pdf": r["source_pdf"],
                "tema": tema,
            }, ensure_ascii=False),
        ))
    return docs


def read_stj_sumulas() -> List[Document]:
    db = DATA_DIR / "stj_informativos" / "stj_informativos.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    sumulas_rows = conn.execute("SELECT * FROM stj_sumulas ORDER BY sumula_numero DESC").fetchall()
    ramo_rows = conn.execute(
        """
        SELECT sumula_numero, ramo_direito, assunto
        FROM stj_sumula_ramos
        ORDER BY sumula_numero, ramo_direito, assunto
        """
    ).fetchall()
    conn.close()

    ramo_map: dict[int, dict[str, list[str]]] = {}
    for r in ramo_rows:
        numero = int(r["sumula_numero"])
        item = ramo_map.setdefault(numero, {"ramos": [], "assuntos": []})
        ramo = (r["ramo_direito"] or "").strip()
        assunto = (r["assunto"] or "").strip()
        if ramo and ramo not in item["ramos"]:
            item["ramos"].append(ramo)
        if assunto and assunto not in item["assuntos"]:
            item["assuntos"].append(assunto)

    docs: List[Document] = []
    for r in sumulas_rows:
        numero = int(r["sumula_numero"])
        enunciado = clean_legal_text((r["enunciado"] or "").strip())
        orgao = clean_legal_text((r["orgao_julgador"] or "").strip())
        data_julgamento = clean_legal_text((r["data_julgamento"] or "").strip())
        data_publicacao = clean_legal_text((r["data_publicacao"] or "").strip())
        ramo_info = ramo_map.get(numero, {"ramos": [], "assuntos": []})
        ramos = ramo_info["ramos"]
        assuntos = ramo_info["assuntos"]

        processo = f"Sumula STJ {numero}"
        ramo_principal = ramos[0] if ramos else ""
        ramos_texto = ", ".join(ramos)
        assuntos_texto = ", ".join(assuntos)

        texto_busca = (
            f"STJ Sumula {numero}\n"
            f"{enunciado}\n"
            f"Orgao julgador: {orgao}\n"
            f"Ramo(s): {ramos_texto}\n"
            f"Assunto(s): {assuntos_texto}"
        )[:8000]
        texto_integral = (
            f"Sumula STJ {numero}\n\n"
            f"Enunciado: {enunciado}\n"
            f"Orgao julgador: {orgao}\n"
            f"Julgamento: {data_julgamento}\n"
            f"Publicacao: {data_publicacao}\n"
            f"Ramo(s): {ramos_texto}\n"
            f"Assunto(s): {assuntos_texto}"
        )[:30000]

        docs.append(
            Document(
                doc_id=f"stj-sumula-{numero}",
                tribunal="STJ",
                tipo="sumula_stj",
                processo=processo,
                relator="",
                ramo_direito=ramo_principal,
                data_julgamento=data_julgamento,
                orgao_julgador=orgao,
                texto_busca=texto_busca,
                texto_integral=texto_integral,
                url="",
                metadata_extra=json.dumps(
                    {
                        "sumula_numero": numero,
                        "data_publicacao": data_publicacao,
                        "source_pdf": r["source_pdf"],
                        "source_page": r["source_page"],
                        "ramos": ramos,
                        "assuntos": assuntos,
                    },
                    ensure_ascii=False,
                ),
            )
        )
    return docs


def read_stj_repetitivos() -> List[Document]:
    db = DATA_DIR / "stj_informativos" / "stj_informativos.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM stj_temas_repetitivos ORDER BY tema_repetitivo, id").fetchall()
    conn.close()

    docs: List[Document] = []
    for r in rows:
        tema = r["tema_repetitivo"]
        tema_label = f"Tema Repetitivo {tema}" if tema is not None else f"Tema Repetitivo ID {r['id']}"
        titulo = clean_legal_text((r["titulo"] or "").strip())
        assunto = clean_legal_text((r["assunto"] or "").strip())
        ementa = clean_legal_text((r["ementa_resumo"] or "").strip())
        raw_contexto = clean_legal_text((r["raw_contexto"] or "").strip())
        processo_referencia = clean_legal_text((r["processo_referencia"] or "").strip())
        relator = clean_legal_text((r["relator"] or "").strip())
        orgao = clean_legal_text((r["orgao_julgador"] or "").strip())
        data_julgamento = clean_legal_text((r["data_julgamento"] or "").strip())
        data_publicacao = clean_legal_text((r["data_publicacao"] or "").strip())
        ramo = clean_legal_text((r["ramo_direito"] or "").strip())

        processo = processo_referencia or tema_label
        texto_busca = (
            f"STJ {tema_label}\n"
            f"Titulo: {titulo}\n"
            f"Assunto: {assunto}\n"
            f"Ementa: {ementa}\n"
            f"Processo: {processo_referencia}\n"
            f"Relator: {relator}\n"
            f"Orgao julgador: {orgao}"
        )[:8000]
        texto_integral_base = raw_contexto or (
            f"{tema_label}\n\n"
            f"Titulo: {titulo}\n"
            f"Assunto: {assunto}\n"
            f"Ementa: {ementa}"
        )
        texto_integral = texto_integral_base[:30000]

        docs.append(
            Document(
                doc_id=f"stj-repetitivo-{r['id']}",
                tribunal="STJ",
                tipo="tema_repetitivo_stj",
                processo=processo,
                relator=relator,
                ramo_direito=ramo,
                data_julgamento=data_julgamento,
                orgao_julgador=orgao,
                texto_busca=texto_busca,
                texto_integral=texto_integral,
                url="",
                metadata_extra=json.dumps(
                    {
                        "tema_repetitivo": tema,
                        "titulo": titulo,
                        "assunto": assunto,
                        "data_publicacao": data_publicacao,
                        "source_pdf": r["source_pdf"],
                        "source_page": r["source_page"],
                    },
                    ensure_ascii=False,
                ),
            )
        )
    return docs


def read_sumulas_vinculantes() -> List[Document]:
    db = DATA_DIR / "sumulas_vinculantes" / "sumulas_vinculantes.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM sumulas_vinculantes").fetchall()


    docs = []
    for r in rows:
        titulo = clean_legal_text(r["titulo"] or "")
        ementa = clean_legal_text(r["ementa"] or "")
        texto_busca = f"{titulo}\n{ementa}"[:8000]

        docs.append(Document(
            doc_id=f"stf-sv-{r['id']}",
            tribunal="STF",
            tipo="sumula_vinculante",
            processo=titulo,
            relator="STF Plenário",
            ramo_direito="Constitucional",
            data_julgamento=r["julgamento_data"] or "",
            orgao_julgador="Tribunal Pleno",
            texto_busca=texto_busca,
            texto_integral=ementa[:30000],
            url=r["inteiro_teor_url"] or "",
            metadata_extra=json.dumps({
                "legislacao_citada": r["legislacao_citada"],
                "indexacao": r["indexacao"]
            }, ensure_ascii=False),
        ))

    # Also extract the SV extras (Acórdãos and Monocráticas)
    try:
        extras = conn.execute("SELECT * FROM sv_extras").fetchall()
        for r in extras:
            titulo = clean_legal_text(r["titulo"] or "")
            ementa = clean_legal_text(r["ementa"] or "")
            decisao = clean_legal_text(r["decisao"] or "")
            base = r["base"] or ""
            
            tipo = "acordao_sv" if base == "acordaos" else "monocratica_sv"
            texto_integral = ementa if base == "acordaos" else decisao
            texto_busca = f"{titulo}\n{texto_integral}"[:8000]

            docs.append(Document(
                doc_id=f"stf-{tipo}-{r['id']}",
                tribunal="STF",
                tipo=tipo,
                processo=titulo,
                relator=clean_legal_text(r["relator"] or ""),
                ramo_direito="Constitucional",
                data_julgamento=r["julgamento_data"] or "",
                orgao_julgador=(
                    "Decisão Monocrática" if tipo == "monocratica_sv"
                    else clean_legal_text(r["orgao_julgador"] or "")
                ),
                texto_busca=texto_busca,
                texto_integral=texto_integral[:30000],
                url=r["inteiro_teor_url"] or "",
                metadata_extra="{}"
            ))
    except sqlite3.OperationalError:
        pass # Table might not exist yet if only SVs were scraped

    conn.close()
    return docs


def read_stf_informativos() -> List[Document]:
    db = DATA_DIR / "informativos" / "informativos.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM informativos").fetchall()
    conn.close()

    docs = []
    for row in rows:
        r = dict(row)
        resumo = clean_legal_text(r.get("resumo") or "")
        ementa = clean_legal_text(r.get("ementa") or "")
        tese = clean_legal_text(r.get("tese") or "")
        texto_busca = f"{tese}\n{ementa}\n{resumo}"[:8000]
        texto_integral = f"{ementa}\n\n{resumo}"[:30000]

        docs.append(Document(
            doc_id=f"stf-info-{r['id']}",
            tribunal="STF",
            tipo="informativo",
            processo=clean_legal_text(r.get("processo_codigo") or r["titulo"] or ""),
            relator=clean_legal_text(r["relator"] or ""),
            ramo_direito="",
            data_julgamento=r["julgamento_data"] or "",
            orgao_julgador=clean_legal_text(r["orgao_julgador"] or ""),
            texto_busca=texto_busca,
            texto_integral=texto_integral,
            url=r["inteiro_teor_url"] or "",
            metadata_extra=json.dumps({
                "informativo_numero": r["informativo_numero"],
                "informativo_titulo": r["informativo_titulo"],
            }, ensure_ascii=False),
        ))
    return docs


def read_acordaos(limit: Optional[int] = None) -> List[Document]:
    db = DATA_DIR / "acordaos" / "acordaos.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM acordaos ORDER BY julgamento_data DESC"
    if limit:
        query += f" LIMIT {limit}"
    rows = conn.execute(query).fetchall()
    conn.close()

    docs = []
    for r in rows:
        ementa = clean_legal_text(r["ementa"] or "")
        tese = clean_legal_text(r["tese"] or "")
        indexacao = clean_legal_text(r["indexacao"] or "")
        texto_busca = f"{tese}\n{ementa}\n{indexacao}"[:8000]

        classe = r["classe_sigla"] or ""
        numero = r["processo_numero"] or ""
        processo = f"{classe} {numero}".strip()

        docs.append(Document(
            doc_id=f"stf-ac-{r['id']}",
            tribunal="STF",
            tipo="acordao",
            processo=processo,
            relator=clean_legal_text(r["relator"] or ""),
            ramo_direito=clean_legal_text(r["ramo_direito"] or ""),
            data_julgamento=r["julgamento_data"] or "",
            orgao_julgador=clean_legal_text(r["orgao_julgador"] or ""),
            texto_busca=texto_busca,
            texto_integral=ementa[:30000],
            url=r["inteiro_teor_url"] or "",
            metadata_extra=json.dumps({
                "tese_tema": r["tese_tema"],
                "legislacao_citada": r["legislacao_citada"],
                "ai_tags": r["ai_tags"],
                "is_repercussao_geral": r["is_repercussao_geral"],
            }, ensure_ascii=False),
        ))
    return docs


def read_monocraticas(limit: Optional[int] = None, offset: int = 0) -> List[Document]:
    db = DATA_DIR / "monocraticas" / "monocraticas.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM monocraticas WHERE julgamento_data >= '2015-01-01' ORDER BY julgamento_data DESC, id DESC"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    if offset:
        query += f" OFFSET {int(offset)}"
    rows = conn.execute(query).fetchall()
    conn.close()

    docs = []
    for r in rows:
        decisao = clean_legal_text(r["decisao"] or "")
        titulo = clean_legal_text(r["titulo"] or "")
        
        classe = r["classe_sigla"] or ""
        numero = r["processo_numero"] or ""
        processo = f"{classe} {numero}".strip()
        
        texto_busca = f"{titulo}\n{decisao}"[:8000]

        docs.append(Document(
            doc_id=f"stf-mon-{r['id']}",
            tribunal="STF",
            tipo="monocratica",
            processo=processo,
            relator=clean_legal_text(r["relator"] or ""),
            ramo_direito=clean_legal_text(r["ramo_direito"] or ""),
            data_julgamento=r["julgamento_data"] or "",
            orgao_julgador="Decisão Monocrática",
            texto_busca=texto_busca,
            texto_integral=decisao[:30000],
            url=r["inteiro_teor_url"] or "",
            metadata_extra=json.dumps({
                "titulo": titulo,
                "ai_tags": r["ai_tags"],
            }, ensure_ascii=False),
        ))
    return docs

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_batch(texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts using Gemini gemini-embedding-001."""
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBED_DIM
        )
    )
    # result.embeddings is a list of Embedding objects, each with a .values property
    return [e.values for e in result.embeddings]


def embed_documents(docs: List[Document]) -> List[dict]:
    """Embed all documents and return list of dicts ready for LanceDB."""
    records = []
    total = len(docs)

    for i in range(0, total, EMBED_BATCH_SIZE):
        batch = docs[i:i + EMBED_BATCH_SIZE]
        texts = [d.texto_busca for d in batch]

        try:
            vectors = embed_batch(texts)
        except Exception as e:
            print(f"  ⚠️ Embedding error at batch {i}: {e}")
            print(f"  ⏳ Waiting 30s and retrying...")
            time.sleep(30)
            try:
                vectors = embed_batch(texts)
            except Exception as e2:
                print(f"  ❌ Retry failed: {e2}. Skipping batch.")
                continue

        for doc, vec in zip(batch, vectors):
            records.append({
                "vector": vec,
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
            })

        progress = min(i + EMBED_BATCH_SIZE, total)
        print(f"  📊 Embedded {progress}/{total} ({progress * 100 // total}%)")
        time.sleep(EMBED_DELAY)

    return records


# ---------------------------------------------------------------------------
# LanceDB storage
# ---------------------------------------------------------------------------

LANCE_SCHEMA = pa.schema([
    pa.field("vector", pa.list_(pa.float32(), EMBED_DIM)),
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
])

TABLE_NAME = "jurisprudencia"


def store_in_lancedb(records: List[dict], mode: str = "append") -> int:
    """Store embedded records in LanceDB."""
    LANCE_DIR.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(LANCE_DIR))

    table_exists = False
    try:
        db.open_table(TABLE_NAME)
        table_exists = True
    except Exception:
        pass

    if mode == "overwrite" or not table_exists:
        tbl = db.create_table(TABLE_NAME, data=records, schema=LANCE_SCHEMA, mode="overwrite")
        print(f"  ✅ Created table '{TABLE_NAME}' with {len(records)} records")
    else:
        tbl = db.open_table(TABLE_NAME)
        before = tbl.count_rows()
        # True upsert: update existing doc_id and insert new ones.
        (
            tbl.merge_insert("doc_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(records)
        )
        after = tbl.count_rows()
        inserted = after - before
        updated = len(records) - inserted
        print(
            f"  ✅ Upsert completed: {inserted} new, {updated} updated existing "
            f"(total: {after})"
        )

    # Create FTS index for hybrid search
    try:
        tbl.create_fts_index("texto_busca", use_tantivy=False, replace=True)
        print("  🔍 Native Full-text search index created on 'texto_busca'")
    except Exception as e:
        print(f"  ⚠️ FTS index creation: {e}")

    return tbl.count_rows()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

SOURCE_MAP = {
    "sumulas": ("Súmulas STF", read_sumulas),
    "sumulas_vinculantes": ("Súmulas Vinculantes STF", read_sumulas_vinculantes),
    "stj": ("STJ Informativos", read_stj_informativos),
    "stj_sumulas": ("STJ Súmulas", read_stj_sumulas),
    "stj_repetitivos": ("STJ Temas Repetitivos", read_stj_repetitivos),
    "informativos": ("STF Informativos", read_stf_informativos),
    "acordaos": ("STF Acórdãos", read_acordaos),
    "monocraticas": ("STF Decisões Monocráticas", read_monocraticas),
}


def run_pipeline(
    sources: List[str],
    mode: str = "overwrite",
    acordaos_limit: Optional[int] = None,
    monocraticas_limit: Optional[int] = None,
    monocraticas_offset: int = 0,
):
    print(f"🚀 RAG Ingestion Pipeline")
    print(f"   LanceDB store: {LANCE_DIR}")
    print(f"   Embedding model: {EMBED_MODEL}")
    print(f"   Sources: {', '.join(sources)}")
    print()

    first = True
    for source in sources:
        if source not in SOURCE_MAP:
            print(f"⚠️ Unknown source: {source}. Skipping.")
            continue

        name, reader = SOURCE_MAP[source]
        print(f"📂 Loading {name}...")

        if source == "acordaos" and acordaos_limit:
            docs = reader(limit=acordaos_limit)
        elif source == "monocraticas":
            docs = reader(limit=monocraticas_limit, offset=monocraticas_offset)
        else:
            docs = reader()

        print(f"   Loaded {len(docs)} documents")

        if not docs:
            print(f"   ⚠️ No documents found. Skipping.")
            continue

        print(f"🔄 Generating embeddings...")
        records = embed_documents(docs)

        print(f"💾 Storing in LanceDB...")
        current_mode = mode if first else "append"
        total = store_in_lancedb(records, mode=current_mode)
        first = False

        print(f"   Total records in DB: {total}")
        print()

    print(f"{'='*60}")
    print(f"✅ INGESTION COMPLETE")
    print(f"{'='*60}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG Ingestion Pipeline")
    parser.add_argument(
        "--source", type=str, default="sumulas",
        choices=[
            "sumulas",
            "sumulas_vinculantes",
            "stj",
            "stj_sumulas",
            "stj_repetitivos",
            "informativos",
            "acordaos",
            "monocraticas",
            "all",
        ],
        help="Data source to ingest",
    )
    parser.add_argument(
        "--mode", type=str, default="overwrite",
        choices=["overwrite", "append"],
        help="Write mode (overwrite creates fresh DB, append adds to existing)",
    )
    parser.add_argument(
        "--acordaos-limit", type=int, default=None,
        help="Limit number of acórdãos to ingest (for testing)",
    )
    parser.add_argument(
        "--monocraticas-limit", type=int, default=None,
        help="Limit number of monocráticas to ingest (for incremental runs)",
    )
    parser.add_argument(
        "--monocraticas-offset", type=int, default=0,
        help="Offset for monocráticas incremental ingest",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sources = list(SOURCE_MAP.keys()) if args.source == "all" else [args.source]
    run_pipeline(
        sources,
        mode=args.mode,
        acordaos_limit=args.acordaos_limit,
        monocraticas_limit=args.monocraticas_limit,
        monocraticas_offset=args.monocraticas_offset,
    )

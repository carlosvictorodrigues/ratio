"""
TJSP Revista Eletronica de Jurisprudencia - Scraper + Parser
==============================================================
Downloads all volumes from https://www.tjsp.jus.br/Biblioteca/RevistaJurisprudencia/Revistas,
parses individual decisions from the PDFs, and stores them in SQLite.

Usage:
    python scrapers/tjsp_revistas.py --download          # Download all PDFs
    python scrapers/tjsp_revistas.py --parse             # Parse downloaded PDFs
    python scrapers/tjsp_revistas.py --all               # Download + parse
    python scrapers/tjsp_revistas.py --parse --vol 73    # Parse single volume
    python scrapers/tjsp_revistas.py --stats             # Show DB stats

Output: data/tjsp_revistas/tjsp_revistas.db
PDFs:   data/tjsp_revistas/pdfs/vol_XX.pdf
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup

# ── Config ───────────────────────────────────────────────────────────
BASE_URL = "https://www.tjsp.jus.br"
FILEFETCH_URL = "https://api.tjsp.jus.br/Handlers/Handler/FileFetch.ashx"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "tjsp_revistas"
PDF_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "tjsp_revistas.db"

DELAY_BETWEEN_REQUESTS = 1.5  # Be polite to the server
DOWNLOAD_TIMEOUT = 120  # seconds per PDF
MAX_RETRIES = 3

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
handler.flush = lambda: sys.stdout.flush()
logging.basicConfig(level=logging.INFO, handlers=[handler])
log = logging.getLogger("tjsp")

# ── Volume catalog ───────────────────────────────────────────────────
# Each entry: (volume_number, period, codigoNoticia)
# Scraped from all 8 pages of the TJSP website on 2026-03-20.

VOLUME_CATALOG = [
    # Page 1
    (73, "Jan/Fev 2026", 113742),
    (72, "Nov/Dez 2025", 113276),
    (71, "Set/Out 2025", 112886),
    (70, "Jul/Ago 2025", 111291),
    (69, "Mai/Jun 2025", 108724),
    (68, "Mar/Abr 2025", 107210),
    (67, "Jan/Fev 2025", 106585),
    (66, "Nov/Dez 2024", 105934),
    (65, "Set/Out 2024", 105320),
    (64, "Jul/Ago 2024", 103647),
    # Page 2
    (63, "Mai/Jun 2024", 100936),
    (62, "Mar/Abr 2024", 98273),
    (61, "Jan/Fev 2024", 97686),
    (60, "Nov/Dez 2023", 97213),
    (59, "Set/Out 2023", 95574),
    (58, "Jul/Ago 2023", 94978),
    (57, "Mai/Jun 2023", 93336),
    (56, "Mar/Abr 2023", 91658),
    (55, "Jan/Fev 2023", 91031),
    (54, "Nov/Dez 2022", 88557),
    # Page 3
    (53, "Set/Out 2022", 87122),
    (52, "Jul/Ago 2022", 85681),
    (51, "Mai/Jun 2022", 84937),
    (50, "Mar/Abr 2022", 82455),
    (49, "Jan/Fev 2022", 81831),
    (48, "Nov/Dez 2021", 79343),
    (47, "Set/Out 2021", 77913),
    (46, "Jul/Ago 2021", 74339),
    (45, "Mai/Jun 2021", 68711),
    (44, "Mar/Abr 2021", 68710),
    # Page 4
    (43, "Jan/Fev 2021", 63554),
    (42, "Nov/Dez 2020", 63104),
    (41, "Set/Out 2020", 62680),
    (40, "Jul/Ago 2020", 62168),
    (39, "Mai/Jun 2020", 61582),
    (38, "Mar/Abr 2020", 61067),
    (37, "Jan/Fev 2020", 60570),
    (36, "Nov/Dez 2019", 60095),
    (35, "Set/Out 2019", 59464),
    (34, "Jul/Ago 2019", 58807),
    # Page 5
    (33, "Mai/Jun 2019", 58143),
    (32, "Mar/Abr 2019", 56492),
    (31, "Jan/Fev 2019", 56073),
    (30, "Nov/Dez 2018", 55502),
    (29, "Set/Out 2018", 54017),
    (28, "Jul/Ago 2018", 52455),
    (27, "Mai/Jun 2018", 51812),
    (26, "Mar/Abr 2018", 51413),
    (25, "Jan/Fev 2018", 51412),
    (24, "Nov/Dez 2017", 51411),
    # Page 6
    (23, "Set/Out 2017", 51409),
    (22, "Jul/Ago 2017", 51408),
    (21, "Mai/Jun 2017", 51407),
    (20, "Mar/Abr 2017", 51406),
    (19, "Jan/Fev 2017", 51405),
    (18, "Nov/Dez 2016", 51404),
    (17, "Set/Out 2016", 51403),
    (16, "Jul/Ago 2016", 51402),
    (15, "Mai/Jun 2016", 51401),
    (14, "Mar/Abr 2016", 51400),
    # Page 7
    (13, "Jan/Fev 2016", 51399),
    (12, "Nov/Dez 2015", 51398),
    (11, "Set/Out 2015", 51396),
    (10, "Jul/Ago 2015", 51393),
    (9, "Mai/Jun 2015", 51392),
    (8, "Mar/Abr 2015", 51391),
    (7, "Jan/Fev 2015", 51390),
    (6, "Nov/Dez 2014", 51389),
    (5, "Set/Out 2014", 51388),
    (4, "Jul/Ago 2014", 51387),
    # Page 8
    (3, "Mai/Jun 2014", 51386),
    (2, "Mar/Abr 2014", 51385),
    (1, "Jan/Fev 2014", 51211),
    (0, "Nov/Dez 2013", 51206),
]

# ── SQLite ───────────────────────────────────────────────────────────

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS decisoes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    volume              INTEGER NOT NULL,
    periodo             TEXT NOT NULL,
    tipo_recurso        TEXT,
    processo            TEXT,
    comarca             TEXT,
    camara              TEXT,
    ramo_direito        TEXT,
    relator             TEXT,
    data_julgamento     TEXT,
    ementa              TEXT,
    texto_integral      TEXT,
    legislacao_citada   TEXT,
    jurisprudencia_citada TEXT,
    pagina_inicio       INTEGER,
    doc_hash            TEXT UNIQUE
)
"""

CREATE_PDF_CODES = """
CREATE TABLE IF NOT EXISTS pdf_codes (
    volume          INTEGER PRIMARY KEY,
    codigo_noticia  INTEGER NOT NULL,
    codigo_pdf      INTEGER,
    periodo         TEXT,
    pages           INTEGER,
    size_bytes      INTEGER
)
"""


def init_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(CREATE_TABLE)
    conn.execute(CREATE_PDF_CODES)
    conn.commit()
    return conn


# ── HTTP helpers ─────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Ratio-Jurisprudencial/1.0",
    "Accept-Language": "pt-BR,pt;q=0.9",
})


def fetch_page(url: str) -> Optional[BeautifulSoup]:
    for attempt in range(MAX_RETRIES):
        try:
            r = SESSION.get(url, timeout=30)
            r.raise_for_status()
            return BeautifulSoup(r.content, "html.parser")
        except Exception as e:
            log.warning(f"  Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
            time.sleep(3 * (attempt + 1))
    return None


# ── Step 1: Resolve PDF download codes ───────────────────────────────

def resolve_pdf_codes(conn: sqlite3.Connection) -> dict[int, int]:
    """Visit each volume page to find the FileFetch codigo for the PDF."""
    resolved = {}

    # Load already resolved codes
    rows = conn.execute("SELECT volume, codigo_pdf FROM pdf_codes WHERE codigo_pdf IS NOT NULL").fetchall()
    for vol, code in rows:
        resolved[vol] = code

    pending = [
        (vol, period, cod)
        for vol, period, cod in VOLUME_CATALOG
        if vol not in resolved
    ]

    if not pending:
        log.info(f"All {len(resolved)} PDF codes already resolved.")
        return resolved

    log.info(f"Resolving PDF codes for {len(pending)} volumes ({len(resolved)} cached)...")

    for vol, period, cod_noticia in pending:
        url = f"{BASE_URL}/Biblioteca/RevistaJurisprudencia/Revista?codigoNoticia={cod_noticia}&pagina=1"
        log.info(f"  Vol {vol:02d} ({period}) ...")

        soup = fetch_page(url)
        if not soup:
            log.error(f"  Could not fetch page for vol {vol}")
            continue

        # Find the FileFetch link
        pdf_code = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"FileFetch\.ashx\?codigo=(\d+)", href)
            if m:
                # Check if it's the e-JTJ link (not other PDFs like Carta de Servicos)
                link_text = a.get_text(strip=True).lower()
                if "e-jtj" in link_text or "vol" in link_text or "revista" in link_text:
                    pdf_code = int(m.group(1))
                    break
                # Keep as candidate if no better match found
                if pdf_code is None:
                    pdf_code = int(m.group(1))

        if pdf_code:
            resolved[vol] = pdf_code
            conn.execute(
                "INSERT OR REPLACE INTO pdf_codes (volume, codigo_noticia, codigo_pdf, periodo) VALUES (?, ?, ?, ?)",
                (vol, cod_noticia, pdf_code, period),
            )
            conn.commit()
            log.info(f"    -> codigo_pdf={pdf_code}")
        else:
            log.warning(f"    -> PDF link not found!")
            conn.execute(
                "INSERT OR REPLACE INTO pdf_codes (volume, codigo_noticia, periodo) VALUES (?, ?, ?)",
                (vol, cod_noticia, period),
            )
            conn.commit()

        time.sleep(DELAY_BETWEEN_REQUESTS)

    log.info(f"Resolved {len(resolved)}/{len(VOLUME_CATALOG)} PDF codes.")
    return resolved


# ── Step 2: Download PDFs ────────────────────────────────────────────

def download_pdfs(conn: sqlite3.Connection, pdf_codes: dict[int, int]) -> list[Path]:
    """Download PDFs that haven't been downloaded yet."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []

    for vol, _, period in sorted(VOLUME_CATALOG, key=lambda x: x[0]):
        if vol not in pdf_codes:
            continue

        pdf_path = PDF_DIR / f"vol_{vol:02d}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 100_000:
            downloaded.append(pdf_path)
            continue

        code = pdf_codes[vol]
        url = f"{FILEFETCH_URL}?codigo={code}"
        log.info(f"Downloading Vol {vol:02d} ({period}) ...")

        for attempt in range(MAX_RETRIES):
            try:
                r = SESSION.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True)
                r.raise_for_status()

                size = 0
                with open(pdf_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
                        size += len(chunk)

                # Update DB with size info
                conn.execute(
                    "UPDATE pdf_codes SET size_bytes = ? WHERE volume = ?",
                    (size, vol),
                )
                conn.commit()

                log.info(f"  -> {size / 1024 / 1024:.1f} MB")
                downloaded.append(pdf_path)
                break

            except Exception as e:
                log.warning(f"  Attempt {attempt + 1}/{MAX_RETRIES}: {e}")
                time.sleep(5 * (attempt + 1))
        else:
            log.error(f"  Failed to download vol {vol}")

        time.sleep(DELAY_BETWEEN_REQUESTS)

    log.info(f"Downloaded {len(downloaded)}/{len(pdf_codes)} PDFs.")
    return downloaded


# ── Step 3: Parse PDFs ───────────────────────────────────────────────

# Month name → number mapping for Portuguese dates
MONTH_MAP = {
    "janeiro": "01", "fevereiro": "02", "março": "03", "marco": "03",
    "abril": "04", "maio": "05", "junho": "06", "julho": "07",
    "agosto": "08", "setembro": "09", "outubro": "10",
    "novembro": "11", "dezembro": "12",
}

# Regex patterns
RE_PROCESSO = re.compile(r"\d{7}-\d{2}\.\d{4}\.8\.26\.\d{4}")
RE_CAMARA = re.compile(
    r"(\d+).{1,3}\s*C.mara\s+(?:Reservada\s+)?de\s+Direito\s+(Privado|P.blico|Criminal|Empresarial)",
    re.IGNORECASE,
)
RE_RELATOR = re.compile(
    r"^(.{5,80}),\s*Relator[a]?\s*$",
    re.MULTILINE,
)
RE_DATE_PT = re.compile(
    r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
    re.IGNORECASE,
)
RE_ACORDAM = re.compile(r"ACORDAM\s*,\s*em\b", re.IGNORECASE)
RE_EMENTA_START = re.compile(r"\bEmenta\s*:", re.IGNORECASE)
RE_VOTO_START = re.compile(r"^\s*VOTO\s*$", re.MULTILINE)
RE_SECTION_HEADER = re.compile(
    r"Jurisprud.ncia\s*-\s*Direito\s+(Privado|P.blico|Criminal)",
    re.IGNORECASE,
)
RE_BOILERPLATE = re.compile(
    r"(?:^e-JTJ\s*-\s*\d+\s*$|"
    r"^Revista\s+Eletr.nica\s+de\s+Jurisprud.ncia.*$|"
    r"^[A-Z][a-z]+\s+e\s+[A-Z][a-z]+\s+de\s+\d{4}\s*$|"
    r"^Acesso\s+ao\s+Sum.rio\s*$|"
    r"^\d{1,4}\s*$)",
    re.MULTILINE | re.IGNORECASE,
)


def _normalize_date(day: str, month_name: str, year: str) -> str:
    """Convert Portuguese date to ISO format."""
    m = MONTH_MAP.get(month_name.lower(), "01")
    return f"{year}-{m}-{int(day):02d}"


def _clean_text(text: str) -> str:
    """Remove boilerplate headers/footers and fix PDF line-break artifacts."""
    text = RE_BOILERPLATE.sub("", text)
    # Fix line-break hyphens: "FAL-\nÊNCIA" → "FALÊNCIA"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Fix line-break without hyphen (word split across lines)
    text = re.sub(r"(\w)\n(\w)", r"\1 \2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_ramo(ramo: str) -> str:
    """Normalize ramo_direito to consistent values."""
    lower = ramo.lower()
    if "privad" in lower:
        return "Direito Privado"
    if "p" in lower and "blic" in lower:
        return "Direito Publico"
    if "criminal" in lower or "penal" in lower:
        return "Direito Criminal"
    if "empresarial" in lower:
        return "Direito Empresarial"
    return ramo


def _extract_decisions_from_text(full_text: str, volume: int) -> list[dict]:
    """Split full PDF text into individual decisions."""
    import hashlib
    decisions = []

    # Track current section (ramo_direito)
    current_ramo = "Direito Privado"

    # Find all ACORDAM positions to split decisions
    acordam_positions = [m.start() for m in RE_ACORDAM.finditer(full_text)]

    if not acordam_positions:
        log.warning(f"  Vol {volume}: no ACORDAM markers found")
        return []

    # Split text at each ACORDAM
    for idx, start in enumerate(acordam_positions):
        end = acordam_positions[idx + 1] if idx + 1 < len(acordam_positions) else len(full_text)
        chunk = full_text[start:end]

        # Include preceding text (processo/comarca appear before ACORDAM)
        prev_boundary = acordam_positions[idx - 1] if idx > 0 else max(0, start - 2000)
        preceding = full_text[max(prev_boundary, start - 1500):start]

        # Check section header before this ACORDAM
        section_match = list(RE_SECTION_HEADER.finditer(preceding))
        if section_match:
            ramo = section_match[-1].group(1)
            if re.match(r"p.blic", ramo, re.IGNORECASE):
                current_ramo = "Direito Publico"
            else:
                current_ramo = f"Direito {ramo.capitalize()}"

        # --- Extract fields ---
        # Combined header: preceding text + first 1500 chars after ACORDAM
        header = preceding + chunk[:1500]

        # Processo: search in preceding first (Vistos, relatados... nº XXXX)
        processo = ""
        proc_in_preceding = RE_PROCESSO.search(preceding)
        if proc_in_preceding:
            processo = proc_in_preceding.group(0)
        else:
            # Fallback: check in VOTO section for processo number
            proc_in_chunk = RE_PROCESSO.search(chunk[:5000])
            if proc_in_chunk:
                processo = proc_in_chunk.group(0)

        # Camara
        camara_match = RE_CAMARA.search(header)
        camara = ""
        ramo_from_camara = ""
        if camara_match:
            num = camara_match.group(1)
            ramo_cam = camara_match.group(2)
            camara = f"{num}a Camara de Direito {ramo_cam}"
            ramo_from_camara = f"Direito {ramo_cam}"

        # Relator: pattern is "NAME, Relator[a]" at end of line
        relator = ""
        relator_match = RE_RELATOR.search(header)
        if relator_match:
            relator = relator_match.group(1).strip()
            # Clean up common prefixes
            relator = re.sub(r"^\s*(?:Des\.?\s*)?", "", relator).strip()

        # Date: first Portuguese date in header
        data_julgamento = ""
        # Look for dates but skip very old ones that are citations
        # Also reject future dates (parsing errors / OCR artefacts)
        from datetime import date as _date_cls
        _today_iso = _date_cls.today().isoformat()
        for dm in RE_DATE_PT.finditer(header):
            month_name = dm.group(2).lower()
            if month_name in MONTH_MAP:
                candidate = _normalize_date(dm.group(1), dm.group(2), dm.group(3))
                year = int(dm.group(3))
                if year >= 2013 and candidate <= _today_iso:
                    data_julgamento = candidate
                    break

        # Comarca (usually in preceding text: "da Comarca de XXXXX,")
        comarca = ""
        comarca_match = re.search(
            r"Comarca\s+de\s+([\w\s]+?)(?:\s*,|\s*em\s+que|\s*\()",
            preceding, re.IGNORECASE,
        )
        if not comarca_match:
            comarca_match = re.search(
                r"Comarca\s+de\s+([\w\s]+?)(?:\s*,|\s*em\s+que|\s*\()",
                chunk[:2000], re.IGNORECASE,
            )
        if comarca_match:
            comarca = comarca_match.group(1).strip()[:200]

        # Tipo recurso (in preceding: "autos de Agravo de Instrumento nº")
        tipo_recurso = ""
        tipo_match = re.search(
            r"autos\s+de\s+([\w\s]+?)\s+n[^a-zA-Z]",
            preceding, re.IGNORECASE,
        )
        if not tipo_match:
            tipo_match = re.search(
                r"autos\s+de\s+([\w\s]+?)\s+n[^a-zA-Z]",
                chunk[:1500], re.IGNORECASE,
            )
        if tipo_match:
            tipo_recurso = tipo_match.group(1).strip()[:200]

        # --- Extract ementa ---
        ementa = ""
        ementa_match = RE_EMENTA_START.search(chunk)
        if ementa_match:
            ementa_start = ementa_match.end()
            # Ementa ends at VOTO or at Legislacao Citada
            voto_match = RE_VOTO_START.search(chunk[ementa_start:])
            leg_start = re.search(r"Legisla.{1,3}o\s+Citada", chunk[ementa_start:], re.IGNORECASE)
            juris_start = re.search(r"Jurisprud.ncia\s+Citada", chunk[ementa_start:], re.IGNORECASE)

            # Find the earliest boundary
            boundaries = []
            if voto_match:
                boundaries.append(voto_match.start())
            if leg_start:
                boundaries.append(leg_start.start())
            if juris_start:
                boundaries.append(juris_start.start())

            if boundaries:
                ementa_end = ementa_start + min(boundaries)
            else:
                ementa_end = ementa_start + 4000
            ementa = _clean_text(chunk[ementa_start:ementa_end])

        # --- Legislacao & Jurisprudencia citada ---
        legislacao = ""
        juris = ""
        leg_match = re.search(
            r"Legisla.{1,3}o\s+Citada\s*:\s*(.*?)(?:Jurisprud|VOTO|$)",
            chunk, re.DOTALL | re.IGNORECASE,
        )
        if leg_match:
            legislacao = _clean_text(leg_match.group(1))[:2000]

        juris_match = re.search(
            r"Jurisprud.ncia\s+Citada\s*:\s*(.*?)(?:VOTO|$)",
            chunk, re.DOTALL | re.IGNORECASE,
        )
        if juris_match:
            juris = _clean_text(juris_match.group(1))[:2000]

        # Full text (cleaned)
        texto_integral = _clean_text(chunk)

        # Skip empty/garbage entries
        if not ementa and len(texto_integral) < 300:
            continue

        # Use ramo from camara if available (more specific), normalize
        ramo = _normalize_ramo(ramo_from_camara or current_ramo)

        # Content hash for deduplication
        hash_input = f"{volume}:{processo}:{relator}:{ementa[:200]}"
        doc_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        decisions.append({
            "volume": volume,
            "tipo_recurso": tipo_recurso,
            "processo": processo,
            "comarca": comarca,
            "camara": camara,
            "ramo_direito": ramo,
            "relator": relator,
            "data_julgamento": data_julgamento,
            "ementa": ementa[:8000],
            "texto_integral": texto_integral[:30000],
            "legislacao_citada": legislacao,
            "jurisprudencia_citada": juris,
            "doc_hash": doc_hash,
        })

    return decisions


def parse_pdf(pdf_path: Path, volume: int, period: str, conn: sqlite3.Connection) -> int:
    """Parse a single PDF and store decisions in SQLite."""
    log.info(f"Parsing Vol {volume:02d} ({period}) - {pdf_path.name} ...")

    doc = fitz.open(str(pdf_path))
    pages = doc.page_count

    # Update page count in DB
    conn.execute("UPDATE pdf_codes SET pages = ? WHERE volume = ?", (pages, volume))

    # Extract all text
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n\n"
    doc.close()

    decisions = _extract_decisions_from_text(full_text, volume)
    log.info(f"  Found {len(decisions)} decisions in {pages} pages")

    # Store in SQLite
    inserted = 0
    for d in decisions:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO decisoes
                   (volume, periodo, tipo_recurso, processo, comarca, camara,
                    ramo_direito, relator, data_julgamento, ementa,
                    texto_integral, legislacao_citada, jurisprudencia_citada,
                    pagina_inicio, doc_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    d["volume"], period, d["tipo_recurso"], d["processo"],
                    d["comarca"], d["camara"], d["ramo_direito"], d["relator"],
                    d["data_julgamento"], d["ementa"], d["texto_integral"],
                    d["legislacao_citada"], d["jurisprudencia_citada"],
                    0, d["doc_hash"],
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass  # Duplicate

    conn.commit()
    log.info(f"  Inserted {inserted} new decisions")
    return inserted


def parse_all_pdfs(conn: sqlite3.Connection, only_vol: Optional[int] = None) -> int:
    """Parse all downloaded PDFs."""
    total = 0
    catalog = {v: p for v, p, _ in VOLUME_CATALOG}

    for vol in sorted(catalog.keys()):
        if only_vol is not None and vol != only_vol:
            continue

        pdf_path = PDF_DIR / f"vol_{vol:02d}.pdf"
        if not pdf_path.exists():
            continue

        period = catalog[vol]
        count = parse_pdf(pdf_path, vol, period, conn)
        total += count

    log.info(f"Total: {total} decisions parsed.")
    return total


# ── Stats ────────────────────────────────────────────────────────────

def show_stats(conn: sqlite3.Connection):
    """Show database statistics."""
    total = conn.execute("SELECT COUNT(*) FROM decisoes").fetchone()[0]
    volumes = conn.execute("SELECT COUNT(DISTINCT volume) FROM decisoes").fetchone()[0]
    by_ramo = conn.execute(
        "SELECT ramo_direito, COUNT(*) FROM decisoes GROUP BY ramo_direito ORDER BY COUNT(*) DESC"
    ).fetchall()
    by_vol = conn.execute(
        "SELECT d.volume, d.periodo, COUNT(*) FROM decisoes d "
        "GROUP BY d.volume ORDER BY d.volume DESC"
    ).fetchall()

    print(f"\n{'=' * 60}")
    print(f"TJSP Revistas - Database Statistics")
    print(f"{'=' * 60}")
    print(f"Total decisions: {total:,}")
    print(f"Volumes parsed:  {volumes}")
    print()
    print("By area of law:")
    for ramo, count in by_ramo:
        print(f"  {ramo or 'N/A':30s} {count:>6,}")
    print()
    print("By volume (recent first):")
    for vol, period, count in by_vol[:15]:
        print(f"  Vol {vol:02d} ({period:15s}): {count:>4} decisions")
    if len(by_vol) > 15:
        print(f"  ... and {len(by_vol) - 15} more volumes")
    print()

    # PDF codes status
    resolved = conn.execute("SELECT COUNT(*) FROM pdf_codes WHERE codigo_pdf IS NOT NULL").fetchone()[0]
    downloaded = len(list(PDF_DIR.glob("vol_*.pdf"))) if PDF_DIR.exists() else 0
    print(f"PDF codes resolved: {resolved}/{len(VOLUME_CATALOG)}")
    print(f"PDFs downloaded:    {downloaded}/{len(VOLUME_CATALOG)}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TJSP Revista de Jurisprudencia scraper")
    parser.add_argument("--download", action="store_true", help="Download PDFs")
    parser.add_argument("--parse", action="store_true", help="Parse PDFs into decisions")
    parser.add_argument("--all", action="store_true", help="Download + parse")
    parser.add_argument("--stats", action="store_true", help="Show DB stats")
    parser.add_argument("--vol", type=int, help="Process single volume")
    parser.add_argument("--resolve-only", action="store_true", help="Only resolve PDF codes (no download)")
    args = parser.parse_args()

    if not any([args.download, args.parse, args.all, args.stats, args.resolve_only]):
        parser.print_help()
        return

    conn = init_db()

    try:
        if args.stats:
            show_stats(conn)
            return

        if args.resolve_only:
            resolve_pdf_codes(conn)
            show_stats(conn)
            return

        if args.download or args.all:
            pdf_codes = resolve_pdf_codes(conn)
            if args.vol is not None:
                pdf_codes = {k: v for k, v in pdf_codes.items() if k == args.vol}
            download_pdfs(conn, pdf_codes)

        if args.parse or args.all:
            parse_all_pdfs(conn, only_vol=args.vol)
            show_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

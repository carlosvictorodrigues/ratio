from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "analysis" / "ingest_monocraticas_pendentes.py"
SPEC = importlib.util.spec_from_file_location("ingest_monocraticas_pendentes", MODULE_PATH)
assert SPEC and SPEC.loader
INGEST = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INGEST
SPEC.loader.exec_module(INGEST)


def _doc(i: int, text: str = "texto curto") -> object:
    return INGEST.MonoDoc(
        doc_id=f"doc-{i}",
        tribunal="STF",
        tipo="monocratica",
        processo=f"PROC {i}",
        relator="Min. Teste",
        ramo_direito="Constitucional",
        data_julgamento="2026-01-01",
        orgao_julgador="Decisao Monocratica",
        texto_busca=text,
        texto_integral=text,
        url="https://example.test/doc",
        metadata_extra="{}",
    )


def test_build_embed_batches_respects_api_request_cap() -> None:
    docs = [_doc(i) for i in range(205)]
    batches = INGEST.build_embed_batches(
        docs,
        embed_batch_size=150,
        max_tokens_per_request=10_000_000,
    )

    sizes = [len(batch_docs) for _, batch_docs, _ in batches]
    assert sizes == [INGEST.EMBED_API_MAX_REQUESTS, INGEST.EMBED_API_MAX_REQUESTS, 5]
    assert max(sizes) <= INGEST.EMBED_API_MAX_REQUESTS


def test_build_embed_batches_still_splits_by_token_budget() -> None:
    docs = [_doc(i, "x" * 1000) for i in range(3)]
    batches = INGEST.build_embed_batches(
        docs,
        embed_batch_size=100,
        max_tokens_per_request=300,
    )

    sizes = [len(batch_docs) for _, batch_docs, _ in batches]
    assert sizes == [1, 1, 1]

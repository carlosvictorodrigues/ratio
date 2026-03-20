from __future__ import annotations

import importlib

import pytest


rag_query = pytest.importorskip("rag.query", reason="requires full RAG runtime")
rag_ingest = pytest.importorskip("rag.ingest", reason="requires ingest runtime")


class _FakeTable:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeDB:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open_table(self, name: str):
        self.opened.append(name)
        return _FakeTable(name)


class _FakeArrowTable:
    def __init__(self, rows):
        self._rows = rows

    def to_pylist(self):
        return list(self._rows)


class _FakeLanceDataset:
    def __init__(self, rows):
        self._rows = rows
        self.schema = type("Schema", (), {"names": list(rows[0].keys()) if rows else []})()

    def to_table(self, columns=None, filter=None):  # noqa: ARG002
        if columns:
            return _FakeArrowTable(
                [{key: row.get(key) for key in columns} for row in self._rows]
            )
        return _FakeArrowTable(self._rows)


class _FakeTimelineTable(_FakeTable):
    def __init__(self, name: str, rows):
        super().__init__(name)
        self._rows = rows

    def to_lance(self):
        return _FakeLanceDataset(self._rows)


def test_search_lancedb_opens_tjsp_table_when_source_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDB()

    def fake_connect(_path: str):
        return fake_db

    def fake_rows(tbl, **_kwargs):
        return [
            {
                "doc_id": f"{tbl.name}-1",
                "tribunal": "TJSP" if tbl.name == "tjsp_jurisprudencia" else "STF",
                "tipo": "acordao",
                "processo": f"PROC-{tbl.name}",
                "_rrf_score": 1.0,
                "_hybrid_hits": 2,
                "_rank_vec": 1,
                "_rank_fts": 1,
            }
        ]

    monkeypatch.setattr(rag_query.lancedb, "connect", fake_connect)
    monkeypatch.setattr(rag_query, "_table_hybrid_rows", fake_rows)

    rows = rag_query.search_lancedb(
        query="hospital",
        query_vector=[0.1, 0.2],
        sources=["tjsp"],
        top_k=5,
    )

    assert fake_db.opened == ["tjsp_jurisprudencia"]
    assert len(rows) == 1
    assert rows[0]["tribunal"] == "TJSP"
    assert rows[0]["source_id"] == "tjsp"
    assert rows[0]["source_label"] == "TJSP Revistas"


def test_search_lancedb_opens_ratio_and_tjsp_tables_when_both_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDB()

    def fake_connect(_path: str):
        return fake_db

    def fake_rows(tbl, **_kwargs):
        tribunal = "TJSP" if tbl.name == "tjsp_jurisprudencia" else "STF"
        return [
            {
                "doc_id": f"{tbl.name}-1",
                "tribunal": tribunal,
                "tipo": "acordao",
                "processo": f"PROC-{tbl.name}",
                "_rrf_score": 1.0,
                "_hybrid_hits": 2,
                "_rank_vec": 1,
                "_rank_fts": 1,
            }
        ]

    monkeypatch.setattr(rag_query.lancedb, "connect", fake_connect)
    monkeypatch.setattr(rag_query, "_table_hybrid_rows", fake_rows)

    rows = rag_query.search_lancedb(
        query="hospital",
        query_vector=[0.1, 0.2],
        sources=["ratio", "tjsp"],
        top_k=5,
    )

    assert fake_db.opened == ["jurisprudencia", "tjsp_jurisprudencia"]
    assert {row["tribunal"] for row in rows} == {"STF", "TJSP"}


def test_ingest_routes_tjsp_to_isolated_table() -> None:
    assert rag_ingest.table_name_for_source("sumulas") == "jurisprudencia"
    assert rag_ingest.table_name_for_source("stj") == "jurisprudencia"
    assert rag_ingest.table_name_for_source("tjsp") == "tjsp_jurisprudencia"


def test_resolve_query_sources_distinguishes_none_from_explicit_empty_list() -> None:
    native_default, user_default, resolved_default = rag_query._resolve_query_sources(None)
    assert native_default == ["ratio"]
    assert isinstance(user_default, list)
    assert resolved_default[0] == "ratio"

    native_empty, user_empty, resolved_empty = rag_query._resolve_query_sources([])
    assert native_empty == []
    assert user_empty == []
    assert resolved_empty == []


def test_recent_timeline_reads_tjsp_table_alongside_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TimelineDB:
        def __init__(self) -> None:
            self.opened: list[str] = []
            self.tables = {
                "jurisprudencia": _FakeTimelineTable(
                    "jurisprudencia",
                    [
                        {
                            "doc_id": "stf-1",
                            "tipo": "acordao",
                            "tribunal": "STF",
                            "processo": "RE 1",
                            "relator": "Min. A",
                            "orgao_julgador": "Plenario",
                            "data_julgamento": "2026-03-18",
                            "_authority_level": "A",
                            "_authority_label": "Vinculante forte",
                        }
                    ],
                ),
                "tjsp_jurisprudencia": _FakeTimelineTable(
                    "tjsp_jurisprudencia",
                    [
                        {
                            "doc_id": "tjsp-1",
                            "tipo": "acordao",
                            "tribunal": "TJSP",
                            "processo": "Apelacao 1",
                            "relator": "Des. B",
                            "orgao_julgador": "1a Camara",
                            "data_julgamento": "2026-03-19",
                            "_authority_level": "D",
                            "_authority_label": "Orientativo",
                        }
                    ],
                ),
            }

        def open_table(self, name: str):
            self.opened.append(name)
            return self.tables[name]

    fake_db = _TimelineDB()
    monkeypatch.setattr(rag_query.lancedb, "connect", lambda _path: fake_db)

    rows = rag_query.get_recent_timeline_items(limit=5)

    assert fake_db.opened == ["jurisprudencia", "tjsp_jurisprudencia"]
    assert [row["tribunal"] for row in rows] == ["TJSP", "STF"]

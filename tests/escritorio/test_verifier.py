from backend.escritorio.verifier import (
    canonicalize_candidate,
    extract_citation_candidates,
    match_against_lancedb,
    match_against_rows,
    normalize_legal_text,
    validate_provenance,
    validar_cnj,
    verify_sections,
    verify_citation_reference,
)
from backend.escritorio.models import RatioEscritorioState


def test_normalize_legal_text_removes_accents_and_normalizes_whitespace():
    normalized = normalize_legal_text("  Súmula   7  do   STJ  ")

    assert normalized == "sumula 7 do stj"


def test_extract_citation_candidates_handles_articles_sumulas_and_resp():
    text = (
        "Nos termos do art. 186 do CC, da Súmula 7 do STJ e do REsp 1.234.567/SP, "
        "a tese nao prospera."
    )

    candidates = extract_citation_candidates(text)
    kinds = {item.kind for item in candidates}

    assert "legislacao" in kinds
    assert "sumula" in kinds
    assert "jurisprudencia" in kinds
    assert any(item.raw_text.lower().startswith("art. 186") for item in candidates)
    assert any("sumula 7 do stj" in item.normalized_text for item in candidates)
    assert any(item.class_name == "RESP" for item in candidates)


def test_extract_citation_candidates_handles_tema_lei_and_cnj():
    text = (
        "Tema 987 do STJ, Lei 8.078/1990 e processo 0001234-56.2024.8.26.0100 "
        "aparecem juntos no corpo do texto."
    )

    candidates = extract_citation_candidates(text)

    assert any(item.kind == "tema_repetitivo" and item.number == "987" for item in candidates)
    assert any(item.kind == "legislacao" and item.diploma == "LEI" for item in candidates)
    assert any(item.kind == "jurisprudencia" and item.class_name == "CNJ" for item in candidates)


def test_extract_citation_candidates_infers_theme_tribunal_from_nearby_context():
    text = (
        "O Supremo Tribunal Federal, sob a sistemática da repercussão geral, "
        "fixou entendimento no Tema 512 (RE 662.405)."
    )

    candidates = extract_citation_candidates(text)

    assert any(item.kind == "tema_repetitivo" and item.number == "512" and item.tribunal == "stf" for item in candidates)


def test_validar_cnj_rejects_invalid_number():
    assert validar_cnj("0001234-56.2024.8.26.0100") is False


def test_canonicalize_candidate_builds_stable_key_for_resp():
    candidate = [
        item
        for item in extract_citation_candidates("REsp 1.234.567/SP")
        if item.class_name == "RESP"
    ][0]

    canonical = canonicalize_candidate(candidate)

    assert canonical.canonical_key == "resp_1234567"


def test_match_against_rows_returns_strong_match_for_class_and_number():
    candidate = [
        item
        for item in extract_citation_candidates("REsp 1.234.567/SP")
        if item.class_name == "RESP"
    ][0]

    match = match_against_rows(
        candidate,
        [
            {
                "canonical_key": "resp_999999",
                "class_name": "RESP",
                "number": "999999",
            },
            {
                "canonical_key": "resp_1234567",
                "class_name": "RESP",
                "number": "1234567",
            },
        ],
    )

    assert match.level == "exact_match"
    assert match.exists is True


def test_validate_provenance_checks_evidence_pack_membership():
    assert validate_provenance("resp_1234567", ["resp_1234567", "sumula_7_stj"]) is True
    assert validate_provenance("resp_1234567", ["sumula_7_stj"]) is False


def test_match_against_lancedb_opens_registry_table_and_matches_rows():
    class _FakeTable:
        def __init__(self, rows):
            self.rows = rows
            self.search_terms = []

        def search(self, term):
            self.search_terms.append(term)
            return self

        def limit(self, n):  # noqa: ARG002
            return self

        def to_list(self):
            return list(self.rows)

    class _FakeRegistry:
        def __init__(self):
            self.opened = []

        def open_table(self, raw_path, table_name):
            self.opened.append((str(raw_path), table_name))
            return _FakeTable(
                [
                    {
                        "canonical_key": "resp_1234567",
                        "class_name": "RESP",
                        "number": "1234567",
                    }
                ]
            )

    candidate = [
        item
        for item in extract_citation_candidates("REsp 1.234.567/SP")
        if item.class_name == "RESP"
    ][0]
    registry = _FakeRegistry()

    match = match_against_lancedb(
        candidate,
        registry=registry,
        lance_dir="C:/tmp/lancedb_store",
        table_name="jurisprudencia",
    )

    assert match.level == "exact_match"
    assert registry.opened == [("C:/tmp/lancedb_store", "jurisprudencia")]
    assert candidate.number == "1234567"


def test_verify_citation_reference_returns_best_match_summary():
    class _FakeArrowTable:
        def __init__(self, rows):
            self._rows = rows

        def to_pylist(self):
            return list(self._rows)

    class _FakeLanceDataset:
        def __init__(self, rows):
            self.schema = type("Schema", (), {"names": list(rows[0].keys()) if rows else []})()
            self._rows = rows

        def to_table(self, columns=None, filter=None):  # noqa: ARG002
            if columns:
                return _FakeArrowTable([{key: row.get(key) for key in columns} for row in self._rows])
            return _FakeArrowTable(self._rows)

    class _FakeTable:
        def __init__(self, rows):
            self.rows = rows

        def to_lance(self):
            return _FakeLanceDataset(self.rows)

    class _FakeRegistry:
        def open_table(self, raw_path, table_name):  # noqa: ARG002
            return _FakeTable(
                [
                    {
                        "canonical_key": "sumula_7_stj",
                        "class_name": None,
                        "number": "7",
                    }
                ]
            )

    result = verify_citation_reference(
        "Súmula 7 do STJ",
        registry=_FakeRegistry(),
        lance_dir="C:/tmp/lancedb_store",
    )

    assert result["exists"] is True
    assert result["level"] == "exact_match"
    assert result["best_candidate"]["canonical_key"] == "sumula_7_stj"


def test_verify_sections_uses_section_provenance():
    class _FakeArrowTable:
        def __init__(self, rows):
            self._rows = rows

        def to_pylist(self):
            return list(self._rows)

    class _FakeLanceDataset:
        def __init__(self, rows):
            self.schema = type("Schema", (), {"names": list(rows[0].keys()) if rows else []})()
            self._rows = rows

        def to_table(self, columns=None, filter=None):  # noqa: ARG002
            if columns:
                return _FakeArrowTable([{key: row.get(key) for key in columns} for row in self._rows])
            return _FakeArrowTable(self._rows)

    class _FakeTable:
        def __init__(self, rows):
            self.rows = rows

        def search(self, term):  # noqa: ARG002
            return self

        def limit(self, n):  # noqa: ARG002
            return self

        def to_list(self):
            return list(self.rows)

        def to_lance(self):
            return _FakeLanceDataset(self.rows)

    class _FakeRegistry:
        def open_table(self, raw_path, table_name):  # noqa: ARG002
            return _FakeTable(
                [
                    {
                        "canonical_key": "resp_1234567",
                        "class_name": "RESP",
                        "number": "1234567",
                    }
                ]
            )

    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        peca_sections={"do_direito": "Conforme REsp 1.234.567/SP, a tese procede."},
        evidence_pack={"do_direito": ["resp_1234567"]},
    )

    results = verify_sections(
        state,
        registry=_FakeRegistry(),
        lance_dir="C:/tmp/lancedb_store",
    )

    assert len(results) == 1
    assert results[0]["section"] == "do_direito"
    assert results[0]["level"] == "exact_match"
    assert results[0]["provenance_ok"] is True


def test_verify_sections_reports_placeholder_markers_as_unverified():
    class _FakeRegistry:
        def open_table(self, raw_path, table_name):  # noqa: ARG002
            raise AssertionError("placeholder verification should not hit LanceDB")

    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        peca_sections={"do_direito": "Tema 512 [VERIFICAR]"},
    )

    results = verify_sections(
        state,
        registry=_FakeRegistry(),
        lance_dir="C:/tmp/lancedb_store",
    )

    assert len(results) == 1
    assert results[0]["section"] == "do_direito"
    assert results[0]["referencia"] == "Tema 512 [VERIFICAR]"
    assert results[0]["level"] == "unverified"
    assert results[0]["kind"] == "placeholder"


def test_verify_sections_accepts_theme_with_tribunal_inferred_from_context():
    class _FakeArrowTable:
        def __init__(self, rows):
            self._rows = rows

        def to_pylist(self):
            return list(self._rows)

    class _FakeLanceDataset:
        def __init__(self, rows):
            self.schema = type("Schema", (), {"names": list(rows[0].keys()) if rows else []})()
            self._rows = rows

        def to_table(self, columns=None, filter=None):  # noqa: ARG002
            if columns:
                return _FakeArrowTable([{key: row.get(key) for key in columns} for row in self._rows])
            return _FakeArrowTable(self._rows)

    class _FakeTable:
        def __init__(self, rows):
            self.rows = rows

        def search(self, term):  # noqa: ARG002
            return self

        def limit(self, n):  # noqa: ARG002
            return self

        def to_list(self):
            return list(self.rows)

        def to_lance(self):
            return _FakeLanceDataset(self.rows)

    class _FakeRegistry:
        def open_table(self, raw_path, table_name):  # noqa: ARG002
            return _FakeTable(
                [
                    {
                        "canonical_key": "tema_512_stf",
                        "class_name": None,
                        "number": "512",
                    }
                ]
            )

    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        peca_sections={
            "do_direito": (
                "O Supremo Tribunal Federal, sob a sistemática da repercussão geral, "
                "fixou entendimento no Tema 512 (RE 662.405)."
            )
        },
    )

    results = verify_sections(
        state,
        registry=_FakeRegistry(),
        lance_dir="C:/tmp/lancedb_store",
    )

    assert any(item["referencia"] == "Tema 512" and item["level"] == "exact_match" for item in results)

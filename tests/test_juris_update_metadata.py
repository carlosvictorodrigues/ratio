from __future__ import annotations

import json
import sqlite3

from backend import juris_update


def test_stf_acordao_builds_rich_metadata_and_marks() -> None:
    source = {
        "id": "123",
        "dg_unique": "DG-XYZ",
        "titulo": "RECURSO EXTRAORDINARIO",
        "processo_numero": "12345",
        "processo_classe_processual_unificada_classe_sigla": "RE",
        "julgamento_data": "2026-02-14",
        "publicacao_data": "2026-02-25",
        "relator_processo_nome": "Min. Teste",
        "orgao_julgador": "Tribunal Pleno",
        "ementa_texto": "Ementa de teste.",
        "inteiro_teor_url": "https://jurisprudencia.stf.jus.br/pages/search/sjur999999/false",
        "documental_tese_texto": "Tese de teste.",
        "documental_tese_tema_texto": "Tema 1000",
        "documental_indexacao_texto": "Direito constitucional",
        "documental_legislacao_citada_texto": "CF/88 art. 5",
        "is_repercussao_geral": True,
    }

    doc = juris_update._stf_doc_from_acordao(source)
    assert doc is not None
    assert doc.url.startswith("https://jurisprudencia.stf.jus.br/")

    metadata = json.loads(doc.metadata_extra)
    assert metadata["id"] == "123"
    assert metadata["dg_unique"] == "DG-XYZ"
    assert metadata["titulo"] == "RECURSO EXTRAORDINARIO"
    assert metadata["classe"] == "RE"
    assert metadata["numero_processo"] == "12345"
    assert metadata["publicacao_data"] == "2026-02-25"
    assert metadata["inteiro_teor_url"].startswith("https://jurisprudencia.stf.jus.br/")
    assert metadata["is_repercussao_geral"] is True
    assert "marcacoes" in metadata
    assert "stf" in metadata["marcacoes"]
    assert "acordao" in metadata["marcacoes"]


def test_stj_load_docs_by_ids_sets_pdf_url_and_rich_metadata() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        juris_update._ensure_stj_schema(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO stj_informativos (
                informativo_numero, source_pdf, processo, ramo_direito, tema, destaque,
                relator, orgao_julgador, data_julgamento, data_publicacao, texto_integral,
                tribunal, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STJ', ?)
            """,
            (
                "879",
                "Informativo_0879.pdf",
                "AgRg no HC 123456",
                "Processual Penal",
                "Tema de teste",
                "Destaque de teste",
                "Min. Teste",
                "Sexta Turma",
                "10/2/2026",
                "03/03/2026",
                "Texto integral de teste",
                "2026-03-04T12:00:00",
            ),
        )
        row_id = int(cursor.lastrowid)
        conn.commit()

        docs = juris_update._load_stj_docs_by_ids(conn, [row_id])
        assert len(docs) == 1
        doc = docs[0]
        assert doc.url.endswith("GetPDFINFJ?edicao=0879")

        metadata = json.loads(doc.metadata_extra)
        assert metadata["informativo_numero"] == "879"
        assert metadata["source_pdf"] == "Informativo_0879.pdf"
        assert metadata["tema"] == "Tema de teste"
        assert metadata["destaque"] == "Destaque de teste"
        assert metadata["data_publicacao"] == "2026-03-03"
        assert metadata["pdf_url"].endswith("GetPDFINFJ?edicao=0879")
        assert "marcacoes" in metadata
        assert "stj" in metadata["marcacoes"]
        assert "informativo" in metadata["marcacoes"]
    finally:
        conn.close()


def test_marcacoes_do_not_explode_and_respect_limit() -> None:
    tags = juris_update._build_marcacoes(
        "STF",
        "acordao",
        "tema, repercussao geral, constitucionalidade de clausula contratual",
        "Tribunal Pleno",
        max_tags=4,
    )
    assert len(tags) == 4
    assert tags[0] == "stf"
    assert tags[1] == "acordao"
    assert "tribunal_pleno" in tags


def test_stj_merge_repair_payload_recovers_broken_fields() -> None:
    broken = {
        "informativo_numero": "879",
        "source_pdf": "Informativo_0879.pdf",
        "processo": "AgRg",
        "ramo_direito": "Outros",
        "tema": "",
        "destaque": "",
        "relator": "istro Rogerio Schietti Cruz",
        "orgao_julgador": "",
        "data_julgamento": "",
        "data_publicacao": "",
        "texto_integral": "PROCESSO AgRg no HC 123.456. Rel. Ministro Rogerio Schietti Cruz. Sexta Turma, julgado em 10/2/2026. DJe 03/03/2026.",
    }
    payload = {
        "processo": "AgRg no HC 123.456",
        "ramo_direito": "Processual Penal",
        "tema": "Acordo de nao persecucao penal",
        "destaque": "E valida a recusa do Ministerio Publico.",
        "relator": "Ministro Rogerio Schietti Cruz",
        "orgao_julgador": "Sexta Turma",
        "data_julgamento": "10/02/2026",
        "data_publicacao": "03/03/2026",
        "confidence": 0.91,
    }

    merged, changed = juris_update._stj_merge_repair_payload(
        broken,
        payload,
        min_confidence=0.62,
    )
    assert changed is True
    assert merged["processo"] == "AgRg no HC 123.456"
    assert merged["relator"] == "Ministro Rogerio Schietti Cruz"
    assert merged["orgao_julgador"] == "Sexta Turma"
    assert merged["data_julgamento"] == "10/02/2026"
    assert merged["data_publicacao"] == "03/03/2026"
    assert merged["ramo_direito"] == "Processual Penal"


def test_stj_merge_repair_payload_respects_confidence_floor() -> None:
    broken = {
        "processo": "",
        "ramo_direito": "Outros",
        "tema": "",
        "destaque": "",
        "relator": "",
        "orgao_julgador": "",
        "data_julgamento": "",
        "data_publicacao": "",
        "texto_integral": "texto",
    }
    payload = {
        "processo": "HC 123",
        "ramo_direito": "Penal",
        "relator": "Ministro Teste",
        "confidence": 0.2,
    }
    merged, changed = juris_update._stj_merge_repair_payload(
        broken,
        payload,
        min_confidence=0.62,
    )
    assert changed is False
    assert merged == broken


def test_stj_verify_expected_editions_detects_missing() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        juris_update._ensure_stj_schema(conn)
        conn.execute(
            """
            INSERT INTO stj_informativos (
                informativo_numero, source_pdf, processo, ramo_direito, tema, destaque,
                relator, orgao_julgador, data_julgamento, data_publicacao, texto_integral,
                tribunal, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STJ', ?)
            """,
            (
                "879",
                "Informativo_0879.pdf",
                "AgRg no HC 123456",
                "Processual Penal",
                "Tema de teste",
                "Destaque de teste",
                "Min. Teste",
                "Sexta Turma",
                "10/2/2026",
                "03/03/2026",
                "Texto integral de teste",
                "2026-03-04T12:00:00",
            ),
        )
        conn.commit()
        out = juris_update._stj_verify_expected_editions(conn, expected_editions=[879, 880])
        assert out["expected_total"] == 2
        assert out["present_total"] == 1
        assert out["missing_total"] == 1
        assert out["missing_editions"] == [880]
    finally:
        conn.close()


def test_embed_docs_falls_back_to_hash_on_quota() -> None:
    class _QuotaModels:
        def embed_content(self, **_kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota")

    class _QuotaClient:
        def __init__(self) -> None:
            self.models = _QuotaModels()

    docs = [
        juris_update.UpdateDocument(
            doc_id="stf-ac-1",
            tribunal="STF",
            tipo="acordao",
            processo="RE 1",
            relator="Min. A",
            ramo_direito="Constitucional",
            data_julgamento="2026-01-01",
            orgao_julgador="Tribunal Pleno",
            texto_busca="texto de busca um",
            texto_integral="texto integral um",
            url="https://example.test/1",
            metadata_extra="{}",
            source_key="stf_acordaos",
        ),
        juris_update.UpdateDocument(
            doc_id="stf-ac-2",
            tribunal="STF",
            tipo="acordao",
            processo="RE 2",
            relator="Min. B",
            ramo_direito="Constitucional",
            data_julgamento="2026-01-02",
            orgao_julgador="Tribunal Pleno",
            texto_busca="texto de busca dois",
            texto_integral="texto integral dois",
            url="https://example.test/2",
            metadata_extra="{}",
            source_key="stf_acordaos",
        ),
    ]

    records, stats = juris_update._embed_docs(
        docs=docs,
        gemini_client=_QuotaClient(),
        embed_model="gemini-embedding-001",
        embed_batch_size=8,
        fallback_on_quota=True,
        progress_cb=None,
    )
    assert len(records) == 2
    assert stats["hash"] == 2
    assert stats["gemini"] == 0
    assert len(records[0]["vector"]) == juris_update.EMBED_DIM


def test_missing_doc_ids_preserves_order() -> None:
    class _FakeTable:
        def __init__(self, existing: set[str]) -> None:
            self._existing = existing

        def search(self):
            return self

        def where(self, clause, prefilter=True):  # noqa: ARG002
            self._clause = clause
            return self

        def limit(self, _n):
            return self

        def to_list(self):
            values = []
            for item in ["a", "b", "c"]:
                if item in self._existing and item in self._clause:
                    values.append({"doc_id": item})
            return values

    missing = juris_update._missing_doc_ids(_FakeTable({"a"}), ["a", "b", "c", "b"])
    assert missing == ["b", "c"]


def test_resolve_stf_start_date_uses_cursor_inside_same_year() -> None:
    resolved = juris_update._resolve_stf_start_date(year=2026, since_date="2026-03-04")
    assert resolved.isoformat() == "2026-03-04"


def test_resolve_stf_start_date_ignores_cursor_from_other_year() -> None:
    resolved = juris_update._resolve_stf_start_date(year=2026, since_date="2025-12-31")
    assert resolved.isoformat() == "2026-01-01"


def test_stj_extractors_capture_full_processo_and_relator_titles() -> None:
    line = (
        "REsp 2.266.708-MS, Rel. Ministra Nancy Andrighi, Corte Especial, "
        "por maioria, julgado em 11/12/2025, DJEN 19/12/2025."
    )
    assert juris_update._stj_extract_processo(line) == "REsp 2.266.708-MS"
    assert juris_update._stj_extract_relator(line) == "Ministra Nancy Andrighi"

    aggravated = (
        "AgRg no RHC 215.549-GO, Rel. Ministro Otávio de Almeida Toledo "
        "(Desembargador convocado do TJSP), Rel. para acórdão Ministro "
        "Rogerio Schietti Cruz, Sexta Turma, por unanimidade, julgado em 10/2/2026."
    )
    assert juris_update._stj_extract_processo(aggravated) == "AgRg no RHC 215.549-GO"
    assert juris_update._stj_extract_relator(aggravated) == "Ministro Otávio de Almeida Toledo"


def test_stj_parse_new_format_keeps_segredo_de_justica_without_gemini_repair() -> None:
    text = """
PROCESSO
Processo em segredo de justiça, Rel. Ministra Nancy Andrighi, Terceira
Turma, por unanimidade, julgado em 3/2/2026, DJEN 9/2/2026.
RAMO DO DIREITO
DIREITO CIVIL
TEMA
Responsabilidade civil objetiva.
DESTAQUE
Hospital responde objetivamente por infeccao hospitalar em recem-nascido.
INFORMAÇÕES DO INTEIRO TEOR
Texto complementar suficientemente longo para manter o bloco estruturado e
reproduzir o parser do informativo STJ.
""".strip()

    records = juris_update._stj_parse_new_format(text, "Informativo_0880.pdf", "880")

    assert len(records) == 1
    record = records[0]
    assert record["processo"] == "Processo em segredo de justiça"
    assert record["relator"] == "Ministra Nancy Andrighi"
    assert record["orgao_julgador"] == "Terceira Turma"
    assert record["data_julgamento"] == "3/2/2026"
    assert record["data_publicacao"] == "9/2/2026"
    assert record["ramo_direito"] == "Civil"
    assert juris_update._stj_record_needs_gemini_repair(record) is False


def test_stj_extract_processo_supports_additional_stj_classes() -> None:
    cases = {
        "RO 285-DF, Rel. Ministro Raul Araújo, Quarta Turma, por unanimidade, julgado em 16/12/2025, DJEN 23/12/2025.": "RO 285-DF",
        "AgInt no EAREsp 1.742.202-SP, Rel. Ministro Luis Felipe Salomão, Corte Especial, por maioria, julgado em 5/11/2025.": "AgInt no EAREsp 1.742.202-SP",
        "APn 1.079-DF, Rel. Ministro Antonio Carlos Ferreira, Corte Especial, por unanimidade, julgado em 15/10/2025, DJEN 23/10/2025.": "APn 1.079-DF",
        "TutCautAnt 672-SP, Rel. Ministro Raul Araújo, Quarta Turma, por unanimidade, julgado em 24/9/2024, DJe 30/9/2024.": "TutCautAnt 672-SP",
        "QC 6-DF, Rel. Ministro Herman Benjamin, Corte Especial, por unanimidade, julgado em 10/6/2024, DJe 26/6/2024.": "QC 6-DF",
        "IDC 22-RO, Rel. Ministro Messod Azulay Neto, Terceira Seção, por unanimidade, julgado em 23/8/2023, DJe 25/8/2023.": "IDC 22-RO",
        "PUIL 825-RS, Rel. Ministro Sérgio Kukina, Primeira Seção, por unanimidade, julgado em 24/5/23.": "PUIL 825-RS",
        "AgInt no PUIL 3.272-MG, Rel. Ministro Paulo de Tarso Sanseverino, Segunda Seção, por unanimidade, julgado em 14/3/2023.": "AgInt no PUIL 3.272-MG",
        "AC 46-RS, Rel. Ministro Francisco Falcão, Segunda Turma, por unanimidade, julgado em 23/5/2023.": "AC 46-RS",
        "AgRg na RvCr 5.735-DF, Rel. Min. Ribeiro Dantas, Terceira Seção, por unanimidade, julgado em 11/05/2022, DJe 16/05/2022.": "AgRg na RvCr 5.735-DF",
        "IF 113-PR, Rel. Min. Jorge Mussi, Corte Especial, por unanimidade, julgado em 06/04/2022.": "IF 113-PR",
        "Inq 1.190-DF, Rel. Min. Maria Isabel Gallotti, Corte Especial, por unanimidade, julgado em 15/09/2021.": "Inq 1.190-DF",
        "HDE 4.289-EX, Rel. Min. Raul Araújo, Corte Especial, por unanimidade, julgado em 18/08/2021, DJe 23/08/2021.": "HDE 4.289-EX",
        "MI 324-DF, Rel. Min. Herman Benjamin, Corte Especial, por unanimidade, julgado em 19/02/2020, DJe 25/08/2020.": "MI 324-DF",
        "AgRg na ExSusp 209-DF, Rel. Min. Antonio Saldanha Palheiro, Terceira Seção, por unanimidade, julgado em 12/08/2020, DJe 17/08/2020.": "AgRg na ExSusp 209-DF",
        "AgInt na ExSusp 198-PE, Rel. Min. Marco Aurélio Bellizze, Segunda Seção, por unanimidade, julgado em 17/03/2020, DJe 20/03/2020.": "AgInt na ExSusp 198-PE",
        "ExeMS 18.782-DF, Rel. Min. Mauro Campbell Marques, por unanimidade, julgado em 12/09/2018, DJe 03/10/2018.": "ExeMS 18.782-DF",
        "SEC 14.812-EX, Rel. Min. Nancy Andrighi, por unanimidade, julgado em 16/05/2018, DJe 23/05/2018.": "SEC 14.812-EX",
        "SIRDR 7-PR, Rel. Min. Paulo de Tarso Sanseverino, DJe 23/6/2017. (TEMA 4)": "SIRDR 7-PR",
        "Processo em segredo judicial, Rel. Min. Marco Aurélio Bellizze, Terceira Turma, por maioria, julgado em 21/06/2022, DJe 30/06/2022.": "Processo em segredo de justiça",
        "Processo em segredo de justiçaa, Rel. Min. Nancy Andrighi, Terceira Turma, por unanimidade, julgado em 18/10/2022, DJe 21/10/2022.": "Processo em segredo de justiça",
    }

    for line, expected in cases.items():
        assert juris_update._stj_extract_processo(line) == expected


def test_stj_fix_common_ocr_glitches_normalizes_ministro_prefix_case() -> None:
    assert juris_update._stj_fix_common_ocr_glitches("min. Benedito Gonçalves") == "Min. Benedito Gonçalves"
    assert juris_update._stj_fix_common_ocr_glitches("ministra Nancy Andrighi") == "Ministra Nancy Andrighi"
    assert juris_update._stj_fix_common_ocr_glitches("ministro Humberto Martins") == "Ministro Humberto Martins"

from types import SimpleNamespace

import rag.query as query_mod


class _FakeResponse:
    def __init__(self, text: str, finish_reason: str) -> None:
        self.text = text
        self.candidates = [SimpleNamespace(finish_reason=finish_reason)]


class _FakeModels:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []
        self.configs: list[object] = []

    def generate_content(self, *, model, contents, config):  # noqa: ANN001
        self.calls.append(str(model))
        self.configs.append(config)
        if not self._responses:
            raise AssertionError("No fake responses left")
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.models = _FakeModels(responses)


def test_generate_answer_uses_fallback_when_primary_hits_max_tokens(monkeypatch):
    fake_client = _FakeClient(
        [
            _FakeResponse("resposta truncada", "MAX_TOKENS"),
            _FakeResponse("resposta completa", "STOP"),
        ]
    )
    monkeypatch.setattr(query_mod, "get_gemini_client", lambda: fake_client)
    monkeypatch.setattr(query_mod, "_resolve_best_gemini_model", lambda name: str(name or ""))

    answer = query_mod.generate_answer(
        "pergunta",
        "contexto",
        generation_model="modelo-principal",
        generation_fallback_model="modelo-fallback",
    )

    assert answer == "resposta completa"
    assert fake_client.models.calls == ["modelo-principal", "modelo-fallback"]


def test_build_generation_config_notice_reports_max_tokens_and_fallback():
    warning = query_mod._build_generation_config_notice(
        {
            "attempts": [
                {
                    "model": "gemini-3-pro-preview",
                    "finish_reason": "MAX_TOKENS",
                    "hit_max_tokens": True,
                    "text_chars": 280,
                },
                {
                    "model": "gemini-2.5-flash",
                    "finish_reason": "STOP",
                    "hit_max_tokens": False,
                    "text_chars": 2200,
                },
            ],
            "selected_model": "gemini-2.5-flash",
            "used_fallback": True,
        }
    )

    assert warning["code"] == "gemini_max_tokens_fallback"
    assert "gemini-3-pro-preview" in warning["message"]
    assert "gemini-2.5-flash" in warning["message"]
    assert "Tokens Max da Resposta" in warning["message"]
    assert "Orcamento de Raciocinio (Thinking)" in warning["message"]


def test_build_theme_sumula_ementa_enrichment_adds_literal_excerpt():
    answer = "No tema de repercussao geral 280, a tese foi reiterada [DOC. 1]."
    docs = [
        {
            "tipo": "acordao",
            "processo": "RE 603616",
            "texto_integral": (
                "EMENTA: A entrada forcada em domicilio sem mandado judicial so e licita quando houver "
                "fundadas razoes devidamente justificadas a posteriori.\n\nAcordam os ministros..."
            ),
            "texto_busca": "",
        }
    ]

    block = query_mod._build_theme_sumula_ementa_enrichment(answer, docs)
    assert "Ementas literais para temas/sumulas citados:" in block
    assert "fundadas razoes" in block
    assert "[DOC. 1]" in block


def test_extract_ementa_literal_requires_real_ementa_marker():
    row_without_marker = {
        "texto_integral": "Tema 1234 - legitimidade passiva da UniÃ£o e competÃªncia da JustiÃ§a Federal.",
        "texto_busca": "",
    }
    assert query_mod._extract_ementa_literal(row_without_marker, require_marker=True) == ""


def test_build_document_map_returns_json_block():
    docs = [
        {
            "tipo": "acordao",
            "tribunal": "STF",
            "processo": "RE 123",
            "data_julgamento": "2024-01-02",
            "texto_integral": "EMENTA: Texto completo da ementa para teste.\n\nAcordam os ministros.",
            "texto_busca": "",
        }
    ]
    block = query_mod._build_document_map(docs, [1])
    assert block.startswith("```json")
    assert '"documento": "DOCUMENTO 1"' in block
    assert '"tribunal": "STF"' in block
    assert '"ementa_literal"' in block


def test_build_document_map_avoids_duplicate_enunciado_and_ementa():
    docs = [
        {
            "tipo": "acordao",
            "tribunal": "STF",
            "processo": "RE 987",
            "data_julgamento": "2025-03-01",
            "texto_integral": (
                "EMENTA: Concurso pÃºblico. Tema 485 da repercussÃ£o geral. NÃ£o compete ao Poder JudiciÃ¡rio "
                "substituir a banca examinadora para reexaminar critÃ©rios de correÃ§Ã£o, salvo ilegalidade.\n\n"
                "Acordam os ministros."
            ),
            "texto_busca": "",
        }
    ]
    block = query_mod._build_document_map(docs, [1])
    assert '"ementa_literal"' in block
    assert '"enunciado_tese"' not in block


def test_validate_answer_omits_document_list_and_normalizes_doc_label():
    answer = "A conclusao central esta no precedente [DOCUMENTO 1]."
    docs = [
        {
            "tipo": "acordao",
            "tribunal": "STF",
            "processo": "RE 632853",
            "data_julgamento": "2015-04-23",
            "texto_integral": "EMENTA: Controle jurisdicional de concurso publico.\n\nAcordam os ministros.",
            "texto_busca": "",
        }
    ]
    out = query_mod._validate_answer(answer, docs, paragraph_citation_min_chars=999)
    assert "Documentos citados:" not in out
    assert "Documentos citados (JSON):" not in out
    assert "[DOC. 1]" in out
    assert "[DOCUMENTO 1]" not in out


def test_generate_answer_prompt_blocks_internal_labels(monkeypatch):
    fake_client = _FakeClient([_FakeResponse("resposta", "STOP")])
    monkeypatch.setattr(query_mod, "get_gemini_client", lambda: fake_client)
    monkeypatch.setattr(query_mod, "_resolve_best_gemini_model", lambda name: str(name or ""))

    result = query_mod.generate_answer(
        "pergunta",
        "contexto",
        generation_model="modelo-principal",
        generation_fallback_model="modelo-fallback",
    )
    assert result == "resposta"

    system_prompt = str(getattr(fake_client.models.configs[0], "system_instruction", "") or "")
    lowered = system_prompt.lower()
    assert "nivel a-e" not in lowered
    assert "tese material" not in lowered
    assert "barreira processual" not in lowered


def test_format_context_omits_internal_ranking_labels():
    docs = [
        {
            "tipo": "acordao",
            "tribunal": "STF",
            "processo": "RE 1",
            "doc_id": "id-1",
            "ramo_direito": "Administrativo",
            "data_julgamento": "2025-01-10",
            "relator": "Min. X",
            "orgao_julgador": "Plenario",
            "_authority_level": "B",
            "_authority_label": "Precedente qualificado",
            "_authority_reason": "Tema de repercussao geral",
            "_document_role": "tese_material",
            "texto_integral": "Trecho util para teste.",
            "texto_busca": "",
        }
    ]
    context = query_mod.format_context(docs, query="teste")
    assert "Forca normativa: Nivel" not in context
    assert "Papel no ranking:" not in context
    assert "Qualificacao do precedente:" in context

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_authority_levels_have_detailed_help_text_in_schema():
    query_py = _read("rag/query.py")
    assert '"key": "authority_level_a_boost"' in query_py
    assert '"help": "Nivel A' in query_py
    assert '"key": "authority_level_b_boost"' in query_py
    assert '"help": "Nivel B' in query_py
    assert '"key": "authority_level_c_boost"' in query_py
    assert '"help": "Nivel C' in query_py
    assert '"key": "authority_level_d_boost"' in query_py
    assert '"help": "Nivel D' in query_py
    assert '"key": "authority_level_e_boost"' in query_py
    assert '"help": "Nivel E' in query_py


def test_generation_prompt_requires_tema_de_repercussao_geral_and_enunciado():
    query_py = _read("rag/query.py")
    assert "tema de repercussao geral" in query_py
    assert "nunca 'tema da repercussao geral'" in query_py
    assert "explique o enunciado/tese" in query_py


def test_document_map_can_include_enunciado_ou_tese():
    query_py = _read("rag/query.py")
    assert "enunciado_tese" in query_py
    assert "_extract_normative_statement" in query_py


def test_answer_validation_no_longer_appends_audit_warning_block():
    query_py = _read("rag/query.py")
    assert "paragrafo(s) extensos sem citacao explicita" not in query_py
    assert "Referencias fora do intervalo retornado" not in query_py


def test_generation_output_tokens_is_tunable_with_higher_default():
    query_py = _read("rag/query.py")
    assert '"generation_max_output_tokens"' in query_py
    assert '"label": "Tokens Max da Resposta"' in query_py
    assert 'GENERATION_MAX_OUTPUT_TOKENS = int(os.getenv("GENERATION_MAX_OUTPUT_TOKENS", "3600"))' in query_py
    assert '"generation_max_output_tokens": GENERATION_MAX_OUTPUT_TOKENS' in query_py


def test_generation_thinking_budget_is_tunable_with_safe_default():
    query_py = _read("rag/query.py")
    assert 'GENERATION_THINKING_BUDGET = int(os.getenv("GENERATION_THINKING_BUDGET", "128"))' in query_py
    assert '"generation_thinking_budget": GENERATION_THINKING_BUDGET' in query_py
    assert '"key": "generation_thinking_budget"' in query_py
    assert '"label": "Orcamento de Raciocinio (Thinking)"' in query_py


def test_richer_response_defaults_are_enabled_for_context_and_rerank():
    query_py = _read("rag/query.py")
    assert 'TOPK_RERANK = int(os.getenv("TOPK_RERANK", "11"))' in query_py
    assert 'CONTEXT_MAX_PASSAGES_PER_DOC = int(os.getenv("CONTEXT_MAX_PASSAGES_PER_DOC", "5"))' in query_py
    assert 'CONTEXT_MAX_PASSAGE_CHARS = int(os.getenv("CONTEXT_MAX_PASSAGE_CHARS", "1000"))' in query_py
    assert 'CONTEXT_MAX_DOC_CHARS = int(os.getenv("CONTEXT_MAX_DOC_CHARS", "2500"))' in query_py

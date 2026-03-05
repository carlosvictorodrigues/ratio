from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_rag_tuning_exposes_gemini_rerank_model():
    content = _read("rag/query.py")
    assert '"gemini_rerank_model": GEMINI_RERANK_MODEL' in content
    assert '"key": "gemini_rerank_model"' in content
    assert "Modelo do Reranker Gemini" in content


def test_compute_semantic_scores_accepts_runtime_gemini_rerank_model():
    content = _read("rag/query.py")
    assert "gemini_rerank_model: Optional[str] = None" in content
    assert "_semantic_scores_gemini(query, results, model_name_override=model_name)" in content


def test_local_reranker_defaults_to_multilingual_legal_model():
    content = _read("rag/query.py")
    assert (
        'RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")'
        in content
    )
    assert "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1" in content


def test_local_reranker_has_probe_and_fallback_chain():
    content = _read("rag/query.py")
    assert "RERANKER_MODEL_FALLBACKS = tuple(" in content
    assert "def _probe_cross_encoder_model(" in content
    assert "subprocess.run(" in content
    assert "--probe-reranker" in content

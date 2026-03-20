from __future__ import annotations

import importlib
import io
import json
import re
import sys
import threading
import time
import types
from pathlib import Path

import pytest

pytest.importorskip("google.genai", reason="backend.main requires google-genai")
from fastapi.testclient import TestClient


def _load_backend_with_stub():
    stub = types.ModuleType("rag.query")

    stub.EXPLAIN_MODEL = "stub-explain"
    stub.GEMINI_RERANK_MODEL = "stub-gemini-rerank"
    stub.GENERATION_MODEL = "stub-generation"
    stub.GENERATION_PROVIDER = "gemini"
    stub.RERANKER_BACKEND = "local"
    stub.RERANKER_MODEL = "stub-reranker"
    stub._gemini_has_key = False
    stub._gemini_last_model = ""
    stub._anthropic_has_key = False

    def run_query(**_kwargs):
        return "stub answer", [], {"source": "stub"}

    def explain_answer(**_kwargs):
        return "stub explanation"

    def orgao_label(raw: str) -> str:
        return raw or "Indefinido"

    def type_label(tipo: str) -> str:
        return tipo or "Documento"

    def get_rag_tuning_defaults():
        return {"semantic_weight": 0.45, "gemini_rerank_model": "gemini-2.5-pro"}

    def get_rag_tuning_schema():
        return [
            {"key": "semantic_weight", "label": "Peso Semantico"},
            {"key": "gemini_rerank_model", "label": "Modelo do Reranker Gemini"},
        ]

    def has_gemini_api_key():
        return bool(stub._gemini_has_key)

    def configure_gemini_api_key(
        api_key: str,
        *,
        validate: bool = False,
        test_model: str = "",
        validation_timeout_ms: int = 12000,
    ):
        key = str(api_key or "").strip()
        if not key:
            raise RuntimeError("GEMINI_API_KEY ausente.")
        if key == "invalid-key":
            raise RuntimeError("API key not valid.")
        stub._gemini_has_key = True
        stub._gemini_last_model = test_model or "gemini-2.5-flash"
        return {"validated": bool(validate), "model": stub._gemini_last_model}

    def get_supported_generation_models():
        return ["gemini-3.1-pro-preview", "gemini-2.5-flash"]

    def get_persona_prompt_defaults():
        return {
            "visao_geral": "",
            "parecer": "Prompt padrao de parecer.",
            "estudos": "Prompt padrao de estudos.",
            "peticao": "Prompt padrao de peticao.",
        }

    class _StubModels:
        def generate_content(self, **_kwargs):
            raise RuntimeError("stub generate_content should be mocked in tests")

    class _StubClient:
        def __init__(self):
            self.models = _StubModels()

    def get_gemini_client():
        return _StubClient()

    def get_reranker_warning():
        return ""

    def get_recent_timeline_items(limit=20, tribunal=None, tipos=None, days_back=365):
        return [
            {
                "doc_id": "stub-1",
                "tipo": "sumula_vinculante",
                "tipo_label": "Súmula Vinculante",
                "tribunal": "STF",
                "processo": "SV 123",
                "relator": "Min. Exemplo",
                "orgao_julgador": "Tribunal Pleno",
                "data_julgamento": "2026-01-15",
                "authority_level": "A",
                "authority_label": "Vinculante Forte",
            }
        ]

    def check_topic_matches(topics, top_k=5):
        return [
            [{"doc_id": "stub-match-1", "tipo": "acordao", "tipo_label": "Acórdão",
              "tribunal": "STF", "processo": "RE 123456", "relator": "Min. Stub",
              "data_julgamento": "2026-03-01"}]
        ] * len(topics)

    def configure_anthropic_api_key(api_key: str, *, validate: bool = False):
        key = str(api_key or "").strip()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY ausente.")
        stub._anthropic_has_key = True
        return {"validated": bool(validate)}

    def has_anthropic_api_key():
        return bool(stub._anthropic_has_key)

    def get_anthropic_client():
        return None

    def get_supported_claude_models():
        return ["claude-sonnet-4-20250514"]

    def get_informativo_items(limit=20, tribunal=None, offset=0):
        return []

    def summarize_informativo_items(items, model_name=None):
        return {"items": items, "summary": "", "model": model_name or "stub-summary"}

    stub.run_query = run_query
    stub.get_reranker_warning = get_reranker_warning
    stub.get_recent_timeline_items = get_recent_timeline_items
    stub.check_topic_matches = check_topic_matches
    stub.explain_answer = explain_answer
    stub.orgao_label = orgao_label
    stub.type_label = type_label
    stub.get_rag_tuning_defaults = get_rag_tuning_defaults
    stub.get_rag_tuning_schema = get_rag_tuning_schema
    stub.has_gemini_api_key = has_gemini_api_key
    stub.configure_gemini_api_key = configure_gemini_api_key
    stub.get_supported_generation_models = get_supported_generation_models
    stub.get_persona_prompt_defaults = get_persona_prompt_defaults
    stub.get_gemini_client = get_gemini_client
    stub.configure_anthropic_api_key = configure_anthropic_api_key
    stub.has_anthropic_api_key = has_anthropic_api_key
    stub.get_anthropic_client = get_anthropic_client
    stub.get_supported_claude_models = get_supported_claude_models
    stub.get_informativo_items = get_informativo_items
    stub.summarize_informativo_items = summarize_informativo_items

    sys.modules["rag.query"] = stub
    sys.modules.pop("backend.main", None)
    backend_main = importlib.import_module("backend.main")
    return backend_main


def test_health_contract():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert "version" in payload
    assert "build" in payload
    assert "has_gemini_api_key" in payload
    assert payload["defaults"]["reranker_backend"] == "local"
    assert payload["defaults"]["generation_model"] == "stub-generation"
    assert payload["defaults"]["persona_prompt_defaults"]["parecer"] == "Prompt padrao de parecer."
    assert "rag_tuning" in payload["defaults"]


def test_query_contract_serialization():
    backend_main = _load_backend_with_stub()

    def fake_run_query(**_kwargs):
        docs = [
            {
                "doc_id": "stf-mon-123",
                "tipo": "monocratica",
                "tribunal": "STF",
                "processo": "RE 123",
                "relator": "Min. X",
                "orgao_julgador": "Decisao Monocratica",
                "data_julgamento": "2026-01-10",
                "_authority_level": "A",
                "_authority_label": "Vinculante forte",
                "_final_score": 0.9876,
                "texto_busca": "Trecho de busca",
                "texto_integral": "Trecho integral longo",
                "url": "https://example.test/doc",
            }
        ]
        return "answer ok", docs, {"total_docs": 1}

    backend_main.run_query = fake_run_query
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/query",
        json={
            "query": "Como fica o tema?",
            "prefer_recent": True,
            "reranker_backend": "local",
            "trace": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "answer ok"
    assert payload["meta"]["total_docs"] == 1
    assert len(payload["docs"]) == 1
    assert payload["docs"][0]["doc_id"] == "stf-mon-123"
    assert payload["docs"][0]["tipo_label"] == "monocratica"


def test_serialize_doc_falls_back_to_inline_for_stf_downloadpeca_links():
    backend_main = _load_backend_with_stub()

    payload = backend_main._serialize_doc(
        1,
        {
            "doc_id": "stf-mon-despacho1638302",
            "tipo": "monocratica",
            "tribunal": "STF",
            "processo": "ARE 1544059",
            "relator": "PRESIDENTE",
            "orgao_julgador": "Decisao Monocratica",
            "data_julgamento": "2025-04-03",
            "texto_busca": "Trecho indexado",
            "texto_integral": "Inteiro teor local disponivel",
            "url": "https://portal.stf.jus.br/processos/downloadPeca.asp?id=15375578399&ext=.pdf",
        },
    )

    assert payload["inteiro_teor_url"] == ""
    assert payload["texto_integral_full"] == "Inteiro teor local disponivel"


def test_query_contract_forwards_sources_and_user_priority():
    backend_main = _load_backend_with_stub()
    captured: dict[str, object] = {}

    def fake_run_query(**kwargs):
        captured.update(kwargs)
        return "answer ok", [], {"total_docs": 0}

    backend_main.run_query = fake_run_query
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/query",
        json={
            "query": "Como fica o tema?",
            "prefer_recent": True,
            "reranker_backend": "local",
            "sources": ["ratio", "user:banco-1"],
            "prefer_user_sources": True,
        },
    )
    assert response.status_code == 200
    assert captured.get("sources") == ["ratio", "user:banco-1"]
    assert captured.get("prefer_user_sources") is True


def test_query_contract_forwards_persona_prompt():
    backend_main = _load_backend_with_stub()
    captured: dict[str, object] = {}

    def fake_run_query(**kwargs):
        captured.update(kwargs)
        return "answer ok", [], {"total_docs": 0}

    backend_main.run_query = fake_run_query
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/query",
        json={
            "query": "Como fica o tema?",
            "prefer_recent": True,
            "reranker_backend": "local",
            "persona": "parecer",
            "persona_prompt": "Responder em 2 paragrafos.",
        },
    )
    assert response.status_code == 200
    assert captured.get("persona") == "parecer"
    assert captured.get("persona_prompt") == "Responder em 2 paragrafos."


def test_query_contract_accepts_tipos_with_underscore():
    backend_main = _load_backend_with_stub()
    captured: dict[str, object] = {}

    def fake_run_query(**kwargs):
        captured.update(kwargs)
        return "answer ok", [], {"total_docs": 0}

    backend_main.run_query = fake_run_query
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/query",
        json={
            "query": "Como fica o tema?",
            "tribunais": ["STF", "STJ"],
            "tipos": ["sumula_vinculante", "tema_repetitivo_stj", "acordao"],
            "prefer_recent": True,
            "reranker_backend": "local",
            "persona": "visao_geral",
        },
    )
    assert response.status_code == 200
    assert captured.get("tipos") == ["sumula_vinculante", "tema_repetitivo_stj", "acordao"]


def test_query_contract_accepts_all_personas():
    backend_main = _load_backend_with_stub()
    captured_personas: list[str] = []

    def fake_run_query(**kwargs):
        captured_personas.append(str(kwargs.get("persona") or ""))
        return "answer ok", [], {"total_docs": 0}

    backend_main.run_query = fake_run_query
    client = TestClient(backend_main.app)

    for persona in ("visao_geral", "parecer", "estudos", "peticao"):
        response = client.post(
            "/api/query",
            json={
                "query": "Teste de persona",
                "tipos": ["sumula_vinculante"],
                "prefer_recent": True,
                "reranker_backend": "local",
                "persona": persona,
            },
        )
        assert response.status_code == 200

    assert captured_personas == ["visao_geral", "parecer", "estudos", "peticao"]


def test_explain_contract():
    backend_main = _load_backend_with_stub()
    backend_main.explain_answer = lambda **_kwargs: "explicacao curta"
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/explain",
        json={
            "query": "Pergunta",
            "answer": "Resposta",
            "docs": [],
        },
    )
    assert response.status_code == 200
    assert response.json()["explanation"] == "explicacao curta"


def test_tts_contract():
    backend_main = _load_backend_with_stub()
    backend_main._synthesize_tts = lambda *_args, **_kwargs: b"fake-mp3-data"
    client = TestClient(backend_main.app)

    response = client.post("/api/tts", json={"text": "Teste de audio"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mime_type"] == "audio/mpeg"
    assert payload["audio_base64"]
    assert payload["voice"]
    assert payload["trace_id"]


def test_meu_acervo_sources_contract():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    response = client.get("/api/meu-acervo/sources")
    assert response.status_code == 200
    payload = response.json()
    assert "sources" in payload
    source_map = {
        str(item.get("id")): item
        for item in payload.get("sources", [])
        if isinstance(item, dict)
    }
    assert "ratio" in source_map
    assert "tjsp" in source_map
    assert source_map["ratio"]["label"] == "Base Ratio (STF/STJ)"
    assert source_map["tjsp"]["label"] == "TJSP Revistas"
    assert "default_selected" in payload


def test_meu_acervo_index_requires_manual_confirmation():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    fake_pdf = io.BytesIO(b"%PDF-1.4\n%fake\n1 0 obj\n<<>>\nendobj\n%%EOF")
    response = client.post(
        "/api/meu-acervo/index",
        data={
            "confirm_index": "false",
            "source_name": "Banco 1",
            "ocr_missing_only": "true",
        },
        files={"files": ("exemplo.pdf", fake_pdf, "application/pdf")},
    )
    assert response.status_code == 400
    detail = response.json().get("detail", {})
    assert str(detail.get("code")) == "confirmation_required"


def test_meu_acervo_index_rejects_file_over_size_limit():
    backend_main = _load_backend_with_stub()
    backend_main.USER_ACERVO_MAX_FILE_SIZE_BYTES = 8
    backend_main.USER_ACERVO_MAX_REQUEST_SIZE_BYTES = 1024
    client = TestClient(backend_main.app)

    fake_pdf = io.BytesIO(b"%PDF-1.4\nabcdefghi\n%%EOF")
    response = client.post(
        "/api/meu-acervo/index",
        data={
            "confirm_index": "true",
            "source_name": "Banco 1",
            "ocr_missing_only": "true",
        },
        files={"files": ("grande.pdf", fake_pdf, "application/pdf")},
    )
    assert response.status_code == 400
    detail = response.json().get("detail", {})
    assert str(detail.get("code")) == "file_too_large"


def test_meu_acervo_index_rejects_request_over_total_size_limit():
    backend_main = _load_backend_with_stub()
    backend_main.USER_ACERVO_MAX_FILE_SIZE_BYTES = 1024
    backend_main.USER_ACERVO_MAX_REQUEST_SIZE_BYTES = 12
    client = TestClient(backend_main.app)

    file_a = io.BytesIO(b"%PDF-1.4\nabcde\n%%EOF")
    file_b = io.BytesIO(b"%PDF-1.4\nabcde\n%%EOF")
    response = client.post(
        "/api/meu-acervo/index",
        data={
            "confirm_index": "true",
            "source_name": "Banco 1",
            "ocr_missing_only": "true",
        },
        files=[
            ("files", ("a.pdf", file_a, "application/pdf")),
            ("files", ("b.pdf", file_b, "application/pdf")),
        ],
    )
    assert response.status_code == 400
    detail = response.json().get("detail", {})
    assert str(detail.get("code")) == "request_too_large"


def test_meu_acervo_index_rejects_pdf_without_magic_bytes_signature():
    backend_main = _load_backend_with_stub()
    backend_main.USER_ACERVO_MAX_FILE_SIZE_BYTES = 1024
    backend_main.USER_ACERVO_MAX_REQUEST_SIZE_BYTES = 1024
    client = TestClient(backend_main.app)

    fake_non_pdf = io.BytesIO(b"NOT-A-REAL-PDF")
    response = client.post(
        "/api/meu-acervo/index",
        data={
            "confirm_index": "true",
            "source_name": "Banco 1",
            "ocr_missing_only": "true",
        },
        files={"files": ("falso.pdf", fake_non_pdf, "application/pdf")},
    )
    assert response.status_code == 422
    detail = response.json().get("detail", {})
    assert str(detail.get("code")) == "invalid_pdf_signature"


def test_meu_acervo_index_starts_async_job_and_exposes_job_status():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    backend_main._start_user_acervo_index_job = lambda **_kwargs: "job-test-001"
    backend_main._get_user_acervo_job_payload = lambda _job_id: {
        "job_id": "job-test-001",
        "status": "running",
        "stage": "extract",
        "progress": {"total_files": 1, "processed_files": 0},
        "eta_seconds": 42,
    }

    fake_pdf = io.BytesIO(b"%PDF-1.4\n%fake\n1 0 obj\n<<>>\nendobj\n%%EOF")
    response = client.post(
        "/api/meu-acervo/index",
        data={
            "confirm_index": "true",
            "source_name": "Banco 1",
            "ocr_missing_only": "true",
        },
        files={"files": ("exemplo.pdf", fake_pdf, "application/pdf")},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload.get("status") == "accepted"
    assert payload.get("job_id") == "job-test-001"

    status_response = client.get("/api/meu-acervo/index/jobs/job-test-001")
    assert status_response.status_code == 200
    job = status_response.json()
    assert job.get("job_id") == "job-test-001"
    assert job.get("status") == "running"
    assert isinstance(job.get("progress"), dict)


def test_meu_acervo_index_job_status_returns_404_for_unknown_job():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    backend_main._get_user_acervo_job_payload = lambda _job_id: None
    response = client.get("/api/meu-acervo/index/jobs/job-does-not-exist")
    assert response.status_code == 404


def test_user_acervo_clean_has_hard_timeout_fallback():
    backend_main = _load_backend_with_stub()
    backend_main._run_with_hard_timeout = lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("timeout hard"))

    started = time.perf_counter()
    out = backend_main._clean_user_chunk_with_flash("pagina 3\nConteudo juridico util")
    elapsed = time.perf_counter() - started

    assert "Conteudo juridico util" in out
    assert elapsed < 2.0


def test_meu_acervo_source_delete_and_restore_contract():
    backend_main = _load_backend_with_stub()
    backend_main._ensure_user_source("Banco 1")
    client = TestClient(backend_main.app)

    delete_resp = client.post("/api/meu-acervo/source/delete", json={"source_id": "user:banco-1"})
    assert delete_resp.status_code == 200
    assert delete_resp.json().get("status") == "ok"

    restore_resp = client.post("/api/meu-acervo/source/restore", json={"source_id": "user:banco-1"})
    assert restore_resp.status_code == 200
    assert restore_resp.json().get("status") == "ok"


def test_tts_contract_accepts_dynamic_mime_type():
    backend_main = _load_backend_with_stub()
    backend_main._synthesize_tts = lambda *_args, **_kwargs: (b"fake-wav-data", "audio/wav")
    client = TestClient(backend_main.app)

    response = client.post("/api/tts", json={"text": "Teste de audio"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mime_type"] == "audio/wav"
    assert payload["audio_base64"]


def test_tts_extract_converts_pcm_l16_into_wav():
    backend_main = _load_backend_with_stub()

    pcm_payload = b"\x00\x01\x00\x02\x00\x03\x00\x04"
    inline = types.SimpleNamespace(data=pcm_payload, mime_type="audio/l16;codec=pcm;rate=24000")
    part = types.SimpleNamespace(inline_data=inline)
    response = types.SimpleNamespace(parts=[part])

    audio, mime = backend_main._extract_inline_audio_from_response(response)
    assert mime == "audio/wav"
    assert audio.startswith(b"RIFF")


def test_tts_defaults_to_gemini_native_provider():
    backend_main = _load_backend_with_stub()
    assert backend_main.TTS_PROVIDER == "gemini_native"
    assert backend_main.TTS_MODEL == "gemini-2.5-pro-preview-tts"
    assert backend_main.TTS_MAX_CHARS == 5000


def test_legacy_tts_module_targets_google_cloud_tts_endpoint():
    legacy_source = Path("backend/tts_legacy_google.py").read_text(encoding="utf-8")
    assert "texttospeech.googleapis.com/v1/text:synthesize" in legacy_source


def test_legacy_tts_module_uses_api_key_header_instead_of_query_param():
    legacy_source = Path("backend/tts_legacy_google.py").read_text(encoding="utf-8")
    assert '"X-Goog-Api-Key": config.api_key' in legacy_source
    assert "?key=" not in legacy_source


def test_tts_dispatch_routes_to_gemini_provider_by_default():
    backend_main = _load_backend_with_stub()
    backend_main._synthesize_google_tts = lambda *_args, **_kwargs: (b"gemini-audio", "audio/wav")
    backend_main._synthesize_legacy_google_tts = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("should not call legacy path")
    )

    audio, mime = backend_main._synthesize_tts("teste", trace_id="trace001")
    assert audio == b"gemini-audio"
    assert mime == "audio/wav"


def test_tts_stream_dispatch_routes_to_gemini_provider_by_default():
    backend_main = _load_backend_with_stub()
    backend_main._stream_google_tts_chunks = lambda *_args, **_kwargs: iter(
        [(b"gemini-chunk", "audio/wav", 1, 1)]
    )
    backend_main._stream_legacy_tts_chunks = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("should not call legacy stream path")
    )

    chunks = list(backend_main._stream_tts_chunks("teste", trace_id="trace002"))
    assert len(chunks) == 1
    assert chunks[0][0] == b"gemini-chunk"
    assert chunks[0][1] == "audio/wav"


def test_tts_sync_falls_back_to_legacy_when_gemini_fails():
    backend_main = _load_backend_with_stub()
    backend_main.TTS_PROVIDER = "gemini_native"
    backend_main.TTS_PROVIDER_FALLBACK = True
    backend_main._legacy_tts_api_key = lambda: "legacy-key"
    events: list[tuple[str, str, dict]] = []
    backend_main._log_tts_event = lambda event, trace_id, **kwargs: events.append((event, trace_id, kwargs))
    backend_main._synthesize_google_tts = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("Falha no TTS Gemini: indisponibilidade upstream apos tentativas.")
    )
    backend_main._synthesize_legacy_google_tts = lambda *_args, **_kwargs: (b"legacy-audio", "audio/wav")

    audio, mime = backend_main._synthesize_tts("texto", trace_id="trace-fallback-sync")
    assert audio == b"legacy-audio"
    assert mime == "audio/wav"
    assert any(item[0] == "tts_provider_fallback" for item in events)


def test_tts_stream_falls_back_to_legacy_when_gemini_fails_before_first_chunk():
    backend_main = _load_backend_with_stub()
    backend_main.TTS_PROVIDER = "gemini_native"
    backend_main.TTS_PROVIDER_FALLBACK = True
    backend_main._legacy_tts_api_key = lambda: "legacy-key"
    backend_main._stream_google_tts_chunks = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("Falha no TTS Gemini: indisponibilidade upstream apos tentativas.")
    )
    backend_main._stream_legacy_tts_chunks = lambda *_args, **_kwargs: iter(
        [(b"legacy-chunk", "audio/wav", 1, 1)]
    )

    chunks = list(backend_main._stream_tts_chunks("texto", trace_id="trace-fallback-stream"))
    assert len(chunks) == 1
    assert chunks[0][0] == b"legacy-chunk"


def test_tts_stream_falls_back_to_legacy_after_partial_gemini_output():
    backend_main = _load_backend_with_stub()
    backend_main.TTS_PROVIDER = "gemini_native"
    backend_main.TTS_PROVIDER_FALLBACK = True
    backend_main._legacy_tts_api_key = lambda: "legacy-key"

    def _partial_fail_stream(*_args, **_kwargs):
        yield (b"gemini-first", "audio/wav", 1, 2)
        raise backend_main._TTSPartialStreamError(
            "Falha no TTS Gemini apos chunks parciais. Ultimo erro: timeout",
            remaining_text="restante do texto",
            emitted_chunks=1,
            total_chunks=2,
        )

    backend_main._stream_google_tts_chunks = _partial_fail_stream
    captured: dict[str, str] = {}

    def _legacy_stream(text: str, *_args, **_kwargs):
        captured["text"] = text
        yield (b"legacy-chunk", "audio/wav", 1, 1)

    backend_main._stream_legacy_tts_chunks = _legacy_stream

    chunks = list(backend_main._stream_tts_chunks("texto", trace_id="trace-partial"))
    assert len(chunks) == 2
    assert chunks[0][0] == b"gemini-first"
    assert chunks[1][0] == b"legacy-chunk"
    assert chunks[1][2] == 2
    assert chunks[1][3] == 2
    assert captured.get("text") == "restante do texto"


def test_tts_sync_does_not_fallback_when_disabled():
    backend_main = _load_backend_with_stub()
    backend_main.TTS_PROVIDER = "gemini_native"
    backend_main.TTS_PROVIDER_FALLBACK = False
    backend_main._legacy_tts_api_key = lambda: "legacy-key"
    backend_main._synthesize_google_tts = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("Falha no TTS Gemini: indisponibilidade upstream apos tentativas.")
    )
    backend_main._synthesize_legacy_google_tts = lambda *_args, **_kwargs: (b"legacy-audio", "audio/wav")

    with pytest.raises(RuntimeError):
        backend_main._synthesize_tts("texto", trace_id="trace-no-fallback")


def test_tts_normalize_removes_doc_citation_markers():
    backend_main = _load_backend_with_stub()

    raw = (
        "A tese do precedente [DOC. 1, DOC. 2] foi reafirmada [DOCUMENTO 3]. "
        "Sem leitura de marcadores [doc. 4]."
    )
    normalized = backend_main._normalize_for_tts(raw)

    assert re.search(r"\[[^\]]*(?:DOC(?:UMENTO)?\.?|DOCUMENTO)[^\]]*\]", normalized, flags=re.IGNORECASE) is None


def test_tts_normalize_restores_portuguese_accents():
    backend_main = _load_backend_with_stub()

    normalized = backend_main._normalize_for_tts(
        "tema de repercussao geral e decisao do judiciario na constituicao"
    ).lower()

    assert "repercussão geral" in normalized
    assert "decisão" in normalized
    assert "judiciário" in normalized
    assert "constituição" in normalized


def test_tts_chunks_keep_ssml_under_google_5000_byte_limit():
    backend_main = _load_backend_with_stub()

    raw = ("á" * 260 + ". ") * 80
    chunks = backend_main._split_tts_chunks(raw)

    assert len(chunks) > 1
    for chunk in chunks:
        ssml = backend_main._build_ssml(chunk)
        assert len(ssml.encode("utf-8")) <= backend_main.TTS_MAX_CHARS


def test_rag_config_contract():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    response = client.get("/api/rag-config")
    assert response.status_code == 200
    payload = response.json()
    assert "version" in payload
    assert "defaults" in payload
    assert "schema" in payload


def test_gemini_status_contract():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    response = client.get("/api/gemini/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["has_api_key"] is False
    assert "supported_models" in payload


def test_tts_config_status_contract():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    response = client.get("/api/tts/config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["provider"] in {"gemini_native", "legacy_google"}
    assert "env_path" not in payload
    options = payload.get("options", [])
    option_ids = {str(item.get("id")) for item in options if isinstance(item, dict)}
    assert "gemini_native" in option_ids
    assert "legacy_google" in option_ids


def test_tts_config_update_switches_provider_for_next_generation():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    backend_main._synthesize_google_tts = lambda *_args, **_kwargs: (b"gemini-audio", "audio/wav")
    backend_main._synthesize_legacy_google_tts = lambda *_args, **_kwargs: (b"legacy-audio", "audio/wav")

    response = client.post(
        "/api/tts/config",
        json={"provider": "legacy_google", "persist_env": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "legacy_google"
    assert "env_path" not in payload
    assert backend_main.TTS_PROVIDER == "legacy_google"

    audio, mime = backend_main._synthesize_tts("texto", trace_id="trace-tts-config-switch")
    assert audio == b"legacy-audio"
    assert mime == "audio/wav"


def test_tts_config_rejects_invalid_provider():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/tts/config",
        json={"provider": "unsupported_engine", "persist_env": False},
    )
    assert response.status_code == 400
    detail = response.json().get("detail", {})
    assert str(detail.get("code")) == "invalid_tts_provider"

def test_gemini_setup_contract():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/gemini/config",
        json={
            "api_key": "test-key",
            "persist_env": False,
            "validate": True,
            "test_model": "gemini-2.5-flash",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["saved"] is True
    assert payload["validated"] is True
    assert payload["has_api_key"] is True
    assert "env_path" not in payload


def test_gemini_setup_soft_validation_failure_still_saves_key():
    backend_main = _load_backend_with_stub()
    calls: list[bool] = []

    def flaky_configure(
        api_key: str,
        *,
        validate: bool = False,
        test_model: str = "",
        validation_timeout_ms: int = 12000,
    ):
        calls.append(bool(validate))
        if validate:
            raise RuntimeError("timeout while contacting Gemini API")
        backend_main.sys.modules["rag.query"]._gemini_has_key = True
        return {"validated": False, "model": test_model or "gemini-2.5-flash"}

    backend_main.configure_gemini_api_key = flaky_configure
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/gemini/config",
        json={
            "api_key": "test-key",
            "persist_env": False,
            "validate": True,
            "test_model": "gemini-3-flash-preview",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["saved"] is True
    assert payload["validated"] is False
    assert payload["has_api_key"] is True
    assert "validation_warning" in payload
    assert "timeout" in payload["validation_warning"].lower()
    assert calls == [True, False]


def test_gemini_setup_invalid_key_still_fails():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/gemini/config",
        json={
            "api_key": "invalid-key",
            "persist_env": False,
            "validate": True,
            "test_model": "gemini-2.5-flash",
        },
    )
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_api_key"


def test_gemini_key_validation_uses_single_attempt_retry_policy():
    source = Path("rag/query.py").read_text(encoding="utf-8")
    assert "HttpRetryOptions(attempts=1)" in source


def test_tts_generation_uses_http_timeout_and_limited_retries():
    source = Path("backend/main.py").read_text(encoding="utf-8")
    assert "GEMINI_TTS_REQUEST_TIMEOUT_MS" in source
    assert "HttpRetryOptions(attempts=retry_attempts)" in source
    assert "TTS_MODEL_MAX_ATTEMPTS" in source


def test_tts_500_internal_is_classified_as_upstream_unavailable():
    backend_main = _load_backend_with_stub()

    exc = RuntimeError(
        "Falha no TTS Gemini (gemini-2.5-pro-preview-tts): 500 INTERNAL. "
        "{'error': {'code': 500, 'message': 'An internal error has occurred. Please retry', 'status': 'INTERNAL'}}"
    )
    status_code, detail = backend_main._classify_runtime_error(exc)

    assert status_code == 503
    assert detail["code"] == "upstream_unavailable"
    assert "TTS" in detail["hint"] or "Gemini" in detail["hint"]


def test_tts_error_response_includes_trace_id_for_support():
    backend_main = _load_backend_with_stub()

    def fail_tts(*_args, **_kwargs):
        raise RuntimeError(
            "Falha no TTS Gemini (gemini-2.5-pro-preview-tts): 500 INTERNAL. "
            "{'error': {'code': 500, 'message': 'An internal error has occurred. Please retry', 'status': 'INTERNAL'}}"
        )

    backend_main._synthesize_tts = fail_tts
    client = TestClient(backend_main.app)

    response = client.post("/api/tts", json={"text": "Teste de audio com falha"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "upstream_unavailable"
    assert "trace_id" in detail
    assert len(str(detail["trace_id"])) >= 8


def test_tts_no_supported_model_is_classified_as_model_unavailable():
    backend_main = _load_backend_with_stub()

    exc = RuntimeError(
        "Falha no TTS Gemini: nenhum modelo de voz suporta audio para esta chave/API. "
        "Modelos testados: gemini-2.5-pro-preview-tts."
    )
    status_code, detail = backend_main._classify_runtime_error(exc)

    assert status_code == 400
    assert detail["code"] == "model_unavailable"


def test_tts_upstream_exhaustion_is_classified_as_upstream_unavailable():
    backend_main = _load_backend_with_stub()

    exc = RuntimeError(
        "Falha no TTS Gemini: indisponibilidade upstream apos tentativas. "
        "Ultimo erro: The read operation timed out"
    )
    status_code, detail = backend_main._classify_runtime_error(exc)

    assert status_code == 503
    assert detail["code"] == "upstream_unavailable"


def test_tts_fallback_default_no_longer_forces_nonexistent_flash_tts_model():
    source = Path("backend/main.py").read_text(encoding="utf-8")
    assert 'or "gemini-2.5-flash-tts"' not in source


def test_tts_stream_uses_controlled_prefetch_concurrency():
    backend_main = _load_backend_with_stub()
    backend_main.has_gemini_api_key = lambda: True
    backend_main.TTS_MODEL_MAX_ATTEMPTS = 1
    backend_main.TTS_REQUEST_RETRY_ATTEMPTS = 1
    backend_main.TTS_PREFETCH_CONCURRENCY = 2
    backend_main.TTS_CACHE_ENABLED = False
    backend_main._split_tts_chunks = (
        lambda _text, max_ssml_bytes=5000: ["bloco 1", "bloco 2", "bloco 3", "bloco 4"]
    )

    active = {"current": 0, "max": 0}
    lock = threading.Lock()

    def fake_generate_content(**kwargs):
        with lock:
            active["current"] += 1
            active["max"] = max(active["max"], active["current"])
        time.sleep(0.06)
        with lock:
            active["current"] -= 1
        payload = kwargs.get("contents", "").encode("utf-8")
        inline = types.SimpleNamespace(data=payload, mime_type="audio/wav")
        return types.SimpleNamespace(parts=[types.SimpleNamespace(inline_data=inline)])

    fake_client = types.SimpleNamespace(
        models=types.SimpleNamespace(generate_content=fake_generate_content)
    )
    backend_main.get_gemini_client = lambda: fake_client

    chunks = list(backend_main._stream_google_tts_chunks("texto longo para concorrencia", trace_id="prefetch01"))
    assert len(chunks) == 4
    assert [idx for _audio, _mime, idx, _total in chunks] == [1, 2, 3, 4]
    assert active["max"] >= 2
    assert active["max"] <= backend_main.TTS_PREFETCH_CONCURRENCY


def test_tts_stream_respects_stream_max_chars_limit():
    backend_main = _load_backend_with_stub()
    backend_main.has_gemini_api_key = lambda: True
    backend_main.TTS_MODEL_MAX_ATTEMPTS = 1
    backend_main.TTS_REQUEST_RETRY_ATTEMPTS = 1
    backend_main.TTS_PREFETCH_CONCURRENCY = 1
    backend_main.TTS_CACHE_ENABLED = False
    backend_main.TTS_STREAM_MAX_CHARS = 777

    captured: dict[str, int] = {}

    def fake_split(text: str, max_ssml_bytes: int = 5000):
        captured["max_ssml_bytes"] = int(max_ssml_bytes)
        return ["bloco unico"]

    backend_main._split_tts_chunks = fake_split

    def fake_generate_content(**kwargs):
        payload = kwargs.get("contents", "").encode("utf-8")
        inline = types.SimpleNamespace(data=payload, mime_type="audio/wav")
        return types.SimpleNamespace(parts=[types.SimpleNamespace(inline_data=inline)])

    fake_client = types.SimpleNamespace(
        models=types.SimpleNamespace(generate_content=fake_generate_content)
    )
    backend_main.get_gemini_client = lambda: fake_client

    chunks = list(backend_main._stream_google_tts_chunks("texto stream", trace_id="stream-max"))
    assert len(chunks) == 1
    assert captured.get("max_ssml_bytes") == 777


def test_tts_chunk_cache_uses_hash_and_disk_storage(tmp_path):
    backend_main = _load_backend_with_stub()
    backend_main.has_gemini_api_key = lambda: True
    backend_main.TTS_MODEL_MAX_ATTEMPTS = 1
    backend_main.TTS_REQUEST_RETRY_ATTEMPTS = 1
    backend_main.TTS_PREFETCH_CONCURRENCY = 1
    backend_main.TTS_CACHE_ENABLED = True
    backend_main._split_tts_chunks = (
        lambda _text, max_ssml_bytes=5000: ["bloco repetido", "bloco repetido"]
    )

    call_count = {"value": 0}

    def fake_generate_content(**kwargs):
        call_count["value"] += 1
        payload = kwargs.get("contents", "").encode("utf-8")
        inline = types.SimpleNamespace(data=payload, mime_type="audio/wav")
        return types.SimpleNamespace(parts=[types.SimpleNamespace(inline_data=inline)])

    fake_client = types.SimpleNamespace(
        models=types.SimpleNamespace(generate_content=fake_generate_content)
    )
    backend_main.get_gemini_client = lambda: fake_client

    cache_root = tmp_path / "tts_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    backend_main._tts_cache_dir = lambda: cache_root

    first = list(backend_main._stream_google_tts_chunks("texto repetido", trace_id="cache01"))
    second = list(backend_main._stream_google_tts_chunks("texto repetido", trace_id="cache02"))

    assert len(first) == 2
    assert len(second) == 2
    assert call_count["value"] == 1
    assert any(cache_root.glob("*.bin"))
    assert any(cache_root.glob("*.json"))


def test_query_error_is_structured_for_missing_api_key():
    backend_main = _load_backend_with_stub()

    def fake_run_query(**_kwargs):
        raise RuntimeError("GEMINI_API_KEY ausente. Configure a chave Gemini.")

    backend_main.run_query = fake_run_query
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/query",
        json={
            "query": "teste",
            "prefer_recent": True,
            "reranker_backend": "local",
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "missing_api_key"
    assert detail["message"] == "Chave de API ausente."
    assert "Configure a chave Gemini" in detail["hint"]


def test_frontend_source_links_are_protocol_sanitized():
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "function sanitizeUrl(rawUrl)" in source
    assert 'protocol === "http:" || protocol === "https:"' in source


def test_frontend_removed_instruction_field_and_added_persona_settings():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    assert 'id="userInstructionInput"' not in html
    assert "userInstructionInput" not in js
    assert 'id="personaConfigSelect"' in html
    assert 'id="personaPromptInput"' in html
    assert 'id="savePersonaConfigBtn"' in html
    assert 'id="personaDefaultPromptPreview"' in html
    assert "PERSONA_CONFIG_STORAGE_KEY" in js
    assert "personaPromptDefaults" in js


def test_query_stream_contract_emits_stage_and_result():
    backend_main = _load_backend_with_stub()

    def fake_run_query(**kwargs):
        stage_callback = kwargs.get("stage_callback")
        if callable(stage_callback):
            stage_callback("embedding_start", {"timings": {}})
            stage_callback("embedding_done", {"timings": {"embedding": 0.01}})
            stage_callback("retrieval_start", {"timings": {"embedding": 0.01}})
            stage_callback("retrieval_done", {"timings": {"embedding": 0.01, "retrieval": 0.02}, "candidates": 3})
            stage_callback("done", {"timings": {"total": 0.05}, "candidates": 3, "returned_docs": 1})
        docs = [
            {
                "doc_id": "stf-stream-1",
                "tipo": "acordao",
                "tribunal": "STF",
                "processo": "RE 999",
                "data_julgamento": "2025-01-10",
                "relator": "Min. Stream",
                "orgao_julgador": "Plenario",
                "_authority_level": "B",
                "_authority_label": "Precedente qualificado",
                "_final_score": 0.91,
                "texto_busca": "Trecho stream",
                "texto_integral": "Trecho integral stream",
            }
        ]
        return "answer stream", docs, {"total_seconds": 0.05, "candidates": 3, "returned_docs": 1}

    backend_main.run_query = fake_run_query
    client = TestClient(backend_main.app)

    packets = []
    with client.stream(
        "POST",
        "/api/query/stream",
        json={
            "query": "Teste stream",
            "prefer_recent": True,
            "reranker_backend": "local",
        },
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line:
                continue
            packets.append(json.loads(line))

    events = [p.get("event") for p in packets]
    assert "started" in events
    assert "stage" in events
    assert "result" in events

    stage_names = [p.get("stage") for p in packets if p.get("event") == "stage"]
    assert "embedding_start" in stage_names
    assert "retrieval_done" in stage_names
    assert "done" in stage_names

    result_packet = next(p for p in packets if p.get("event") == "result")
    assert result_packet["data"]["answer"] == "answer stream"
    assert result_packet["data"]["meta"]["returned_docs"] == 1
    assert len(result_packet["data"]["docs"]) == 1


def test_tts_stream_contract_emits_started_chunk_done():
    backend_main = _load_backend_with_stub()

    def fake_stream(_text: str, trace_id: str | None = None):
        yield (b"chunk-1", "audio/wav", 1, 2)
        yield (b"chunk-2", "audio/wav", 2, 2)

    backend_main._stream_tts_chunks = fake_stream
    client = TestClient(backend_main.app)

    packets = []
    with client.stream("POST", "/api/tts/stream", json={"text": "Teste stream TTS"}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line:
                continue
            packets.append(json.loads(line))

    events = [p.get("event") for p in packets]
    assert "started" in events
    assert "chunk" in events
    assert "done" in events

    chunk_packets = [p for p in packets if p.get("event") == "chunk"]
    assert len(chunk_packets) == 2
    assert chunk_packets[0]["audio_base64"]
    assert chunk_packets[0]["mime_type"] == "audio/wav"


def test_juris_update_last_contract():
    backend_main = _load_backend_with_stub()
    client = TestClient(backend_main.app)

    response = client.get("/api/juris-update/last")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["defaults"]["target_year"] >= 2026
    assert "include_stf" in payload["defaults"]
    assert "include_stj" in payload["defaults"]


def test_juris_update_last_exposes_cursor_state():
    backend_main = _load_backend_with_stub()
    backend_main._save_juris_update_manifest(
        {
            "version": 2,
            "last_result": {"message": "ok"},
            "cursor": {
                "target_year": 2026,
                "stf_since_date": "2026-03-04",
                "last_checked_at": "2026-03-04T20:10:00",
            },
        }
    )
    client = TestClient(backend_main.app)

    response = client.get("/api/juris-update/last")
    assert response.status_code == 200
    payload = response.json()
    assert payload["cursor"]["target_year"] == 2026
    assert payload["cursor"]["stf_since_date"] == "2026-03-04"
    assert payload["cursor"]["last_checked_at"] == "2026-03-04T20:10:00"


def test_juris_update_start_contract():
    backend_main = _load_backend_with_stub()
    backend_main._start_juris_update_job = lambda **_kwargs: "jobtest123"
    client = TestClient(backend_main.app)

    response = client.post(
        "/api/juris-update/start",
        json={
            "include_stf": True,
            "include_stj": True,
            "target_year": 2026,
            "visible_browser": True,
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["job_id"] == "jobtest123"
    assert payload["target_year"] == 2026
    assert payload["include_stf"] is True
    assert payload["include_stj"] is True

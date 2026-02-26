# Ratio - Pesquisa Jurisprudencial - Architecture

This document describes the current production path of Ratio (web-first stack).

## 1. Runtime topology

- Frontend: static app served from `frontend/`
- Backend: FastAPI app in `backend/main.py`
- Retrieval engine: `rag/query.py`
- Vector store: LanceDB (`lancedb_store/`, table `jurisprudencia`)
- Source data: SQLite files under `data/`

Request flow:
1. Browser sends query payload to `POST /api/query`
2. Backend calls `run_query(...)` in `rag/query.py`
3. Retrieval engine executes hybrid retrieval + reranking
4. Backend returns answer + serialized cited docs + meta

## 2. API surface

- `GET /health`
- `POST /api/query`
- `POST /api/explain`
- `POST /api/tts`

Notes:
- CORS is controlled by `API_CORS_ORIGINS` (default `*`).
- `/api/tts` uses Google TTS endpoint and requires API key.

## 3. Retrieval pipeline (`rag/query.py`)

High-level stages:
1. Query embedding
2. Hybrid candidate retrieval (dense + FTS)
3. Reranking (local default, Gemini optional)
4. Context assembly for answer generation
5. Post checks on answer quality/citations

Key tuning knobs are loaded from environment, including:
- `TOPK_HYBRID`, `TOPK_RERANK`
- semantic/lexical/recency weights
- reranker backend/model settings
- context clipping limits

## 4. Ingestion pipeline

Main paths:
- `rag/ingest.py` for standard source ingestion
- `analysis/ingest_monocraticas_pendentes.py` for resilient monocraticas backlog

Backlog ingestion characteristics:
- checkpoint resume
- dedupe by `doc_id`
- configurable embedding parallelism
- minute-based throttle by items/tokens

## 5. Data contract per indexed document

Core fields in LanceDB rows include:
- `vector`
- `doc_id`
- `tribunal`, `tipo`, `processo`, `relator`, `ramo_direito`
- `data_julgamento`, `orgao_julgador`
- `texto_busca` (retrieval-optimized text)
- `texto_integral` (long reference body)
- `url`, `metadata_extra`

## 6. Operational scripts (Windows)

- `iniciar_jurisai_web.bat`: start backend + frontend
- `desligar_jurisai_web.bat`: stop backend + frontend
- `ingestar_monocraticas.bat`: incremental append batches
- `ingestar_monocraticas_pendentes.bat`: backlog ingestion with throttle
- `monitor_monocraticas.bat`: console monitor loop

## 7. Non-goals in this doc

- Detailed model prompt text
- Legal interpretation policy
- Full ingestion strategy per tribunal source

Those are tracked in code and roadmap docs.




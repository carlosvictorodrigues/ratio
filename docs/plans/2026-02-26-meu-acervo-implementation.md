# Meu Acervo Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Adicionar "Meu Acervo" com indexacao de PDFs do usuario (confirmacao manual obrigatoria), OCR Gemini so em paginas sem texto, limpeza de ruido via Gemini Flash em todos os chunks, embeddings `gemini-embedding-001`, consulta combinada com base Ratio + bases do usuario, e exclusao logica com restauracao.

**Architecture:** O backend passa a manter uma tabela separada de LanceDB para o acervo do usuario e um manifesto local de fontes (ativas/deletadas). O motor de consulta passa a buscar em multiplas fontes selecionadas (ratio + user) e aplicar bonus configuravel para priorizar documentos do usuario. O frontend ganha um painel "Meu Acervo" para upload/indexacao, selecao de fontes e acoes de excluir/restaurar.

**Tech Stack:** FastAPI, LanceDB, PyArrow, PyMuPDF, Google GenAI SDK, frontend SPA (vanilla JS/CSS), pytest.

---

### Task 1: API contract tests (RED)

**Files:**
- Modify: `tests/test_api_contract.py`

**Step 1: Write failing tests**
- Adicionar testes para:
  - `GET /api/meu-acervo/sources` com fonte `ratio` e colecoes do usuario.
  - `POST /api/meu-acervo/index` exigindo confirmacao manual.
  - `POST /api/meu-acervo/source/delete` e `/restore`.
  - `/api/query` aceitando `sources` e `prefer_user_sources`.

**Step 2: Run tests to verify failure**
- Run: `py -m pytest -q tests/test_api_contract.py`
- Expected: FAIL em novos testes.

### Task 2: Frontend contract tests (RED)

**Files:**
- Modify: `tests/test_frontend_sidebar_saved.py`

**Step 1: Write failing tests**
- Validar existencia de:
  - Secao "Meu Acervo" em `frontend/index.html`.
  - Controles de upload/indexacao e status.
  - Referencias JS para `sources`, `prefer_user_sources` e acoes de restaurar.

**Step 2: Run tests to verify failure**
- Run: `py -m pytest -q tests/test_frontend_sidebar_saved.py`
- Expected: FAIL em novos testes.

### Task 3: Backend Meu Acervo (GREEN)

**Files:**
- Modify: `backend/main.py`
- Modify: `rag/query.py`

**Step 1: Implement source catalog + lifecycle**
- Adicionar manifesto local de fontes do usuario.
- Implementar endpoints:
  - `GET /api/meu-acervo/sources`
  - `POST /api/meu-acervo/source/delete`
  - `POST /api/meu-acervo/source/restore`

**Step 2: Implement PDF indexing flow**
- `POST /api/meu-acervo/index` com `confirm_index`.
- Extrair texto com PyMuPDF.
- OCR Gemini somente para paginas sem texto.
- Quebrar em chunks (aprox. 1400 chars).
- Limpar ruido em todos os chunks com Gemini Flash.
- Gerar embeddings `gemini-embedding-001`.
- Persistir na tabela LanceDB separada do acervo do usuario.

**Step 3: Integrate query sources**
- Estender `QueryRequest` e `run_query/search_lancedb` para `sources` e `prefer_user_sources`.
- Default: incluir `ratio` + fontes ativas do usuario.
- Adicionar bonus configuravel para priorizacao de docs do usuario.
- Incluir metadados de origem na serializacao de docs.

### Task 4: Frontend Meu Acervo (GREEN)

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`

**Step 1: Add panel controls**
- Criar secao "Meu Acervo" no settings:
  - upload de PDF,
  - nome da base do usuario,
  - opcao OCR em pagina sem texto,
  - acao de indexar com confirmacao manual,
  - lista de fontes com incluir/excluir/restaurar.

**Step 2: Wire API integration**
- Carregar fontes via `/api/meu-acervo/sources`.
- Enviar `sources` e `prefer_user_sources` no payload de consulta.
- Persistir selecao de fontes em sessao local.

### Task 5: Verification

**Files:**
- N/A

**Step 1: Static and unit validation**
- Run: `node --check frontend/app.js`
- Run: `py -m pytest -q tests/test_api_contract.py tests/test_frontend_sidebar_saved.py`

**Step 2: Full regression smoke**
- Run: `py -m pytest -q`

**Step 3: Packaging confidence (optional)**
- Validar que `dist/Ratio/_internal/frontend/app.js` reflete novas strings apos rebuild (se rebuild for executado nesta rodada).

# Clara Gate1 Conversational Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fazer a Clara analisar o caso, devolver perguntas-chave e manter o usuário no intake até que ele decida complementar ou prosseguir com a triagem.

**Architecture:** O backend do intake passará a retornar novos campos conversacionais e a UI de intake mostrará esses campos inline, sem redesenhar o fluxo inteiro. O `gate1` continuará existindo, mas só será avançado por ação explícita do usuário.

**Tech Stack:** FastAPI, Pydantic, Gemini intake layer, React via `frontend/Escritorio/escritorio.html`, pytest.

---

### Task 1: Expandir o estado do intake

**Files:**
- Modify: `backend/escritorio/models.py`
- Test: `tests/escritorio/test_intake_models.py`

**Step 1: Write the failing test**

Add assertions for:
- `resposta_conversacional_clara`
- `perguntas_pendentes`
- `triagem_suficiente`

**Step 2: Run test to verify it fails**

Run: `pytest tests/escritorio/test_intake_models.py -q`
Expected: FAIL because the new fields do not exist.

**Step 3: Write minimal implementation**

Add the new intake fields to `RatioEscritorioState`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/escritorio/test_intake_models.py -q`
Expected: PASS

### Task 2: Fazer a LLM de intake devolver perguntas e resposta conversacional

**Files:**
- Modify: `backend/escritorio/intake_llm.py`
- Test: `tests/escritorio/test_intake_llm.py`

**Step 1: Write the failing test**

Add tests that prove:
- the prompt requests `resposta_conversacional_clara`, `perguntas_pendentes` and `triagem_suficiente`
- `parse_intake_payload()` preserves these fields

**Step 2: Run test to verify it fails**

Run: `pytest tests/escritorio/test_intake_llm.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

Update:
- prompt
- payload parser
- coercion rules for string lists / booleans

**Step 4: Run test to verify it passes**

Run: `pytest tests/escritorio/test_intake_llm.py -q`
Expected: PASS

### Task 3: Ajustar o intake graph para não parecer autoavanço mudo

**Files:**
- Modify: `backend/escritorio/graph/intake_graph.py`
- Test: `tests/escritorio/test_intake_graph.py`

**Step 1: Write the failing test**

Add tests that prove:
- the intake node returns conversation text and pending questions
- `gate1` still depends on explicit user approval

**Step 2: Run test to verify it fails**

Run: `pytest tests/escritorio/test_intake_graph.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

Pass through:
- `resposta_conversacional_clara`
- `perguntas_pendentes`
- `triagem_suficiente`

Do not auto-approve gate1.

**Step 4: Run test to verify it passes**

Run: `pytest tests/escritorio/test_intake_graph.py -q`
Expected: PASS

### Task 4: Ajustar o frontend do intake

**Files:**
- Modify: `frontend/Escritorio/escritorio.html`
- Test: `tests/escritorio/test_frontend_escritorio_real_runtime.py`

**Step 1: Write the failing test**

Add tests that prove:
- Clara renders a conversational answer block
- pending questions are shown inline
- `Prosseguir assim mesmo` is visible
- `Responder perguntas da Clara` is visible

**Step 2: Run test to verify it fails**

Run: `pytest tests/escritorio/test_frontend_escritorio_real_runtime.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**

Update the intake panel to show:
- answer from Clara
- pending questions
- buttons for reanalyze / respond / proceed

Keep the existing chat and dossiê.

**Step 4: Run test to verify it passes**

Run: `pytest tests/escritorio/test_frontend_escritorio_real_runtime.py -q`
Expected: PASS

### Task 5: Run integrated verification

**Files:**
- Modify if needed: `tests/escritorio/test_pipeline_api.py`

**Step 1: Run the focused suite**

Run:
`pytest tests/escritorio/test_intake_models.py tests/escritorio/test_intake_llm.py tests/escritorio/test_intake_graph.py tests/escritorio/test_frontend_escritorio_real_runtime.py tests/escritorio/test_pipeline_api.py -q`

Expected: PASS

**Step 2: Run the broader Escritório suite**

Run:
`pytest tests/escritorio/test_ratio_tools.py tests/escritorio/test_drafting_graph.py tests/escritorio/test_drafting_legislation.py tests/escritorio/test_orchestrator.py tests/escritorio/test_redaction.py tests/escritorio/test_formatter.py tests/escritorio/test_verifier.py tests/escritorio/test_contraparte.py tests/escritorio/test_frontend_escritorio_real_runtime.py tests/escritorio/test_pipeline_api.py tests/escritorio/test_e2e_pipeline_flow.py tests/escritorio/test_adversarial_graph.py tests/test_rag_generation_fallback.py tests/test_packaging_support.py -q`

Expected: PASS

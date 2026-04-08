# Review Loop And Stage Restore Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Permitir que o usuário volte para etapas anteriores do Ratio Escritório, visualize o histórico completo das respostas dos agentes e faça ida-e-volta real com o Marco sem perder rodadas anteriores.

**Architecture:** O backend passará a expor restauração explícita por snapshot/etapa e um histórico resumido de execução derivado dos snapshots e eventos já persistidos no `CaseStore`. O loop do Marco deixará de sobrescrever o estado anterior de forma opaca e passará a usar as rodadas já versionadas em `state.rodadas`, enquanto o frontend navegará por essas estruturas para mostrar histórico e botões de voltar.

**Tech Stack:** FastAPI, Pydantic, SQLite (`CaseStore`), React via `frontend/Escritorio/escritorio.html`, pytest.

---

### Task 1: Expor snapshots restauráveis no backend

**Files:**
- Modify: `backend/escritorio/store.py`
- Modify: `backend/escritorio/api.py`
- Test: `tests/escritorio/test_pipeline_api.py`

**Step 1: Write the failing tests**

Add tests that prove:
- `CaseStore` can load a snapshot by `id`.
- `POST /api/escritorio/cases/{caso_id}/restore` restores the chosen snapshot and updates metadata.
- The restore endpoint rejects unknown snapshot ids with `404`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/escritorio/test_pipeline_api.py -q`
Expected: FAIL because the restore endpoint and snapshot lookup do not exist yet.

**Step 3: Write minimal implementation**

Implement:
- `CaseStore.load_snapshot(snapshot_id: int)`
- `CaseStore.restore_snapshot(snapshot_id: int)` or equivalent helper
- FastAPI endpoint `POST /cases/{caso_id}/restore`
- append event `case.restored`

Keep restore minimal:
- replace current state with snapshot state
- save a new snapshot for the restored state
- update case index metadata

**Step 4: Run test to verify it passes**

Run: `pytest tests/escritorio/test_pipeline_api.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/store.py backend/escritorio/api.py tests/escritorio/test_pipeline_api.py
git commit -m "feat: add case snapshot restore endpoint"
```

### Task 2: Expor histórico navegável por etapa

**Files:**
- Modify: `backend/escritorio/api.py`
- Modify: `backend/escritorio/store.py`
- Test: `tests/escritorio/test_pipeline_api.py`

**Step 1: Write the failing tests**

Add tests that prove:
- `GET /cases/{caso_id}/history` returns etapas resumidas.
- Each history item includes snapshot id, stage, timestamp, and user-facing summary.
- The response is ordered chronologically.

**Step 2: Run test to verify it fails**

Run: `pytest tests/escritorio/test_pipeline_api.py -q`
Expected: FAIL because `history` does not exist.

**Step 3: Write minimal implementation**

Add:
- helper in API that builds a summarized timeline from `store.list_snapshots()` and `store.list_events()`
- endpoint `GET /cases/{caso_id}/history`

Do not over-model yet:
- one summary item per saved snapshot
- include stage labels sufficient for the frontend

**Step 4: Run test to verify it passes**

Run: `pytest tests/escritorio/test_pipeline_api.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/api.py backend/escritorio/store.py tests/escritorio/test_pipeline_api.py
git commit -m "feat: add escritorio history timeline endpoint"
```

### Task 3: Fechar o loop do Marco sem perder rodadas

**Files:**
- Modify: `backend/escritorio/adversarial.py`
- Modify: `backend/escritorio/graph/orchestrator.py`
- Test: `tests/escritorio/test_adversarial_graph.py`
- Test: `tests/escritorio/test_orchestrator.py`
- Test: `tests/escritorio/test_e2e_pipeline_flow.py`

**Step 1: Write the failing tests**

Add tests that prove:
- after editing and rerunning, a new rodada is appended instead of overwriting the previous rodada
- `critica_atual` points to the newest rodada
- `usuario_finaliza=False` after a non-final revision keeps the case in the review loop

**Step 2: Run test to verify it fails**

Run: `pytest tests/escritorio/test_adversarial_graph.py tests/escritorio/test_orchestrator.py tests/escritorio/test_e2e_pipeline_flow.py -q`
Expected: FAIL because the review loop is not explicit enough yet.

**Step 3: Write minimal implementation**

Tighten:
- `apply_human_revision(...)`
- `run_adversarial_graph(...)`

Contract:
- user edits draft
- state remains reviewable
- next `/run` produces a new rodada
- finalization only happens when user explicitly finalizes

**Step 4: Run test to verify it passes**

Run: `pytest tests/escritorio/test_adversarial_graph.py tests/escritorio/test_orchestrator.py tests/escritorio/test_e2e_pipeline_flow.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/adversarial.py backend/escritorio/graph/orchestrator.py tests/escritorio/test_adversarial_graph.py tests/escritorio/test_orchestrator.py tests/escritorio/test_e2e_pipeline_flow.py
git commit -m "feat: preserve adversarial rounds across review loop"
```

### Task 4: Adicionar voltar e histórico no frontend

**Files:**
- Modify: `frontend/Escritorio/escritorio.html`
- Test: `tests/escritorio/test_frontend_escritorio_real_runtime.py`

**Step 1: Write the failing tests**

Add tests that prove:
- the frontend requests `/history`
- there is a visible control to restore a previous stage
- the workspace renders the timeline/history of agent outputs
- the Marco flow exposes repeated rounds

**Step 2: Run test to verify it fails**

Run: `pytest tests/escritorio/test_frontend_escritorio_real_runtime.py -q`
Expected: FAIL because the history/restore UI does not exist yet.

**Step 3: Write minimal implementation**

Implement in the frontend:
- fetch `history`
- render a compact timeline/flow map
- show `Voltar para esta etapa`
- call `POST /restore`
- refresh state/events/history after restore
- show multiple rodadas do Marco in the review column or side panel

Keep the current working UX intact:
- no regression in Theo card, Helena modal, Marco cards, Auditor column

**Step 4: Run test to verify it passes**

Run: `pytest tests/escritorio/test_frontend_escritorio_real_runtime.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/Escritorio/escritorio.html tests/escritorio/test_frontend_escritorio_real_runtime.py
git commit -m "feat: add stage restore and review history to escritorio ui"
```

### Task 5: Verificação integrada do fluxo de ida e volta

**Files:**
- Modify: `tests/escritorio/test_pipeline_api.py`
- Modify: `tests/escritorio/test_e2e_pipeline_flow.py`

**Step 1: Write the failing tests**

Add an integrated flow that:
- creates/loads a case
- goes through Theo and Helena
- enters Marco
- applies a human revision without finalizing
- reruns Marco
- restores to a prior stage
- finalizes and proceeds to delivery

**Step 2: Run test to verify it fails**

Run: `pytest tests/escritorio/test_pipeline_api.py tests/escritorio/test_e2e_pipeline_flow.py -q`
Expected: FAIL until all contracts are connected.

**Step 3: Write minimal implementation**

Adjust only what the integrated flow still exposes as gap.

**Step 4: Run test to verify it passes**

Run: `pytest tests/escritorio/test_pipeline_api.py tests/escritorio/test_e2e_pipeline_flow.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/escritorio/test_pipeline_api.py tests/escritorio/test_e2e_pipeline_flow.py
git commit -m "test: cover restore and reviewer roundtrip flow"
```

### Task 6: Próximo bloco após concluir restore + review loop

**Files:**
- Modify later: `backend/escritorio/graph/drafting_graph.py`
- Modify later: `backend/escritorio/tools/google_search.py`
- Modify later: `backend/escritorio/redaction.py`
- Test later: `tests/escritorio/test_drafting_legislation.py`

**Step 1: Do not implement in this batch**

This task is intentionally deferred.

**Step 2: Scope for next session**

Strengthen legislation:
- guaranteed search for common statutory grounds
- CPC/CDC/CF articles expected in petitions
- “gratuidade de justiça” and similar procedural foundations

**Step 3: Commit**

No commit in this task. It is a follow-on work item.

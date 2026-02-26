# Ratio Sidebar + Pipeline Visual Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unificar "Fixar/Marcar" em "Salvar", compactar biblioteca lateral e substituir o estado de processamento por visual animado em loop com query real e microanimacao de resposta.

**Architecture:** A implementacao fica toda no frontend atual, mantendo o contrato de API. O estado de sessao migra de `pinned/marked` para `saved`. O render de turnos passa a usar biblioteca compacta e um novo componente visual de pipeline (canvas + tracker discreto) no card de pending.

**Tech Stack:** HTML, CSS, JavaScript (frontend existente), pytest, Playwright (smoke UI), Node syntax check.

---

### Task 1: Cobertura de regressao para biblioteca compacta e novo modo salvo

**Files:**
- Create: `tests/test_frontend_sidebar_saved.py`
- Test: `tests/test_frontend_sidebar_saved.py`

**Step 1: Write the failing test**

```python
from pathlib import Path


def test_sidebar_uses_history_and_saved_modes_only():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert 'data-library-mode="history"' in html
    assert 'data-library-mode="saved"' in html
    assert 'data-library-mode="pinned"' not in html
    assert 'data-library-mode="marked"' not in html
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_sidebar_uses_history_and_saved_modes_only -q`
Expected: FAIL because current HTML ainda usa `pinned`/`marked`.

**Step 3: Write minimal implementation**

- Ajustar `frontend/index.html` para modos `history` e `saved`.
- Ajustar `frontend/app.js` para estado e metadados `saved`.

**Step 4: Run test to verify it passes**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_sidebar_uses_history_and_saved_modes_only -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js tests/test_frontend_sidebar_saved.py
git commit -m "feat(ui): unify sidebar collections into saved mode"
```

### Task 2: Migracao de sessao e acoes de UI (Salvar)

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend_sidebar_saved.py`

**Step 1: Write the failing test**

```python
from pathlib import Path


def test_saved_action_labels_and_state_keys_present():
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "pin-turn" not in js
    assert "mark-turn" not in js
    assert "save-turn" in js
    assert "saved" in js
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_saved_action_labels_and_state_keys_present -q`
Expected: FAIL while old actions still exist.

**Step 3: Write minimal implementation**

- Reescrever campos de turno para `saved`.
- Migrar leitura de sessao antiga (`pinned/marked` -> `saved`).
- Atualizar toolbar e biblioteca para `Salvar/Remover`.
- Compactar layout visual dos itens na sidebar.

**Step 4: Run test to verify it passes**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_saved_action_labels_and_state_keys_present -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/app.js frontend/styles.css tests/test_frontend_sidebar_saved.py
git commit -m "feat(ui): migrate session flags and actions to saved"
```

### Task 3: Pipeline visual simples em loop no card pending

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend_sidebar_saved.py`

**Step 1: Write the failing test**

```python
from pathlib import Path


def test_pending_card_uses_rag_visual_markup():
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "pipeline-simple" in js
    assert "progress-track" in js
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_pending_card_uses_rag_visual_markup -q`
Expected: FAIL because visual ainda nao integrado.

**Step 3: Write minimal implementation**

- Inserir markup simplificado do pipeline no `renderPendingPipeline`.
- Implementar loop visual discreto por turno pendente (tokenizacao, embedding, busca vetorial, rerank, geracao).
- Mostrar preview da pergunta no card.
- Atualizar etapa ativa + timer + badge continuamente ate retorno da API.

**Step 4: Run test to verify it passes**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_pending_card_uses_rag_visual_markup -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/app.js frontend/styles.css tests/test_frontend_sidebar_saved.py
git commit -m "feat(ui): add looped rag visual in pending response card"
```

### Task 4: Microanimacao curta de caracteres na resposta final

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend_sidebar_saved.py`

**Step 1: Write the failing test**

```python
from pathlib import Path


def test_response_microtyping_hooks_exist():
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "microType" in js
    assert "prefers-reduced-motion" in Path("frontend/styles.css").read_text(encoding="utf-8")
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_response_microtyping_hooks_exist -q`
Expected: FAIL before implementation.

**Step 3: Write minimal implementation**

- Adicionar revelacao curta de caracteres no inicio da resposta concluida.
- Em seguida render completo automatico.
- Respeitar `prefers-reduced-motion` para fallback sem animacao.

**Step 4: Run test to verify it passes**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_response_microtyping_hooks_exist -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/app.js frontend/styles.css tests/test_frontend_sidebar_saved.py
git commit -m "feat(ui): add short microtyping reveal for final answer"
```

### Task 5: Verificacao integrada + sincronizacao git_ready

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Modify: `d:\dev\sumulas-stf_git_ready\frontend\index.html`
- Modify: `d:\dev\sumulas-stf_git_ready\frontend\app.js`
- Modify: `d:\dev\sumulas-stf_git_ready\frontend\styles.css`

**Step 1: Run full tests**

Run: `py -m pytest -q`
Expected: All PASS.

**Step 2: Validate JavaScript syntax**

Run: `node --check frontend/app.js`
Expected: Exit 0.

**Step 3: Smoke UI (playwright script)**

Run script local para abrir `frontend/index.html` e confirmar ausencia de console error.
Expected: `errors=0`.

**Step 4: Sync to git_ready**

Run copy commands para manter pasta de distribuicao alinhada.

**Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js frontend/styles.css tests/test_frontend_sidebar_saved.py docs/plans/2026-02-24-ratio-sidebar-pipeline-design.md docs/plans/2026-02-24-ratio-sidebar-pipeline-implementation.md
git commit -m "feat(ui): compact saved library and looped pending pipeline visual"
```

### Task 6: Tooltips detalhados para Fontes A-E

**Objetivo:** Explicar no painel de configuracoes o significado tecnico de cada nivel (A/B/C/D/E), com impacto para mais/menos no ranking.

### Task 7: Compactacao final da lateral "Salvos"

**Objetivo:** Garantir lista compacta consistente mesmo com 1 item (sem esticar card), com truncamento previsivel e acoes discretas.

### Task 8: Priorizacao normativa + enunciado/tese em citacoes

**Objetivo:** Priorizar por padrao fontes A/B/C sobre D/E, reduzir peso relativo de monocraticas e incluir enunciado/tese ao citar sumula/tema para evitar pesquisa manual do usuario.

# Composer Contact Strip Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Adicionar uma faixa discreta de contato com e-mail na area principal da interface, respeitando a identidade visual existente.

**Architecture:** A mudanca fica restrita ao `composer` principal para manter alta visibilidade sem criar um rodape global novo. O HTML recebe um bloco sem logica JS, e o CSS reutiliza a linguagem visual dos paines com tipografia mono, tons neutros e responsividade simples.

**Tech Stack:** HTML, CSS, pytest

---

### Task 1: Cobertura de teste

**Files:**
- Modify: `tests/test_frontend_sidebar_saved.py`
- Test: `tests/test_frontend_sidebar_saved.py`

**Step 1: Write the failing test**

Adicionar um teste que valide no `frontend/index.html`:
- existencia de um bloco de contato dentro de `.composer`,
- existencia do texto `Contato`,
- existencia de `mailto:contato@ratiojuris.me`.

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/test_frontend_sidebar_saved.py -k composer_contact`
Expected: FAIL porque o bloco ainda nao existe.

### Task 2: Implementacao minima

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`

**Step 3: Write minimal implementation**

Adicionar uma linha de contato entre `.composer-meta` e `#requestState`, com:
- rotulo discreto,
- link `mailto:contato@ratiojuris.me`,
- classes CSS novas de baixo impacto.

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q tests/test_frontend_sidebar_saved.py -k composer_contact`
Expected: PASS

### Task 3: Verificacao final

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend_sidebar_saved.py`

**Step 5: Run focused verification**

Run:
- `node --check frontend/app.js`
- `py -m pytest -q tests/test_frontend_sidebar_saved.py tests/test_packaging_support.py`

Expected: tudo verde.

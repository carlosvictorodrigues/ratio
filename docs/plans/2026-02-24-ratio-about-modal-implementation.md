# Ratio About Modal Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Criar um modal central `Sobre o Ratio` com abas, remover secoes institucionais de `Configuracoes` e integrar dados de contato/apoio (Instagram, email e PIX com QR e copia).

**Architecture:** A implementacao fica no frontend SPA atual. Um novo estado de UI (`about-open` + aba ativa) controlara o modal institucional. O settings continua focado apenas em configuracao tecnica. O conteudo do acervo e da estrutura documental migra para o modal novo com layout de cards/escala visual.

**Tech Stack:** HTML, CSS, JavaScript, pytest.

---

### Task 1: Testes de regressao para novo modal e remocao do settings

**Files:**
- Modify: `tests/test_frontend_sidebar_saved.py`

**Step 1: Write the failing test**
- Adicionar asserts para:
  - botao lateral `data-open-about`;
  - modal `id="aboutModal"`;
  - ausencia de `summary>Sobre o acervo` e `summary>Sobre o autor e apoio` dentro do settings;
  - presenca de instagram, email, qr e chave PIX.

**Step 2: Run test to verify it fails**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_about_modal_replaces_about_sections_in_settings -q`  
Expected: FAIL.

**Step 3: Write minimal implementation**
- Implementar estrutura no HTML/CSS/JS para satisfazer os asserts.

**Step 4: Run test to verify it passes**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py::test_about_modal_replaces_about_sections_in_settings -q`  
Expected: PASS.

### Task 2: HTML - botao lateral e modal com abas

**Files:**
- Modify: `frontend/index.html`

**Step 1: Add UI shell**
- Inserir botao `Sobre` na coluna esquerda.
- Criar modal `aboutModal` com:
  - cabecalho + fechar;
  - abas (`Acervo`, `Estrutura documental`, `Autor e apoio`);
  - conteudo por aba;
  - bloco apoio com QR e chave PIX.

**Step 2: Remove old settings sections**
- Excluir `details` de `Sobre o acervo` e `Sobre o autor e apoio` do settings.

**Step 3: Validate markup quickly**

Run: `rg -n "aboutModal|data-open-about|Sobre o acervo|Sobre o autor e apoio|apoio-pix.jpeg" frontend/index.html`  
Expected: novo modal presente e secoes antigas removidas do settings.

### Task 3: CSS - layout visual e responsividade do novo modal

**Files:**
- Modify: `frontend/styles.css`

**Step 1: Add style blocks**
- Criar estilos:
  - `.about-modal`, `.about-tabs`, `.about-tab`, `.about-pane`;
  - cards de acervo e visual de escala nao-ASCII;
  - bloco apoio (QR, chave, botao copiar).

**Step 2: Update responsive rules**
- Garantir comportamento mobile fullscreen para o modal novo.

**Step 3: Keep visual consistency**
- Preservar paleta e tipografia existentes.

### Task 4: JavaScript - estado/modal/abas/copiar PIX

**Files:**
- Modify: `frontend/app.js`

**Step 1: Add DOM refs and state**
- Referencias para modal `about`, botoes abrir/fechar, abas e botao copiar.

**Step 2: Add handlers**
- `setAboutOpen(open)`;
- troca de aba;
- copia da chave PIX via `navigator.clipboard`.

**Step 3: Integrate with overlay and Esc**
- Fechar modal `about` antes de settings/library/onboarding.

### Task 5: Verificacao final

**Files:**
- Modify: `tests/test_frontend_sidebar_saved.py`
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `frontend/app.js`

**Step 1: Run focused tests**

Run: `py -m pytest tests/test_frontend_sidebar_saved.py -q`  
Expected: PASS.

**Step 2: Run full suite**

Run: `py -m pytest -q`  
Expected: PASS.

**Step 3: Syntax check JS**

Run: `node --check frontend/app.js`  
Expected: exit 0.

**Step 4: Sync export folder**
- Copiar arquivos alterados para `d:\dev\sumulas-stf_git_ready`.

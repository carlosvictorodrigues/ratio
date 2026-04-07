# Ratio Escritorio -- Handoff para Continuacao

**Data:** 2026-04-06  
**Sessao anterior:** Claude Opus 4.6 (contexto esgotado)  
**Branch:** `codex/ratio-escritorio-foundation` (40 commits, worktree em `C:/Users/Gabriel/.config/superpowers/worktrees/Ratio - Pesquisa Jurisprudencial/codex/ratio-escritorio-foundation`)  
**Premissa:** Gemini-only (sem Claude API para contraparte)

---

## 1. O QUE FOI FEITO NESTA SESSAO

### 1.1 Revisao completa do backend

Li e analisei todos os 26 arquivos Python em `backend/escritorio/` no branch Codex. Inventario completo:

| Arquivo | Linhas | Funcao |
|---------|--------|--------|
| `models.py` | 115 | Pydantic schemas: `RatioEscritorioState`, `CriticaContraparte`, `FalhaCritica`, `TeseJuridica`, `RodadaAdversarial`, `IntakeChecklist` |
| `store.py` | 436 | `CaseStore` (SQLite por caso) + `CaseIndex` (indice global) |
| `state.py` | 40 | `build_redator_revision_payload()` com state trimming |
| `config.py` | 12 | `DEFAULT_PESQUISADOR_MODEL`, `DEFAULT_REASONING_MODEL` |
| `security.py` | 17 | `build_external_text_extraction_prompt()` com delimitadores XML |
| `intake.py` | 80 | Checklist heuristico, `process_intake_message()` |
| `intake_llm.py` | 53 | `generate_intake_with_gemini()` -- estrutura fatos via Gemini |
| `planning.py` | 54 | `decompose_case_with_gemini()` -- decompoe caso em teses |
| `redaction.py` | 175 | `generate_sections_with_gemini()`, `generate_revision_with_gemini()`, `infer_section_provenance()`, `build_section_evidence_pack()` |
| `contraparte.py` | 58 | `generate_critique_with_gemini()` -- critica adversarial |
| `adversarial.py` | 165 | Servico adversarial: `register_critique()`, `dismiss_finding()`, anti-sycophancy |
| `formatter.py` | 150 | `FormatadorPeticao` -- DOCX com python-docx |
| `verifier.py` | 355 | 7 regex, canonicalizacao, matching multi-nivel |
| `api.py` | 364 | Router FastAPI: CRUD de casos, intake, adversarial, pipeline, history |
| `graph/intake_graph.py` | 70 | `build_intake_graph()` com gate1 interrupt |
| `graph/drafting_graph.py` | 177 | `build_drafting_graph()` com pesquisa por tese, curadoria, gate2, redator |
| `graph/adversarial_graph.py` | 167 | `build_adversarial_graph()` com contraparte, anti-sycophancy, pausa humana, revisao, verificador, formatador |
| `graph/orchestrator.py` | 88 | `run_escritorio_pipeline()` -- encadeia 3 grafos |
| `graph/nodes.py` | 23 | **CODIGO MORTO** -- stubs nao usados |
| `graph/workflows.py` | 22 | **CODIGO MORTO** -- workflow foundation nao usado |
| `tools/ratio_tools.py` | 132 | `ratio_search()`, `run_with_retry()`, `search_tese_bundle()`, `merge_ranked_results()` |
| `tools/langchain_tools.py` | 101 | 5 @tool wrappers para LangChain |
| `tools/lancedb_access.py` | 38 | `LanceDBReadonlyRegistry` singleton thread-safe |

**Total: ~2.866 linhas de Python, 31 testes em `tests/escritorio/`, 259 testes passando.**

### 1.2 Frontend -- Template Gemini analisado

O Gemini gerou `frontend/Escritorio/template1.txt` (379 linhas React):
- **Paleta:** "Warm Obsidian" (dark theme, gold accent `#c4a882`)
- **Tipografia:** Cormorant Garamond (headings), Inter (body), JetBrains Mono (dados), Merriweather (citacoes)
- **3 modos:** Intake (chat) -> Dashboard (3 colunas: nav + editor + painel operacional) -> Delivery (checklist final + download)
- **Componentes:** BurnMeter, Stepper, IntakeMode, DashboardMode (ResearchHierarchy, editor), DeliveryMode
- **Left Rail:** Navegacao global (icones: pesquisa, timeline, bookmark, escritorio, acervo, config)
- **Mock data:** INITIAL_CHAT, MOCK_SECTIONS (3 secoes), MOCK_RESEARCH (1 tese com 1 doc)

---

## 2. ISSUES ENCONTRADOS NO BACKEND (a corrigir)

### 2.1 CRITICOS

**Issue 1: Contraparte usa Gemini em vez de Claude**
- **Arquivo:** `backend/escritorio/contraparte.py:33-58`
- **Decisao:** Como estamos trabalhando com hipotese Gemini-only, isso NAO e mais um issue. Manter Gemini.
- **Acao:** Nenhuma. O plano de arquitetura menciona Claude, mas a premissa do usuario e Gemini-only.

**Issue 2: Excecoes engolidas silenciosamente**
- **Arquivos:**
  - `graph/intake_graph.py:16-17` -- `except Exception: parsed = {}` (intake_node)
  - `graph/adversarial_graph.py:100-101` -- `except Exception: verificacoes = []` (verificador_node)
- **Impacto:** Bugs invisiveis em producao. LLM timeout, LanceDB lock, API 429 -- tudo vira silencio.
- **Correcao:** Adicionar `import logging; logger = logging.getLogger(__name__)` e `logger.exception("...")` em cada except.

**Issue 3: Codigo morto**
- **Arquivos:** `graph/nodes.py` (23 linhas) e `graph/workflows.py` (22 linhas)
- **Acao:** Deletar ambos. Nenhum outro arquivo os importa (verificado).

### 2.2 MEDIOS

**Issue 4: Context overflow parcialmente aberto**
- `redaction.py:12-37` -- `build_redaction_prompt()` inclui `state.fatos_brutos` sem truncagem
- `contraparte.py:11-23` -- `build_contraparte_prompt()` itera TODAS as `peca_sections`
- **Mitigacao:** Gemini 3.1 Pro tem 200K tokens, entao na pratica aguenta a maioria dos casos. Mas para seguranca, truncar a 150K chars antes de enviar.

**Issue 5: Prompt injection em prompts internos**
- `redaction.py:29` -- `state.tipo_peca` e `teses` passados raw sem escape
- `contraparte.py:13` -- `peca_sections` passados raw
- **Mitigacao:** Risco baixo pois dados vem do proprio sistema. Monitorar se/quando usuario importar parecer externo.

**Issue 6: Model name `gemini-3-flash` possivelmente incorreto**
- `config.py:7` -- verificar se API aceita `gemini-3-flash` ou se e `gemini-3.0-flash`
- **Acao:** Testar chamada real ou consultar docs da API.

### 2.3 BAIXOS

**Issue 7: Intake checklist leniente** -- `intake.py:39` exige 40 chars para `fatos_principais_cobertos`
**Issue 8: Formatter sem enderecamento automatico** -- `gerar()` chama `add_cabecalho()` mas nao `add_enderecamento()` (metodo existe mas nao e chamado)
**Issue 9: Orchestrator roda com `enable_interrupts=False`** -- Bypassa gates humanos (correto para programmatic, mas frontend precisa usar interrupts)

---

## 3. FORMATTER -- STATUS vs. GUIA DE FORMATACAO JURIDICA

| Regra | Status | Onde |
|-------|--------|------|
| Margens 3cm esquerda/superior, 2cm direita/inferior | OK | `formatter.py:26-29` |
| Times New Roman 12pt | OK | `formatter.py:32-33` |
| Espacamento 1.5 | OK | `formatter.py:35` |
| Alinhamento justificado | OK | `formatter.py:38` |
| Recuo primeira linha 2cm | OK | `formatter.py:37` |
| Numeracao de paginas | OK | `formatter.py:118-132` |
| Cor preta para todo texto | OK | `formatter.py:34` |
| Citacao longa (recuo 4cm, fonte 10, esp. simples) | OK | `formatter.py:87-97` |
| Enderecamento (centrado, bold, uppercase) | EXISTE mas NAO CHAMADO | `formatter.py:71-81` -- `add_enderecamento()` existe, `gerar()` nao chama |
| Espacamento apos paragrafo 6pt | OK | `formatter.py:36` |
| Headings: bold, 14pt/12pt, sem recuo | OK | `formatter.py:40-47` |

**Unico fix necessario:** Chamar `add_enderecamento()` dentro de `gerar()`.

---

## 4. O QUE RESTA FAZER

### 4.1 Backend -- Correcoes rapidas (15 min)

1. Deletar `graph/nodes.py` e `graph/workflows.py` (codigo morto)
2. Adicionar logging nos `except Exception` silenciosos (intake_graph.py, adversarial_graph.py)
3. Chamar `add_enderecamento()` no `formatter.py:gerar()`
4. Opcional: aumentar threshold de checklist de 40 para 200 chars

### 4.2 Frontend -- Templates (tarefa principal pendente)

O usuario pediu **diversos templates com abordagens distintas**. O template1 (Gemini) ja existe. Precisam ser criados:

**Template 2: "Legal Minimal"**
- Abordagem: layout clean, foco total no texto. Sem 3 colunas no dashboard.
- Intake como wizard/stepper em vez de chat.
- Editor full-width. Painel de critica como sidebar toggle.
- Cores: slate neutro com accent azul escuro profissional.

**Template 3: "Document-Centric"**
- Abordagem: simula processador de texto (Word-like). Editor WYSIWYG centralizado.
- Painel de pesquisa em drawer lateral esquerdo.
- Contraparte como "reviewer comments" estilo Google Docs (margem direita).
- Cores: fundo branco/creme, tipografia serif pesada.

**Template 4: "Kanban Pipeline"**
- Abordagem: cada onda do pipeline e uma coluna visual (Intake | Pesquisa | Redacao | Adversarial | Entrega).
- Cards movem entre colunas conforme progresso.
- Editor abre em modal/overlay quando card e clicado.
- Cores: fundo escuro, cards com borda colorida por status.

Todos devem:
- Ser arquivos React standalone em `frontend/Escritorio/templateN.txt`
- Usar Tailwind CSS inline
- Incluir os mesmos mocks (INITIAL_CHAT, MOCK_SECTIONS, MOCK_RESEARCH)
- Manter BurnMeter e Stepper
- Demonstrar os 3 modos: Intake, Workspace, Delivery
- Ser coerentes com a paleta premium do Ratio existente

### 4.3 Backend -- Proximas fases (apos frontend)

Conforme Appendix C do plano de arquitetura:
- **Fase 3:** Pesquisa juridica real por tese (tool-driven loop com refinamento)
- **Fase 4:** Redacao automatica real com split por secao + refinamento
- **Fase 5:** Verificador deterministico 5 camadas completo
- **Fase 6:** Formatacao DOCX final (acabamento)
- **Fase 7:** Frontend React integrado
- **Fase 8:** Testes ponta a ponta

---

## 5. COMO CONTINUAR EM OUTRA JANELA

### 5.1 Para correcoes no backend

```bash
# Worktree do Codex ja existe:
cd "C:/Users/Gabriel/.config/superpowers/worktrees/Ratio - Pesquisa Jurisprudencial/codex/ratio-escritorio-foundation"

# Verificar estado
git log --oneline -5
py -m pytest tests/escritorio -q

# Aplicar correcoes descritas na secao 4.1
```

### 5.2 Para criar templates de frontend

```bash
# Trabalhar no main (frontend nao depende do branch Codex)
cd "d:\dev\Ratio - Pesquisa Jurisprudencial"
ls frontend/Escritorio/
# template1.txt ja existe (Gemini)
# Criar template2.txt, template3.txt, template4.txt
```

### 5.3 Contexto para Claude

Diga ao Claude na nova janela:

> Leia `docs/plans/2026-04-06-escritorio-handoff.md` e continue o trabalho pendente.
> Premissa: Gemini-only (sem Claude API).
> Template 1 do frontend ja existe em `frontend/Escritorio/template1.txt`.
> Crie os templates 2, 3 e 4 conforme descrito no handoff.
> Depois aplique as correcoes rapidas no backend (secao 4.1).

---

## 6. DECISOES TOMADAS NESTA SESSAO

1. **Gemini-only:** O usuario decidiu que a contraparte usara Gemini (nao Claude). Isso simplifica -- sem necessidade de Anthropic API key.
2. **4 issues do Gemini review:** 3 de 4 estao resolvidos no codigo (tool latency, prompt injection, LanceDB). O #1 (context overflow) esta parcialmente aberto mas mitigado pela janela de 200K do Gemini Pro.
3. **Formatter:** Quase completo. Unico gap real e chamar `add_enderecamento()` em `gerar()`.
4. **Codigo morto identificado:** `graph/nodes.py` e `graph/workflows.py` podem ser deletados com seguranca.

---

## 7. ARQUIVOS-CHAVE PARA REFERENCIA

- **Plano de arquitetura:** `docs/plans/2026-04-06-ratio-escritorio-architecture.md` (~3500 linhas)
- **Review Gemini:** `docs/reviews/review_gemini_3.1_pro.md`
- **Script de review:** `docs/review_architecture.py`
- **Template 1 frontend:** `frontend/Escritorio/template1.txt`
- **Backend inteiro:** `backend/escritorio/` no branch `codex/ratio-escritorio-foundation`
- **Testes:** `tests/escritorio/` no mesmo branch
- **Memory Claude:** `C:\Users\Gabriel\.claude\projects\d--dev-Ratio---Pesquisa-Jurisprudencial\memory\`

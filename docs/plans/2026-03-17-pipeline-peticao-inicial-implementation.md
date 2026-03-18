# Pipeline De Peticao Inicial Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Construir o MVP de peticao inicial do Ratio com dossie estruturado, busca dual, analise de cobertura da minuta e stress test adversarial ancorado em precedente real.

**Architecture:** O backend passa a expor um pipeline de peticao inicial como operacoes internas reutilizaveis e endpoints de orquestracao. O frontend adiciona um fluxo em etapas (`Caso`, `Eixos`, `Pesquisa`, `Dossie`, `Minuta`, `Stress test`) consumindo artefatos estruturados em vez de chat livre.

**Tech Stack:** FastAPI, Python, RAG atual em `rag/query.py`, JavaScript vanilla, HTML/CSS estaticos, `pytest`.

---

### Task 1: Definir contratos e estado da sessao de peticao

**Files:**
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\petition_pipeline.py`
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_petition_pipeline_contract.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\main.py`

**Step 1: Write the failing test**

Adicionar teste para os objetos basicos da sessao: `matriz_do_caso`, `eixo`, `resultado_favoravel`, `resultado_contrario`, `restricao_processual`, `item_cobertura` e `item_fila_ataque`.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_petition_pipeline_contract.py`
Expected: FAIL porque os contratos ainda nao existem.

**Step 3: Write minimal implementation**

Criar os modelos iniciais e um estado de sessao simples no backend para o pipeline de peticao.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_petition_pipeline_contract.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/petition_pipeline.py tests/test_petition_pipeline_contract.py backend/main.py
git commit -m "feat: define petition pipeline contracts"
```

### Task 2: Implementar matriz do caso, proposta de eixos e gate de confirmacao

**Files:**
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\petition_pipeline.py`
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_petition_case_setup.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\main.py`

**Step 1: Write the failing test**

Adicionar testes para:
- `criar_matriz_do_caso`;
- `propor_eixos`;
- `confirmar_eixos` bloqueando as buscas ate revisao humana.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_petition_case_setup.py`
Expected: FAIL porque o fluxo inicial ainda nao existe.

**Step 3: Write minimal implementation**

Implementar normalizacao do caso, sugestao de eixos e persistencia das edicoes feitas pelo advogado.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_petition_case_setup.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/petition_pipeline.py tests/test_petition_case_setup.py backend/main.py
git commit -m "feat: add petition case setup flow"
```

### Task 3: Extrair busca favoravel e busca contraria por eixo

**Files:**
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\rag\query.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\petition_pipeline.py`
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_petition_axis_search.py`

**Step 1: Write the failing test**

Adicionar testes para `buscar_favoraveis` e `buscar_contrarios`, exigindo por eixo:
- precedente;
- trecho nuclear;
- motivo de relevancia;
- precedente base para itens contrarios.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_petition_axis_search.py`
Expected: FAIL porque as operacoes dedicadas ainda nao existem.

**Step 3: Write minimal implementation**

Encapsular a logica de busca atual em helpers chamaveis com `contexto + eixo`, separados para uso favoravel e contrario.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_petition_axis_search.py`
Expected: PASS

**Step 5: Commit**

```bash
git add rag/query.py backend/petition_pipeline.py tests/test_petition_axis_search.py
git commit -m "feat: add axis-level favorable and contrary search"
```

### Task 4: Filtrar citacao ornamental e montar kits por eixo

**Files:**
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\petition_pipeline.py`
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_petition_authority_filtering.py`

**Step 1: Write the failing test**

Adicionar teste que diferencie precedente forte de citacao decorativa quando ambos tratam do mesmo tema, mas apenas um resolve o mesmo ponto controvertido em contexto fatico analogo.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_petition_authority_filtering.py`
Expected: FAIL porque a consolidacao agressiva ainda nao existe.

**Step 3: Write minimal implementation**

Implementar `consolidar_autoridades`, `extrair_tese_nuclear` e montagem dos kits favoravel/contrario por eixo.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_petition_authority_filtering.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/petition_pipeline.py tests/test_petition_authority_filtering.py
git commit -m "feat: filter ornamental citations from petition dossiers"
```

### Task 5: Mapear provas e restricoes processuais

**Files:**
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\petition_pipeline.py`
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_petition_proof_and_procedure.py`

**Step 1: Write the failing test**

Adicionar testes para:
- `mapear_provas`, ligando fato alegado a documento presente, ausente ou insuficiente;
- `avaliar_restricoes_processuais`, cobrindo checks deterministas iniciais de competencia, prescricao/decadencia e documentos indispensaveis.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_petition_proof_and_procedure.py`
Expected: FAIL porque o mapa de prova e os checks processuais ainda nao existem.

**Step 3: Write minimal implementation**

Implementar o mapa de prova e a camada hibrida inicial de analise processual, separando regra deterministica do que sera interpretado depois pelo agente-juiz.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_petition_proof_and_procedure.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/petition_pipeline.py tests/test_petition_proof_and_procedure.py
git commit -m "feat: add petition proof mapping and procedural checks"
```

### Task 6: Montar o dossie estruturado e o pacote de exportacao

**Files:**
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\petition_pipeline.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\main.py`
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_petition_dossier.py`

**Step 1: Write the failing test**

Adicionar teste validando que `montar_dossie` gera os blocos fixos do MVP e que `exportar_pacote_redacao` inclui fatos autorizados, teses autorizadas, teses vedadas, fundamentos favoraveis e contrarios.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_petition_dossier.py`
Expected: FAIL porque o dossie estruturado ainda nao existe.

**Step 3: Write minimal implementation**

Implementar `montar_dossie`, `exportar_pacote_redacao` e endpoints para criar/ler o dossie da sessao.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_petition_dossier.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/petition_pipeline.py backend/main.py tests/test_petition_dossier.py
git commit -m "feat: build structured petition dossier"
```

### Task 7: Criar a shell do frontend em etapas

**Files:**
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/index.html`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/app.js`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/styles.css`
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_frontend_petition_flow.py`

**Step 1: Write the failing test**

Adicionar teste estatico cobrindo a presenca das etapas `Caso`, `Eixos`, `Pesquisa`, `Dossie`, `Minuta` e `Stress test`.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_frontend_petition_flow.py -k shell`
Expected: FAIL porque a shell da interface ainda nao existe.

**Step 3: Write minimal implementation**

Adicionar a estrutura principal do fluxo, sem logica completa, apenas navegacao e containers das seis etapas.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_frontend_petition_flow.py -k shell`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js frontend/styles.css tests/test_frontend_petition_flow.py
git commit -m "feat: add petition workflow shell"
```

### Task 8: Implementar as telas de Eixos, Pesquisa e Dossie

**Files:**
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/index.html`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/app.js`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/styles.css`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_frontend_petition_flow.py`

**Step 1: Write the failing test**

Adicionar testes para:
- edicao e confirmacao de eixos;
- exibicao do progresso real da pesquisa;
- renderizacao do dossie com colunas favoraveis, contrarios, distincoes, prova e restricoes processuais.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_frontend_petition_flow.py -k "axes or progress or dossier"`
Expected: FAIL porque essas telas ainda nao existem.

**Step 3: Write minimal implementation**

Renderizar eixos editaveis com gate de confirmacao, estados de progresso do pipeline e workspace do dossie focado em poucos precedentes fortes.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_frontend_petition_flow.py -k "axes or progress or dossier"`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js frontend/styles.css tests/test_frontend_petition_flow.py
git commit -m "feat: add petition dossier workflow screens"
```

### Task 9: Implementar a analise de cobertura da minuta

**Files:**
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\petition_pipeline.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\main.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/index.html`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/app.js`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_petition_dossier.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_frontend_petition_flow.py`

**Step 1: Write the failing test**

Adicionar testes para `avaliar_cobertura_da_minuta`, exigindo tres grupos: `ancorado`, `sem_respaldo` e `nao_utilizado`.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_petition_dossier.py tests/test_frontend_petition_flow.py -k coverage`
Expected: FAIL porque a analise de cobertura ainda nao existe.

**Step 3: Write minimal implementation**

Implementar a comparacao entre minuta e dossie no backend e exibir a tela `Minuta` com destaque para argumentos sem lastro e fundamentos pesquisados nao usados.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_petition_dossier.py tests/test_frontend_petition_flow.py -k coverage`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/petition_pipeline.py backend/main.py frontend/index.html frontend/app.js tests/test_petition_dossier.py tests/test_frontend_petition_flow.py
git commit -m "feat: add petition draft coverage analysis"
```

### Task 10: Implementar o stress test com agente-reu, agente-juiz e fila de ataque

**Files:**
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\petition_pipeline.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\rag\query.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\backend\main.py`
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_petition_stress_test.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/index.html`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/app.js`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\frontend/styles.css`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_frontend_petition_flow.py`

**Step 1: Write the failing test**

Adicionar testes cobrindo:
- `atacar_minuta_com_rag` com busca nova sobre a minuta concreta;
- `revisar_minuta_com_juiz_hibrido` com regras e inferencia separadas;
- `gerar_fila_de_ataque` exigindo precedente base e ordenacao por impacto;
- tela `Stress test` com painel lateral e acoes do advogado.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_petition_stress_test.py tests/test_frontend_petition_flow.py -k "stress or queue"`
Expected: FAIL porque a camada adversarial ainda nao existe.

**Step 3: Write minimal implementation**

Implementar o primeiro ciclo do agente-reu, o agente-juiz hibrido, a fila consolidada de ataque e a interface de revisao com painel lateral.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_petition_stress_test.py tests/test_frontend_petition_flow.py -k "stress or queue"`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/petition_pipeline.py rag/query.py backend/main.py tests/test_petition_stress_test.py frontend/index.html frontend/app.js frontend/styles.css tests/test_frontend_petition_flow.py
git commit -m "feat: add petition adversarial stress test"
```

### Task 11: Validar o fluxo ponta a ponta e documentar limites do MVP

**Files:**
- Create: `D:\dev\Ratio - Pesquisa Jurisprudencial\tests\test_petition_pipeline_end_to_end.py`
- Modify: `D:\dev\Ratio - Pesquisa Jurisprudencial\README.md`

**Step 1: Write the failing test**

Adicionar teste integrado cobrindo o caminho minimo: criar caso, confirmar eixos, executar busca dual, montar dossie, importar minuta, analisar cobertura e gerar fila de ataque.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_petition_pipeline_end_to_end.py`
Expected: FAIL porque o fluxo completo ainda nao esta conectado.

**Step 3: Write minimal implementation**

Ajustar os pontos de integracao restantes e documentar no `README.md` o novo fluxo, seus limites e a necessidade de validacao humana.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_petition_pipeline_end_to_end.py`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_petition_pipeline_end_to_end.py README.md
git commit -m "docs: describe petition pipeline workflow"
```

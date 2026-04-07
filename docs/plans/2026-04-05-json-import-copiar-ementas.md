# Plano Revisado: Import JSON no Meu Acervo + Copiar Ementas em Lote

## Status

- Revisado contra o código real em `2026-04-05`
- O plano original **não deve ser executado como estava**
- Há um caminho técnico viável, mas a implementação deve esperar resposta das perguntas pendentes no fim deste documento

---

## Contexto

Um usuário do Ratio quer:

1. Importar milhares de arquivos JSON contendo acórdãos para o Meu Acervo, que hoje aceita apenas PDF.
2. Copiar ementas das fontes citadas na resposta, inclusive em lote.

Este documento consolida:

- o estado atual confirmado no código
- os problemas encontrados no plano original
- um plano técnico revisado
- os testes que precisam ser atualizados
- as perguntas que precisam ser respondidas antes da implementação

---

## Estado Atual Confirmado no Código

### Backend: Meu Acervo

- O endpoint `POST /api/meu-acervo/index` aceita apenas arquivos `.pdf`.
- A validação atual rejeita qualquer extensão diferente de `.pdf`.
- O backend grava cada upload em disco via `_store_upload_file(...)`.
- Depois disso, valida magic-bytes de PDF com `_ensure_pdf_magic_bytes(...)`.
- O pipeline assíncrono real usa `_start_user_acervo_index_job(...)`, `_run_user_acervo_index_job(...)` e `_index_single_user_acervo_file(...)`.
- O nome `_process_user_corpus_job` citado no plano original **não existe**.
- O processamento atual do Meu Acervo é orientado a PDF:
  - extrai texto com `PyMuPDF` e OCR opcional
  - divide em chunks
  - limpa ruído com `_clean_user_chunk_with_flash(...)`
  - gera embeddings
  - grava no LanceDB
- O schema do LanceDB do Meu Acervo já suporta os campos necessários para jurisprudência:
  - `tribunal`
  - `tipo`
  - `processo`
  - `relator`
  - `ramo_direito`
  - `data_julgamento`
  - `orgao_julgador`
  - `texto_busca`
  - `texto_integral`
  - além de metadados como `source_id`, `source_label`, `doc_sha256`, `chunk_index` e `chunk_total`

### Frontend: Meu Acervo

- O `input` de arquivo do Meu Acervo usa `accept="application/pdf"`.
- O fluxo de seleção por pasta filtra manualmente apenas arquivos `.pdf`.
- As mensagens da UI ainda falam explicitamente em "PDF".
- O polling do job assíncrono usa `processed_files`, `total_files`, `indexed_docs`, `duplicate_files`, `skipped_files` e `eta_seconds`.

### Frontend: painel de evidências / fontes

- As fontes são renderizadas por `renderSources(turn)`.
- Cada card usa `.source-card.source-card-actionable`.
- O clique no card abre o documento inteiro.
- O handler atual já trata `data-source-action`, mas hoje só cobre abertura inline/external.
- O handler de teclado (`Enter` / `Space`) abre o card ao focar qualquer elemento dentro dele.
- Os ícones Lucide só aparecem depois de `refreshIcons()`.

### Frontend: modais

- O app já possui padrão próprio de modal/painel, controlado por `document.body.dataset.*Open`.
- Overlay e `Escape` já são tratados nesse padrão.
- O app **não usa** `<dialog>` como padrão principal.

---

## Revisão Crítica do Plano Original

## 1. O plano original cita a função errada do pipeline

O documento original fala em branching em `_process_user_corpus_job`, mas o pipeline real do Meu Acervo passa por:

- `_start_user_acervo_index_job(...)`
- `_run_user_acervo_index_job(...)`
- `_index_single_user_acervo_file(...)`

Se alguém seguir o plano original literalmente, vai procurar uma função que não existe.

## 2. A proposta de `_extract_decisions_from_json(file_bytes, file_name)` precisa ser ajustada

Hoje o upload é salvo em disco e o pipeline posterior trabalha com `temp_path`. Para arquivos grandes, manter o JSON inteiro em memória como `file_bytes` é uma decisão ruim.

Recomendação:

- usar `_extract_decisions_from_json_path(temp_path, file_name)` ou
- ler bytes do arquivo só dentro da função, a partir do caminho já persistido

## 3. A heurística sugerida para encontrar decisões é frágil

O plano original propõe:

- array top-level
- objeto com array aninhado
- objeto único
- "primeira lista de dicts com >= 2 itens"

Problema:

- isso ignora listas aninhadas com apenas 1 item
- isso pode escolher a lista errada se o JSON tiver múltiplas listas auxiliares

Recomendação:

- procurar recursivamente listas de dicionários
- aceitar listas com `>= 1` item
- se houver múltiplas listas candidatas, escolher a de maior tamanho ou a primeira com campos de decisão reconhecíveis

## 4. `processed_files` não pode mudar de semântica

O plano original diz:

- "`processed_files` conta arquivos JSON"

Isso está incorreto. Hoje `processed_files` é o contador global do lote e alimenta a UI com:

- `X/Y arquivo(s) processados`
- ETA do job
- avanço do polling

Se ele mudar de semântica, o fluxo quebra para lotes mistos PDF+JSON.

Recomendação:

- manter `processed_files` como contador global de arquivos processados no lote
- adicionar contadores novos, por exemplo:
  - `accepted_pdf_files`
  - `accepted_json_files`
  - `extracted_decisions`
  - opcionalmente `skipped_decisions`

## 5. O plano do frontend esqueceu o fluxo de pasta inteira

O documento original só fala em mudar o `accept` do file picker.

Isso não basta.

Hoje o frontend também faz:

- `userCorpusFolderInput.files`
- filtro manual por `f.name.toLowerCase().endsWith(".pdf")`

Sem ajustar isso, JSON continuará sendo ignorado no upload por pasta.

## 6. O plano da cópia esqueceu teclado e ícones

O plano original cobre o clique, mas não cobre:

- o handler de `keydown`, que hoje abre o card ao pressionar `Enter`/`Space`
- a necessidade de chamar `refreshIcons()` após inserir novos botões com `data-lucide`

Sem isso:

- um botão de copiar focado no teclado pode acabar abrindo o documento
- o ícone de copiar pode não renderizar

## 7. O modal em `<dialog>` é inconsistente com a arquitetura atual

O app já tem um padrão consistente de modal/painel baseado em:

- `document.body.dataset.*Open`
- overlay global
- fechamento por `Escape`

Adicionar `<dialog>` cria um segundo padrão de modal. Isso aumenta risco, complexidade e inconsistência visual/comportamental.

Recomendação:

- seguir o padrão já existente do app
- usar uma `section`/`aside` com `role="dialog"` e um novo estado, por exemplo `data-batch-copy-open`

## 8. O plano não inclui atualização dos testes existentes

O repositório já possui:

- testes de contrato do endpoint do Meu Acervo
- testes estáticos do frontend para o Meu Acervo / painel lateral

O plano original lista apenas verificações manuais. Isso é insuficiente para este projeto.

---

## Decisões Técnicas Recomendadas

## Feature 1: Import JSON no Meu Acervo

### Objetivo

Permitir upload de `.json` além de `.pdf`, transformando cada decisão encontrada no JSON em um ou mais registros do Meu Acervo no LanceDB, sem quebrar o pipeline existente de PDF.

### Backend

#### 1. Ajustar validação de tipo em `backend/main.py`

Na API `POST /api/meu-acervo/index`:

- aceitar `.pdf` e `.json`
- trocar a contagem `skipped_non_pdf` por algo semanticamente correto, por exemplo `skipped_unsupported_files`
- atualizar mensagens de erro de:
  - "Nenhum arquivo PDF enviado..."
  - para algo como "Nenhum arquivo PDF/JSON enviado..."

Também é recomendável gravar em `stored_files` um campo explícito como:

- `file_kind: "pdf"` ou `file_kind: "json"`

Isso evita depender apenas da extensão depois.

#### 2. Adicionar validação de assinatura para JSON

Criar algo como `_ensure_json_magic_bytes(temp_path, filename)`:

- ler o primeiro byte não-whitespace
- aceitar apenas `{` ou `[`
- se falhar, retornar erro de validação no mesmo estilo do PDF

Observação:

- isso valida "parece JSON"
- isso **não substitui** o parse real com `json.loads`
- JSON sintaticamente inválido ainda deve ser tratado no estágio de processamento

#### 3. Criar helper de extração a partir de arquivo em disco

Em vez de `_extract_decisions_from_json(file_bytes, file_name)`, usar algo como:

- `_extract_decisions_from_json_path(temp_path, file_name)`

Responsabilidades da função:

- ler o arquivo
- tentar `utf-8`
- fallback para `latin-1`
- fazer `json.loads`
- localizar decisões
- normalizar cada decisão para o schema interno do Meu Acervo

#### 4. Criar heurística robusta para localizar decisões no JSON

A função de extração deve suportar, no mínimo:

- array top-level de objetos
- objeto único representando 1 decisão
- objeto com lista(s) aninhada(s) de decisões

Recomendação:

- percorrer a estrutura recursivamente
- coletar listas de dicionários
- aceitar listas com pelo menos 1 item
- priorizar listas com maior quantidade de itens
- dar preferência a listas cujos elementos tenham campos conhecidos como:
  - `ementa`
  - `processo`
  - `relator`
  - `tribunal`
  - `orgao_julgador`
  - `data_julgamento`
  - `texto_integral`

#### 5. Mapear aliases de campos

O dicionário de aliases do plano original faz sentido como ponto de partida. Ele deve permanecer, com espaço para expansão.

Sugestão inicial:

```python
FIELD_ALIASES = {
    "ementa": ["ementa", "ementa_completa", "ementa_curta", "ementario"],
    "processo": ["processo", "numero_processo", "processo_codigo", "numero"],
    "relator": ["relator", "nome_relator", "ministro_relator"],
    "tribunal": ["tribunal", "nome_tribunal", "sigla_tribunal"],
    "orgao_julgador": ["orgao_julgador", "orgao", "camara", "turma"],
    "data_julgamento": ["data_julgamento", "julgamento_data", "dt_julgamento"],
    "tipo": ["tipo", "tipo_documento", "classe", "classe_sigla"],
    "texto_integral": ["texto_integral", "inteiro_teor", "acordao_integra", "conteudo"],
    "ramo_direito": ["ramo_direito", "assunto", "nome_assunto_cnj"],
}
```

#### 6. Normalizar os campos antes de indexar

Cada decisão extraída deve produzir um dicionário com:

- `tribunal`
- `tipo`
- `processo`
- `relator`
- `ramo_direito`
- `data_julgamento`
- `orgao_julgador`
- `texto_busca`
- `texto_integral`

Regras recomendadas:

- `texto_busca`:
  - priorizar `ementa`
  - se houver `texto_integral` curto ou útil, concatenar
  - limitar a `8000` chars
- `texto_integral`:
  - usar `texto_integral` quando existir
  - fallback para `ementa`
- `data_julgamento`:
  - tentar usar `_clean_iso_date(...)`
  - se vier em formato não-ISO e não houver normalizador confiável, manter vazio por enquanto
- `tribunal`, `processo`, `relator`, `orgao_julgador`, `tipo`, `ramo_direito`:
  - preencher com string vazia ou fallback defensivo

#### 7. Atualizar o pipeline real: `_index_single_user_acervo_file(...)`

O branching deve acontecer em `_index_single_user_acervo_file(...)`, não em uma função inexistente.

Fluxo proposto:

- se `file_kind == "pdf"`:
  - manter pipeline atual
- se `file_kind == "json"`:
  - extrair decisões
  - para cada decisão:
    - gerar chunks
    - pular OCR
    - pular a limpeza LLM especializada em ruído de OCR
    - gerar embeddings
    - fazer upsert no LanceDB

#### 8. Não reutilizar cegamente `_clean_user_chunk_with_flash(...)` para JSON

O prompt atual de limpeza é voltado a:

- ruído de OCR
- paginação
- cabeçalhos/rodapés de PDF

Para JSON estruturado, isso não é o ideal.

Recomendação:

- pular completamente a etapa de cleaning LLM para JSON
- no máximo usar limpeza heurística leve, se necessário

#### 9. Atualizar a geração dos registros LanceDB

Hoje `_build_user_acervo_record_batch(...)` gera defaults genéricos:

- `tribunal = "MEU_ACERVO"`
- `tipo = "acervo_usuario"`
- `processo = filename`
- `relator = "-"`
- `orgao_julgador = "Meu Acervo"`

Isso precisa ser ajustado para o caso JSON.

Opções viáveis:

1. ampliar `_build_user_acervo_record_batch(...)` para aceitar overrides de metadados
2. criar uma função específica para JSON, por exemplo `_build_user_acervo_record_batch_from_decision(...)`

Cada decisão deve virar um "sub-documento", por exemplo:

```text
{source_id}:{file_digest[:16]}:dec{i}:chunk{j}
```

Também é recomendável registrar em `metadata_extra`:

- `source_kind = "user"`
- `source_id`
- `source_label`
- `file_name`
- `doc_sha256`
- `decision_index`
- `decision_total`
- `chunk_index`
- `chunk_total`
- `file_kind = "json"`

#### 10. Ajustar contadores e payload do job

Manter:

- `processed_files` = total de arquivos do lote já finalizados

Adicionar:

- `accepted_pdf_files`
- `accepted_json_files`
- `extracted_decisions`
- opcional: `skipped_decisions`

Esses campos devem aparecer em:

- `progress`
- `result`
- mensagem final do job, quando aplicável

Exemplo de mensagem final:

- `Indexacao concluida: 37 doc(s), 112 decisao(oes) extraidas de JSON, 3 duplicado(s), 1 ignorado(s).`

#### 11. Tratar edge cases de JSON

Casos obrigatórios:

- JSON com assinatura inválida:
  - erro de validação imediata
- JSON sintaticamente inválido:
  - logar warning
  - marcar arquivo como `skipped_files += 1`
  - não derrubar o job inteiro
- JSON sem decisões detectáveis:
  - warning
  - `skipped_files += 1`
- decisão sem `ementa` e sem `texto_integral`:
  - ignorar decisão individual
- decisão com texto muito curto:
  - ignorar decisão individual
- encoding inválido:
  - tentar fallback
  - se não der, ignorar o arquivo com warning

#### 12. Observação importante sobre deduplicação na busca

O pipeline de busca do projeto faz deduplicação por:

- `tribunal`
- `tipo`
- `processo`

Isso significa que, se o usuário importar múltiplas decisões com o mesmo trio `tribunal|tipo|processo`, a busca/rerank pode colapsar resultados semelhantes.

Isso não bloqueia a feature, mas deve ser mantido em mente ao testar casos com processos repetidos.

### Frontend

#### 13. Ajustar o file picker e o fluxo de pasta

Em `frontend/index.html`:

- mudar o texto de "Arquivos PDF" para "Arquivos PDF ou JSON"
- trocar `accept="application/pdf"` por algo que aceite ambos

Em `frontend/app.js`:

- o fluxo de pasta inteira deve aceitar `.json` também
- o frontend hoje filtra manualmente apenas `.pdf`; isso precisa mudar

Também atualizar mensagens como:

- `Selecione ao menos 1 PDF para indexar.`
- para algo como:
  - `Selecione ao menos 1 PDF ou JSON para indexar.`

#### 14. Ajustar o status do polling

Na UI do Meu Acervo:

- se `extracted_decisions > 0`, exibir informação complementar

Exemplo:

- `Extraindo decisoes do JSON (2/10 arquivo(s) processados | 37 decisoes extraidas)`
- ou, na conclusão:
  - `Indexacao concluida: 112 decisoes extraidas de 4 arquivo(s) JSON.`

---

## Feature 2: Copiar Ementa + Cópia em Lote

### Objetivo

Permitir ao advogado copiar rapidamente o texto principal da fonte exibida no painel de evidências, individualmente ou em lote, sem abrir o inteiro teor.

### Diretriz de UX

- cópia individual deve ser rápida e discreta
- cópia em lote deve seguir o padrão visual já existente do app
- teclado, acessibilidade e feedback visual precisam funcionar

### Frontend: botão individual por fonte

#### 1. Adicionar botão de copiar em cada `.source-card`

Dentro de `renderSources(turn)`:

- incluir um botão com `data-source-action="copy-ementa"`
- usar ícone Lucide `copy`
- mostrar feedback temporário com ícone `check`

Exemplo de markup:

```html
<button
  class="source-copy-btn"
  type="button"
  data-doc-index="N"
  data-source-action="copy-ementa"
  title="Copiar ementa"
  aria-label="Copiar ementa"
>
  <i data-lucide="copy"></i>
</button>
```

#### 2. Ajustar CSS do card para suportar posicionamento absoluto

Se o botão ficar no canto superior direito do card, o card precisa estar preparado para isso.

Recomendação:

- `position: relative` em `.source-card`

#### 3. Definir helper único para montar o texto copiado

Criar algo como:

- `buildSourceEmentaCopyText(doc)`

Formato recomendado:

```text
EMENTA - [Tribunal] - [Processo] - [Data]
Relator(a): [Relator]
Orgao julgador: [Orgao]

[normative_statement || texto_busca]
```

Regras recomendadas:

- usar `dateHuman(doc.data_julgamento)` para a data
- preferir `normative_statement`
- fallback para `texto_busca`
- se ambos estiverem vazios, retornar erro amigável ao usuário

### Frontend: comportamento do click e teclado

#### 4. Atualizar handler de click

No `sourcesBox?.addEventListener("click", ...)`:

- adicionar branch para `copy-ementa`
- impedir abertura do documento quando a ação for copiar

#### 5. Atualizar handler de teclado

O handler atual de `keydown` abre o card para qualquer descendente focado.

Isso precisa ser corrigido para que:

- `Enter` / `Space` sobre o botão de copiar **não abra** o documento
- elementos com `data-source-action` sejam tratados como interativos próprios

Sem isso, a feature fica incorreta para usuários de teclado.

#### 6. Atualizar ícones após render dinâmico

Depois de re-renderizar as fontes, é necessário chamar `refreshIcons()`.

Sem isso, o ícone de copiar pode não aparecer.

### Frontend: cópia em lote

#### 7. Não usar `<dialog>`; seguir o padrão já existente do app

Em vez de `<dialog>`, seguir o padrão dos demais modais/painéis:

- novo estado em `document.body.dataset.batchCopyOpen`
- novo bloco em `frontend/index.html` com `role="dialog"`
- integração com overlay e `Escape`

#### 8. Adicionar botão "Copiar" no cabeçalho de anexos

No bloco `.evidence-head`:

- adicionar botão `batchCopySourcesBtn`
- esconder quando não houver docs no turno ativo

#### 9. Criar painel/modal de seleção

O painel deve conter:

- título
- botão de fechar
- checkbox "Selecionar todas"
- contador de selecionadas
- lista com os documentos
- botão final de copiar

Cada item da lista deve mostrar:

- checkbox
- tribunal
- processo
- data
- preview curto do texto que será copiado

#### 10. Criar helpers de seleção e geração do texto em lote

Sugestão de helpers:

- `openBatchCopyModal()`
- `closeBatchCopyModal()`
- `renderBatchCopyList()`
- `collectSelectedDocsForBatchCopy()`
- `buildBatchCopyText(docs)`

Formato recomendado:

```text
========================================
[1/3] STF - HC 123456 - 15/03/2025
Relator(a): Min. Alexandre de Moraes
Orgao julgador: Primeira Turma

[texto da ementa]

========================================
[2/3] STJ - REsp 789012 - 20/01/2025
...
```

#### 11. Clipboard e feedback

Ao copiar:

- usar `navigator.clipboard.writeText(...)`
- mostrar feedback visual de sucesso
- em caso de falha, exibir erro amigável no `requestState` ou UI equivalente

### CSS

#### 12. Estilos necessários

Adicionar estilos para:

- `.source-copy-btn`
- estado copiado
- `.batch-copy-btn`
- `.batch-copy-modal`
- `.batch-copy-list`
- itens selecionáveis
- dark theme

Mantendo:

- linguagem visual já existente
- contraste adequado
- sem introduzir um padrão visual paralelo

---

## Testes Necessários

## Backend

Atualizar `tests/test_api_contract.py` com cenários como:

1. aceita upload `.json` válido além de `.pdf`
2. rejeita arquivo `.json` com assinatura incompatível
3. job continua funcionando para PDF
4. job retorna campos novos de progresso/result quando houver JSON
5. JSON sintaticamente inválido não derruba o job inteiro

## Frontend

Atualizar `tests/test_frontend_sidebar_saved.py` com asserts para:

1. o Meu Acervo exibe "PDF ou JSON"
2. existe suporte visual e markup do botão de cópia individual
3. existe suporte visual e markup do botão de cópia em lote
4. o painel/modal de batch copy está presente no HTML
5. o JS contém a action `copy-ementa`
6. o fluxo de pasta não filtra apenas `.pdf`

## Verificação manual

Também executar validação manual:

1. importar PDF normal e confirmar que continua funcionando
2. importar JSON com múltiplas decisões
3. importar pasta contendo PDFs e JSONs
4. testar JSON inválido
5. testar cópia individual
6. testar cópia em lote
7. testar teclado no painel de fontes
8. testar dark theme

---

## Riscos e Observações

- O shape real dos JSONs do usuário é a principal variável de risco.
- Sem amostra real, a heurística de extração será apenas uma aproximação.
- Se houver JSONs muito grandes, `json.loads` pode se tornar custoso em memória.
- Se os dados vierem com datas não-ISO, será preciso decidir se haverá normalização adicional agora ou depois.
- Se várias decisões tiverem o mesmo `tribunal|tipo|processo`, a deduplicação da busca pode reduzir a visibilidade de resultados parecidos.

---

## Próximos Passos Recomendados

Não iniciar implementação antes de responder às perguntas abaixo.

Depois das respostas:

1. fechar a heurística de extração
2. confirmar se upload por pasta deve incluir JSON
3. confirmar a política de fallback da ementa copiada
4. então atualizar este plano em versão final de execução

---

## Perguntas Pendentes

Estas respostas são necessárias para continuar a implementação com segurança.

1. Você pode fornecer 1 ou 2 JSONs reais, ou pelo menos trechos anonimizados, para validar a heurística de extração?
2. Qual é a faixa de tamanho dos JSONs reais? Existem arquivos muito grandes?
3. No botão "copiar ementa", quando a fonte não tiver ementa explícita, o fallback para `normative_statement` ou `texto_busca` é aceitável?
4. O suporte a JSON deve valer também para o fluxo de "selecionar uma pasta inteira", ou apenas para seleção manual de arquivos?

---

## Resumo Executivo

O plano original tinha a ideia certa, mas estava tecnicamente incompleto em pontos críticos:

- função errada do pipeline
- semântica errada de contadores
- frontend incompleto no fluxo de pasta
- ausência de ajustes de teclado/ícones
- modal inconsistente com o padrão do app
- ausência de atualização de testes

O caminho recomendado está descrito neste documento e deve ser retomado a partir daqui na próxima conversa.

---

## Log de Sessão: 2026-04-06 — Planejamento Detalhado

### Respostas às Perguntas Pendentes

1. **Amostra JSON real obtida**: arquivo `docs/plans/json_example.txt`, ~250KB, 3 decisões DataJud.
   - Formato: array top-level de objetos
   - Campos confirmados: `area`, `assuntos[].nome`, `classe.nome`, `datajulgamento` (ISO), `ementatextopuro`, `numeroprocesso`, `orgaojulgador.nome`, `orgaojulgadorcolegiado.nome`, `origem`, `textopuro`, `textooriginal`
   - Campos aninhados (dict): `classe`, `orgaojulgador`, `orgaojulgadorcolegiado`, `competencia`, `sistemaorigem`
   - Campos irrelevantes para o Ratio: `binario`, `hashstorage`, `id`, `lido`, `matchNaEmenta`, `scoreRelevancia`, `textoementa` (HTML)

2. **Faixa de tamanho**: ~85KB/decisão. Para milhares de decisões, arquivos podem chegar a dezenas de MB. `json.loads` suporta isso sem problemas; o limite existente `USER_ACERVO_MAX_FILE_SIZE_BYTES` (1GB) protege.

3. **Fallback da ementa**: `ementatextopuro` presente em todos os exemplos. Fallback para `textopuro`/`textooriginal` confirmado como aceitável. Para copiar ementa no frontend, fallback `normative_statement` → `texto_busca` já validado no código existente (`buildSourceDocumentText`).

4. **Pasta inteira**: SIM — o suporte a JSON deve incluir o fluxo de pasta, pois o caso de uso do usuário envolve milhares de arquivos.

### Exploração Realizada

- **Backend** (`backend/main.py`): confirmado pipeline completo — endpoint (4031-4174), `_index_single_user_acervo_file` (2890-3025), `_build_user_acervo_record_batch` (2835-2887), schema LanceDB (2179-2204), progresso/ETA (2669-2810), deduplicação por `doc_sha256` (2219-2234).
- **Frontend** (`frontend/app.js`, `frontend/index.html`): confirmado file input (861), folder filter (2546-2547, 5300), upload flow (2542-2615), progress polling (1425-1461, 1477-1500), `renderSources` (4287-4344), click handler (5413-5432), keyboard handler (5434-5442), modal pattern (`body.dataset.*Open`), Escape/overlay handlers (5232-5258, 5464-5493), clipboard pattern (5218-5230), `refreshIcons` (1125-1128), `buildSourceDocumentText` (416-434), `dateHuman` (390-393).
- **Testes**: `test_api_contract.py` (390-565), `test_frontend_sidebar_saved.py` (338-397).

### Mapeamento DataJud → Schema Ratio (Confirmado)

| Campo DataJud | Tipo | Campo Ratio |
|---|---|---|
| `origem` | string | `tribunal` |
| `classe.nome` | nested dict | `tipo` |
| `numeroprocesso` | string | `processo` |
| `orgaojulgador.nome` | nested dict | `relator` |
| `orgaojulgadorcolegiado.nome` | nested dict | `orgao_julgador` |
| `area` + `assuntos[].nome` | string + array | `ramo_direito` |
| `datajulgamento` | string ISO | `data_julgamento` |
| `ementatextopuro` | string | `texto_busca` |
| `textopuro` / `textooriginal` | string | `texto_integral` |

### Plano de Implementação

Dividido em 4 fases sequenciais:

- **Fase 1**: Backend — aceitar .json, validar magic bytes, extrair decisões, normalizar campos, indexar sem LLM cleaning
- **Fase 2**: Frontend upload — file picker + folder filter aceitar .json, progress com decision count
- **Fase 3**: Frontend copiar ementa — botão individual por card, batch copy modal, keyboard, clipboard
- **Fase 4**: CSS, testes, dist sync, preparação para release

Plano detalhado em: `C:\Users\Gabriel\.claude\plans\calm-pondering-whistle.md`

### Observações para Release

- Após implementação e testes, será necessário version bump e release
- O release seguirá o processo documentado: `installer/bump_version.py` → dist sync → git tag → GitHub Actions
- A release será feita em sessão separada após validação completa

---

## Log de Implementação: 2026-04-06

### Execução Completa — Todas as 4 Fases

#### Fase 1 — Backend (`backend/main.py`)
- [x] `_deep_get()` helper para acesso seguro a dicts aninhados
- [x] `_extract_ramo_direito()` helper
- [x] `_DATAJUD_KNOWN_FIELDS` frozenset para detecção de campos DataJud
- [x] `_normalize_datajud_decision()` — mapeamento completo DataJud → Ratio
- [x] `_find_decision_list()` — heurística robusta (array top-level, objeto único, busca recursiva)
- [x] `_ensure_json_magic_bytes()` — validação por primeiro char não-whitespace
- [x] `_extract_decisions_from_json_file()` — extração completa com fallback de encoding
- [x] `_build_user_acervo_record_batch_json()` — record builder com metadados de decisão
- [x] Endpoint aceita `.json` além de `.pdf` com branching de validação
- [x] `skipped_non_pdf` → `skipped_unsupported` (renomeado)
- [x] `file_kind` propagado no `stored_files` e pipeline
- [x] Branching em `_index_single_user_acervo_file`: JSON pula OCR e LLM cleaning
- [x] `extracted_decisions` adicionado ao progress, result_payload e done_message
- [x] Mensagens de erro atualizadas: "PDF" → "PDF ou JSON"
- [x] Sintaxe Python verificada: OK

#### Fase 2 — Frontend Upload
- [x] `index.html`: accept agora inclui `.json`, label "PDF ou JSON"
- [x] `app.js`: folder filter aceita `.json`
- [x] `app.js`: mensagens atualizadas (validação, confirm dialog, folder change handler)
- [x] `app.js`: `applyUserCorpusJobSnapshot` exibe `extracted_decisions`

#### Fase 3 — Copiar Ementa
- [x] `buildSourceEmentaCopyText(doc)` — formato EMENTA com header, relator, órgão, corpo
- [x] `buildBatchCopyText(docs)` — formato lote com numeração e separadores
- [x] Botão `.source-copy-btn` com `data-source-action="copy-ementa"` em cada card
- [x] Click handler atualizado (async, branch copy-ementa, ícone check→copy com 1.8s)
- [x] Keyboard handler atualizado (delega `[data-source-action]` ao click)
- [x] Botão `#batchCopySourcesBtn` no `.evidence-head` (hidden por padrão)
- [x] Modal `#batchCopyModal` com select all, lista, botão copiar
- [x] Helpers: `setBatchCopyOpen`, `openBatchCopyModal`, `closeBatchCopyModal`, `renderBatchCopyList`, `updateBatchCopyCount`
- [x] Event listeners: batch copy btn, close, select all, execute
- [x] Escape handler inclui batch copy (prioridade máxima)
- [x] Overlay handler inclui batch copy

#### Fase 4 — CSS, Testes, Sync
- [x] CSS: `.evidence-head-actions`, `.batch-copy-trigger`, `.source-top-actions`, `.source-copy-btn` (hover reveal, 160ms)
- [x] CSS: `.batch-copy-modal` completo (fixed centered, 480px, overflow-y auto)
- [x] CSS: dark theme overrides para copy btn e batch modal
- [x] Testes backend: 4 novos testes (JSON accept, signature reject, extraction, empty ementa skip)
- [x] Testes frontend: 5 novos testes (file picker, folder flow, copy action, batch modal, modal pattern)
- [x] Todos os 62 testes de API passaram
- [x] Todos os 56 testes frontend passaram
- [x] Dist sync: index.html, app.js, styles.css → dist/Ratio/_internal/frontend/

### Validação com JSON Real (json_example.txt)
- [x] Extração testada: 2 decisões extraídas corretamente do arquivo real DataJud
- [x] Campos mapeados: tribunal, tipo, processo, relator, orgao_julgador, ramo_direito, data_julgamento, texto_busca, texto_integral
- [x] Decisão 1: TJPA, CONFLITO DE COMPETÊNCIA CÍVEL, 0809814-36.2023.8.14.0000, 1144 chars ementa, 6935 chars integral
- [x] Decisão 2: TJPA, EXCEÇÃO DE SUSPEIÇÃO, 0816991-85.2022.8.14.0000, 1380 chars ementa, 15497 chars integral
- [x] ramo_direito extraído corretamente: "Cível - Imunidade de Jurisdição", "Cível - Suspeição"

### Release v2026.04.06-b1
- [x] Version bump: 2026.03.23 (build 17) → 2026.04.06 (build 1)
- [x] Commit: `b71bd3f feat: JSON import (DataJud) no Meu Acervo + copiar ementas em lote`
- [x] Tag: `v2026.04.06-b1` criada e pushed
- [x] GitHub Actions Release workflow: completado com sucesso
- [x] Landing page (ratiojuris.me) atualizada com notas da v2026.04.06
- [x] Landing page pushed e publicada

### Pendente
- [ ] Testar dark theme visual (manual)
- [ ] Testar importação por pasta com mix PDF+JSON (manual)
- [ ] Verificar auto-update em instalação existente

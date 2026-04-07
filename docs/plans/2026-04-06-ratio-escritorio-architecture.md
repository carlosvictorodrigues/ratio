# Ratio Escritorio â€” Documento Final de Arquitetura

**Versao:** 1.1  
**Data:** 2026-04-06  
**Status:** Aprovado para implementacao (com ressalvas â€” ver Apendice B)  
**Revisado por:** Claude Opus 4.6, Gemini 3.1 Pro Preview, Gemini 2.5 Flash, GPT-5.4

---

## 1. Visao Geral

O **Ratio Escritorio** e a evolucao do Ratio â€” hoje um sistema de pesquisa jurisprudencial com RAG hibrido â€” para um escritorio juridico multi-agente completo. O objetivo e permitir que um advogado descreva um caso em linguagem natural e obtenha, ao final de um pipeline assistido por IA, uma peticao ou contestacao robusta, fundamentada em jurisprudencia real e legislacao vigente, testada adversarialmente.

O sistema opera como uma **equipe de escritorio virtual**: agentes especializados pesquisam, redigem e atacam a peca, enquanto o advogado supervisiona, edita e decide em pontos-chave.

### Status de Implementacao (regua em 2026-04-06)

**Ja implementado no branch `codex/ratio-escritorio-foundation`:**

- bounded context novo em `backend/escritorio/`, separado do backend monolitico atual;
- schemas Pydantic para state, intake, rodadas adversariais, findings e gates;
- store SQLite com `cases`, `case_snapshots` e `case_events`;
- migracao para `CaseStore` por caso + `CaseIndex` global leve;
- `ratio_tools.py` com retry, paralelismo assinc e recency bias;
- wrapper read-only para LanceDB com registry reutilizavel;
- wrappers LangChain/LangGraph em `tools/langchain_tools.py`;
- isolamento de texto externo contra prompt injection;
- workflow minimo LangGraph, IntakeGraph real, DraftingGraph foundation, AdversarialGraph foundation, orquestrador sequencial e router FastAPI do Escritorio;
- ciclo de caso: criar caso, listar caso, intake, Gate 1 e Gate 2;
- loop adversarial backend-first: registrar critica, anti-sycophancy, dismiss humano, revisao por secao, guard de retries, `contraparte_node` e `redator_revisao_node` com caminho real padrao e payload de revisao com `preserve_human_anchors=True`;
- `DraftingGraph` foundation com curadoria deterministica;
- verificador expandido com canonicalizacao, matching em niveis e integracao ao registry;
- suite dedicada de testes do Escritorio integrada ao contrato atual do backend.

**Ainda nao implementado:**

- pesquisa juridica real por tese no fluxo do Escritorio (foundation com decomposicao explicita e agregacao por tese implementadas; loop tool-driven/refinamento ainda pendente);
- redacao automatica real por secoes com LLM (foundation com prompt builder e node real implementados; refinamento de output ainda pendente);
- verificador deterministico em 5 camadas (foundation conectada ao fluxo por secao; evidence pack automatico por secao ja existe e alimenta a validacao, mas ainda precisa amadurecer semanticamente);
- formatacao DOCX (foundation do formatador e integracao default ao graph implementadas; formatacao juridica principal — alinhamento, espacamento, paginação, enderecamento e citacao longa — ja aplicada; acabamento final ainda pendente);
- importacao de parecer externo;
- frontend React do Escritorio;
- integracao completa ponta a ponta do pipeline previsto nas Ondas 1, 2 e 4.

### Timeline de Progresso

| Data | Marco | Status | Evidencia |
|---|---|---|---|
| 2026-04-06 | Fundacao backend-first do Escritorio | IMPLEMENTADO | pacote `backend/escritorio/`, store SQLite, `ratio_tools.py`, `lancedb_access.py`, workflow minimo, router `/api/escritorio`, testes |
| 2026-04-06 | Intake e ciclo do caso | IMPLEMENTADO | criacao/listagem de casos, snapshots, intake heuristico, checklist minimo, Gate 1/Gate 2, testes de ciclo |
| 2026-04-06 | Loop adversarial backend-first | IMPLEMENTADO | critica, anti-sycophancy, `finding_id`, dismiss humano, revisao por secao, endpoints adversariais, testes ponta a ponta |
| 2026-04-06 | Migracao para persistencia por caso | IMPLEMENTADO | `CaseStore` + `CaseIndex`, API ajustada para root por caso, testes de store/API/ciclo |
| 2026-04-06 | Tipagem de grafo + wrappers LangChain | IMPLEMENTADO | `StateGraph(RatioEscritorioState)` + `tools/langchain_tools.py` |
| 2026-04-06 | Suite de verificacao do branch | VERIFICADO | `py -m pytest -q tests/escritorio tests/test_api_contract.py` e `py -m pytest` limpos no worktree `codex/ratio-escritorio-foundation` (suite atual: 259 passed) |
| 2026-04-06 | Verificador deterministico - foundation | PARCIAL | `backend/escritorio/verifier.py` com normalizacao, extracao expandida, canonicalizacao e matching inicial, com testes |
| 2026-04-06 | IntakeGraph real - foundation | PARCIAL | `backend/escritorio/intake_llm.py` + `backend/escritorio/graph/intake_graph.py` com gate1 interrupt e fallback heuristico |
| 2026-04-06 | DraftingGraph - foundation | PARCIAL | `backend/escritorio/graph/drafting_graph.py` com gate2 interrupt, pesquisa agregada por tese, decomposicao explicita de teses, redator real via `gemini-3.1-pro-preview` e builder tipado |
| 2026-04-06 | Formatador DOCX - foundation | PARCIAL | ackend/escritorio/formatter.py com margens, headings, secoes e integracao default ao ormatador_node |
| 2026-04-06 | Pesquisa por tese, redacao real, verificador e DOCX | PENDENTE | proximas frentes de implementacao |

### 1.1 Principios Fundamentais

- **Generalidade total.** O sistema nao e hardcoded para nenhum tipo de processo. A estrutura da peticao, secoes, pedidos e perguntas de intake sao emergentes do caso concreto.
- **Separacao epistemica.** Agentes diferentes existem porque tem contexto, objetivo, ferramentas e saida diferentes â€” nao por role-playing.
- **Verificacao deterministica.** Validacao de citacoes e coerencia nao dependem de LLM. Sao feitas por ferramentas programaticas.
- **Human-in-the-loop.** O advogado aprova em gates obrigatorios. O sistema nunca prossegue sem aprovacao humana nos pontos criticos.
- **Falhar fechado.** Se o sistema nao tem confianca em uma citacao ou dado, marca como `[NAO VERIFICADO]` em vez de usar dado ruim.

---

## 2. O que o Ratio Ja Resolve

O Ratio atual e o motor de pesquisa e verificacao do escritorio. Nao sera substituido â€” sera exposto como **Tool Layer** para os agentes.

| Componente | Tecnologia | Funcao |
|---|---|---|
| Frontend | HTML/JS statico | Interface de pesquisa |
| Backend | FastAPI (Python) | API REST `/api/query` |
| Motor de Retrieval | `rag/query.py` (~3955 linhas) | Busca hibrida + rerank + geracao |
| Banco Vetorial | LanceDB | Embeddings locais |
| Fontes Oficiais | STF, STJ, TJSP | Jurisprudencia indexada |
| Meu Acervo | LanceDB (separado) | Base privada do usuario |
| Multi-provider | Gemini + Claude | Geracao de respostas |

**Funcao `run_query()`** (`rag/query.py:3760`): aceita query, filtros (tribunais, tipos, ramos, datas, sources), persona, e retorna resposta gerada + documentos rankeados com metadados ricos (processo, tribunal, data_julgamento, relator, orgao_julgador, scores).

---

## 3. Arquitetura do Pipeline

### 3.1 Fluxo Principal

```
ONDA 0 â€” INTAKE (chat dinamico)
  |-- Area do direito (dropdown / deteccao automatica)
  |-- Tipo de peca (peticao inicial / contestacao)
  |-- Texto livre: "descreva o caso"
  |-- Agente Intake faz perguntas dinamicas
  |-- Pesquisador da feedback -> Intake refina perguntas
  |-- Checklist minimo antes de prosseguir
  |-- Saida: dossie narrativo estruturado
  |
  == GATE 1: "Entendemos o problema?" (pausa humana) ==
  |
ONDA 1 â€” QUEBRA EM TESES + PESQUISA POR TESE
  |-- Estrategista decompoe caso em teses juridicas objetivas
  |-- Pesquisador busca POR TESE (nao busca generica):
  |     |-- Jurisprudencia favoravel (Ratio via run_query)
  |     |-- Jurisprudencia contraria (Ratio via run_query)
  |     |-- Legislacao (Gemini Search + Planalto pre-indexado)
  |-- Curadoria: seleciona pro, contra, fragilidades por tese
  |-- Saida: dossie por tese com evidencias rankeadas
  |
  == GATE 2: "Base suficiente para agir?" (pausa humana) ==
  |
ONDA 2 â€” REDACAO
  |-- Redator (Gemini Pro) produz peca por secoes
  |-- peca_sections = Dict[str, str] (secoes dinamicas por tipo)
  |-- Cada paragrafo com proveniencia (fonte linkada)
  |-- Streaming em tempo real (WebSocket/SSE)
  |-- Peticao v1 apresentada ao usuario
  |
ONDA 3 â€” LOOP ADVERSARIAL (N rodadas, usuario controla)
  |-- Contraparte (Claude) ataca:
  |     |-- Busca jurisprudencia contraria (Ratio)
  |     |-- Busca leis que enfraquecem teses
  |     |-- Aponta falhas processuais e materiais
  |     |-- Saida 1: analise tipo contestacao (texto estruturado)
  |     |-- Saida 2: JSON Pydantic estruturado
  |           { falhas_processuais, args_fracos, jurisp_faltante, score_risco }
  |-- Anti-sycophancy: se score=0 e arrays vazios -> rejeicao interna, forca re-execucao
  |-- Usuario ve criticas no dashboard
  |-- Usuario edita por secao (editor central)
  |-- Botoes rapidos: aprofundar | enxugar | trocar tese | inserir precedente | corrigir tom
  |-- Campo livre para apontamentos
  |-- Sistema alerta dependencias entre secoes (fatos -> fundamentos -> pedidos)
  |-- Redator revisa SO secoes criticadas/editadas
  |-- Reflection pattern: Redator reflete se critica revela falha fundamental na logica
  |-- [+ Rodada] ou [Finalizar]
  |
ONDA 4 â€” VERIFICACAO + ENTREGA
  |-- Verificacao de citacoes em camadas:
  |     |-- Camada 1: Normalizacao (acentos, espacos, aliases)
  |     |-- Camada 2: Extracao hibrida (regex + parser + NER leve)
  |     |-- Camada 3: Resolucao para identificador canonico
  |     |-- Camada 4: Match em niveis (exact / strong / weak / unverified)
  |     |-- Camada 5: Validacao de proveniencia (citacao esta no evidence pack da secao?)
  |-- Placeholder para citacoes nao verificadas: [VERIFICAR - Art. X, Lei Y]
  |-- Formatacao DOCX (python-docx + template)
  |-- Custo total exibido
  |-- Download pacote final
```

### 3.2 Gates Humanos

O pipeline tem **2 gates obrigatorios** onde o sistema pausa e espera aprovacao:

| Gate | Momento | Pergunta | Consequencia de rejeicao |
|---|---|---|---|
| Gate 1 | Apos Intake | "Entendemos o problema?" | Volta pro intake, mais perguntas |
| Gate 2 | Apos Pesquisa | "Base suficiente para agir?" | Volta pra pesquisa, busca mais |

Alem dos gates, o usuario pode interromper/editar a qualquer momento no loop adversarial.

### 3.3 Contestacao (polaridade invertida)

Para contestacao, o mesmo pipeline opera com inversao:
- **Input**: peticao da outra parte (PDF/texto colado pelo advogado)
- **Pesquisador**: busca jurisprudencia para rebater os argumentos
- **Redator**: produz a contestacao
- **Contraparte**: simula o autor tentando reforcar a inicial

Arquiteturalmente e o mesmo grafo com parametros diferentes.

---

## 4. Agentes â€” Definicao e Delineamento

O MVP opera com **6 componentes**: 4 agentes LLM + 2 modulos deterministicos.

No MVP, o papel de "Estrategista" (decompor caso em teses) e absorvido pelo Pesquisador. Isso reduz a complexidade do grafo sem perder funcionalidade. O Estrategista se torna agente separado em versao futura, quando houver um gate de aprovacao do roteiro de teses.

### 4.1 Mapa de Agentes (MVP â€” 6 componentes)

| # | Agente | Tipo | Modelo | Missao | Ferramentas | Saida |
|---|---|---|---|---|---|---|
| 1 | **Intake** | LLM | Gemini Flash | Entrevistar o advogado, fazer perguntas dinamicas ate cobrir todos os fatos, montar dossie estruturado | Chat (conversa com usuario) | Dossie narrativo estruturado |
| 2 | **Pesquisador** | LLM | Gemini Flash | Decompor caso em teses juridicas + buscar jurisprudencia e legislacao por tese (favoravel e contraria) | `ratio_search()`, `legislation_search()` | Dossie por tese com evidencias rankeadas |
| 3 | **Redator** | LLM | Gemini Pro | Redigir a peca por secoes, com proveniencia em cada paragrafo. Revisar apenas secoes afetadas em rodadas subsequentes | `format_section()`, dossie de pesquisa | `peca_sections: Dict[str, str]` |
| 4 | **Contraparte** | LLM | Claude (ou Gemini Flash se so houver 1 chave) | Atacar a peca adversarialmente: encontrar falhas processuais, argumentos fracos, jurisprudencia faltante. Buscar jurisprudencia contraria com lastro real | `ratio_search()`, `legislation_search()` | JSON `CriticaContraparte` + analise em texto |
| 5 | **Verificador** | Deterministico | Sem LLM | Conferir cada citacao de lei, sumula e julgado contra a base real. Match deterministico, sem margem para alucinacao | `verify_citation()`, acesso direto LanceDB | Relatorio binario por citacao |
| 6 | **Formatador** | Deterministico | Sem LLM | Gerar documento .docx nos padroes forenses brasileiros | `python-docx`, template de formatacao | Arquivo .docx pronto para protocolar |

### 4.2 Delineamento Detalhado por Agente

#### Agente 1 â€” Intake

| Atributo | Valor |
|---|---|
| **Modelo** | Gemini Flash (rapido, custo baixo â€” o intake precisa de agilidade, nao de raciocinio profundo) |
| **Temperature** | 0.4 (conversacional mas focado) |
| **Prompt de sistema** | Advogado assistente. Objetivo: coletar todos os fatos do caso via entrevista. Fazer perguntas especificas, nao genericas. Nao aceitar respostas vagas â€” pedir detalhes. Ao final, consolidar em dossie padrao. |
| **Informacoes que recebe** | Texto livre do usuario + historico de perguntas/respostas |
| **Informacoes que NAO recebe** | Nenhum resultado de pesquisa, nenhuma petiÃ§Ã£o â€” ele so ve fatos |
| **Ferramentas** | Nenhuma (apenas chat com usuario) |
| **Saida** | Dossie estruturado: area, tipo de peca, partes, fatos confirmados, documentos disponiveis |
| **Criterio de parada** | Checklist minimo preenchido (partes identificadas, fatos principais cobertos, documentos listados) |

#### Agente 2 â€” Pesquisador

| Atributo | Valor |
|---|---|
| **Modelo** | Gemini Flash (muitas chamadas de tool â€” custo importa) |
| **Temperature** | 0.3 (preciso nas queries) |
| **Prompt de sistema** | Pesquisador juridico senior. Objetivo: (1) Decompor o caso em teses juridicas objetivas. (2) Para cada tese, buscar jurisprudencia favoravel E contraria. (3) Mapear legislacao aplicavel. (4) Identificar lacunas. Nunca inventar fonte â€” usar apenas resultados reais das ferramentas. |
| **Informacoes que recebe** | Dossie do Intake |
| **Informacoes que NAO recebe** | Nenhum rascunho de peticao â€” ele nao sabe como a peca sera escrita |
| **Ferramentas** | `ratio_search()`, `legislation_search()` |
| **Saida** | Lista de teses + para cada: jurisprudencia favoravel, contraria, legislacao, forca estimada, lacunas |
| **Criterio de parada** | Todas as teses cobertas com pelo menos 1 resultado favoravel |

#### Agente 3 â€” Redator

| Atributo | Valor |
|---|---|
| **Modelo** | Gemini Pro (raciocinio profundo para argumentacao juridica) |
| **Temperature** | 0.2 (preciso, formal, sem criatividade excessiva) |
| **Prompt de sistema** | Advogado redator especialista. Redigir peca processual por secoes. Cada afirmacao deve citar a fonte do dossie de pesquisa. Se nao houver fonte para uma afirmacao, nao incluir. Linguagem tecnica, clara, sem prolixidade. Em rodadas subsequentes, revisar APENAS secoes criticadas/editadas, nao reescrever tudo. Refletir se critica da Contraparte revela falha fundamental na logica antes de corrigir pontualmente. |
| **Informacoes que recebe** | Dossie do Intake + dossie de pesquisa + criticas da Contraparte (se houver) + edicoes do usuario (se houver) |
| **Informacoes que NAO recebe** | Pesquisa contraria bruta â€” ele recebe a curadoria, nao os resultados crus |
| **Ferramentas** | `format_section()` (helper de formatacao) |
| **Saida** | `peca_sections: Dict[str, str]` â€” secoes dinamicas por tipo de peca |
| **Criterio de parada** | Todas as secoes geradas com proveniencia |

#### Agente 4 â€” Contraparte

| Atributo | Valor |
|---|---|
| **Modelo** | Claude (diversidade real de modelo). Fallback: Gemini Flash com temperature 0.7 se usuario so tem chave Gemini |
| **Temperature** | 0.5 (exploratoria â€” precisa encontrar falhas, nao confirmar acertos) |
| **Prompt de sistema** | Advogado senior implacavel da parte contraria. Objetivo: destruir esta peticao. Encontrar toda falha processual, argumento fraco, jurisprudencia faltante, inconsistencia logica. NAO oferecer sugestoes construtivas. Apenas atacar. Buscar jurisprudencia que sustente cada contra-argumento. Uma resposta que nao encontra falhas significativas e considerada fracasso. |
| **Informacoes que recebe** | APENAS a peticao finalizada (current_draft) |
| **Informacoes que NAO recebe** | Dossie do Intake, dossie de pesquisa, feedback do usuario â€” ele so ve a peca como a parte contraria veria |
| **Ferramentas** | `ratio_search()`, `legislation_search()` (pesquisa independente, nao reusa pesquisa anterior) |
| **Saida** | JSON `CriticaContraparte` (Pydantic) + texto de analise tipo contestacao |
| **Criterio de parada** | Preencher obrigatoriamente todos os campos do schema. Se `score_risco=0` e arrays vazios: rejeicao interna, re-execucao automatica |

#### Modulo 5 â€” Verificador (deterministico)

| Atributo | Valor |
|---|---|
| **Tipo** | Codigo Python puro, sem LLM |
| **Entrada** | Peticao finalizada com todas as citacoes |
| **Processo** | Pipeline de 5 camadas (ver secao 8): normalizacao â†’ extracao hibrida â†’ resolucao canonica â†’ match em niveis â†’ validacao de proveniencia |
| **Saida** | Relatorio: para cada citacao, status (confirmada / nao verificada) + texto real se confirmada |
| **Citacoes nao verificadas** | Marcadas como `[VERIFICAR â€” citacao]` na peca. Nunca passa silenciosamente |

#### Modulo 6 â€” Formatador (deterministico)

| Atributo | Valor |
|---|---|
| **Tipo** | Codigo Python puro, sem LLM |
| **Entrada** | `peca_sections` + relatorio de verificacao + metadados do caso |
| **Processo** | `python-docx` com template: Times New Roman 12pt, espacamento 1.5, margens 3cm/2cm, numeracao de secoes, cabecalho com juizo |
| **Saida** | Arquivo `.docx` nos padroes forenses brasileiros |

### 4.3 Assimetria de Informacao â€” O Principio Central

A razao de ter agentes separados nao e role-playing. E **assimetria de informacao**:

| Agente | Ve | Nao ve |
|---|---|---|
| Intake | Fatos crus do usuario | Nada mais (contexto limpo) |
| Pesquisador | Dossie do Intake | Peticao, criticas, edicoes |
| Redator | Dossie + pesquisa + criticas + edicoes | Pesquisa contraria bruta |
| Contraparte | Apenas a peticao final | Dossie, pesquisa, edicoes, intencao do usuario |

O Pesquisador nao sabe como a peca sera escrita â†’ pesquisa sem vies de confirmacao.
A Contraparte nao sabe o que o Pesquisador encontrou de favoravel â†’ critica sem vies de confirmacao.
O Redator nao ve a pesquisa contraria bruta â†’ nao fica "na defensiva" ao redigir.

### 4.4 Diferenciacao por 5 Camadas Arquiteturais

A diversidade entre agentes vem de 5 camadas, nao de personalidade:

1. **Objetivo diferente** (prompt de sistema com restricoes reais)
2. **Informacoes assimetricas** (cada agente ve dados diferentes â€” camada mais poderosa)
3. **Ferramentas diferentes** (tool access controlado por agente)
4. **Modelos diferentes** (Gemini Pro para raciocinio, Flash para operacional, Claude para critica)
5. **Parametros de geracao** (temperature baixa para redacao, mais alta para brainstorming)

### 4.3 Contraparte â€” Anti-Sycophancy

LLMs tendem a concordar (sycophancy). Mecanismos para forcar critica real:

1. **Prompt agressivo**: "Voce e um advogado senior da parte contraria, implacavel. Seu objetivo e destruir esta peticao."
2. **Saida estruturada obrigatoria** (Pydantic schema com campos que forcam preenchimento)
3. **Campo `query_jurisprudencia_contraria`**: forca o agente a formular query e usar o Ratio
4. **Chain of Thought adversarial explicito**: ler peca -> identificar argumentos -> formular antitese -> buscar jurisp -> verificar processuais -> consolidar JSON
5. **Rejeicao interna**: se `score_risco=0` e arrays vazios, re-executa automaticamente
6. **Diferenciacao de modelo**: Claude para Contraparte (melhor raciocinio critico)

### 4.4 Schema Pydantic â€” Criticas da Contraparte

```python
class FalhaCritica(BaseModel):
    secao_afetada: str
    tipo: Literal[
        "processual", "material", "logica",
        "jurisprudencia_fraca", "citacao_incorreta",
        "prova_insuficiente", "prescricao", "ilegitimidade"
    ]
    gravidade: Literal["alta", "media", "baixa"]
    descricao: str = Field(description="Explicacao detalhada do erro")
    argumento_contrario: str = Field(description="Como a contraparte usaria essa falha")
    query_jurisprudencia_contraria: str = Field(
        description="Query para buscar jurisprudencia que suporte o contra-argumento"
    )
    jurisprudencia_encontrada: Optional[List[Dict]] = None

class CriticaContraparte(BaseModel):
    falhas_processuais: List[FalhaCritica]
    argumentos_materiais_fracos: List[FalhaCritica]
    jurisprudencia_faltante: List[str]
    score_de_risco: int = Field(ge=0, le=100, description="0=perfeito, 100=indefensavel")
    analise_contestacao: str = Field(description="Analise em formato de contestacao")
    recomendacao: Literal["aprovar", "revisar", "reestruturar"]
```

---

## 5. LangGraph â€” Como Funciona

### 5.1 Conceito em 30 Segundos

LangGraph e uma biblioteca que modela fluxos de trabalho como **grafos** â€” nos (funcoes) conectados por arestas (transicoes). A diferenca de um pipeline linear e que o LangGraph permite **ciclos**: o fluxo pode voltar para um no anterior. Isso e essencial pro loop adversarial (Contraparte â†’ Redator â†’ Contraparte â†’ ...).

Tudo gira em torno de 3 conceitos:

```
STATE   â€” um objeto Python (Pydantic) que acumula informacao ao longo do fluxo.
            Analogia: pasta fisica que passa de mao em mao no escritorio.
            Cada pessoa (no) abre a pasta, faz seu trabalho, e devolve com
            suas anotacoes adicionadas. A pasta vai engordando.

NODES   â€” funcoes que leem o state, fazem algo, e devolvem o state modificado.
            Cada no e um agente ou modulo deterministico.

EDGES   â€” regras que decidem qual no executa depois (podem ser condicionais).
            A edge "redator_revisao â†’ contraparte" cria o ciclo adversarial.
```

### 5.2 O State â€” Dossie Vivo do Caso

O state e um `RatioEscritorioState` (Pydantic model) que comeca vazio e acumula dados conforme cada no executa. Cada no le so os campos que precisa e escreve so os campos que produz:

```python
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class TeseJuridica(BaseModel):
    id: str
    descricao: str
    tipo: Literal["principal", "subsidiaria"]
    jurisprudencia_favoravel: List[Dict]
    jurisprudencia_contraria: List[Dict]
    legislacao: List[Dict]
    confianca: Literal["alta", "media", "baixa"]

class RodadaAdversarial(BaseModel):
    numero: int
    critica_contraparte: CriticaContraparte
    edicoes_humanas: Optional[Dict[str, str]] = None  # secao -> novo texto
    apontamentos_humanos: Optional[str] = None
    secoes_revisadas: List[str] = Field(default_factory=list)

class RatioEscritorioState(BaseModel):
    # --- Identificacao ---
    caso_id: str
    tipo_peca: Literal["peticao_inicial", "contestacao"]
    area_direito: str = ""

    # --- Intake ---
    fatos_brutos: str = ""
    fatos_estruturados: List[str] = Field(default_factory=list)
    provas_disponiveis: List[str] = Field(default_factory=list)
    provas_recomendadas: List[str] = Field(default_factory=list)
    pontos_atencao: List[str] = Field(default_factory=list)
    documentos_cliente: List[Dict] = Field(default_factory=list)

    # --- Teses ---
    teses: List[TeseJuridica] = Field(default_factory=list)

    # --- Pesquisa ---
    pesquisa_jurisprudencia: List[Dict] = Field(default_factory=list)
    pesquisa_legislacao: List[Dict] = Field(default_factory=list)

    # --- Peca (Sectioned State) ---
    peca_sections: Dict[str, str] = Field(default_factory=dict)
    # Ex: {"preliminares": "...", "dos_fatos": "...", "do_direito": "...", "pedidos": "..."}
    # Secoes sao DINAMICAS â€” determinadas pelo Pesquisador, nao hardcoded

    # --- Proveniencia ---
    proveniencia: Dict[str, List[str]] = Field(default_factory=dict)
    # Ex: {"dos_fatos.p3": ["REsp 1.234.567", "Art. 186 CC"]}

    # --- Loop Adversarial ---
    rodadas: List[RodadaAdversarial] = Field(default_factory=list)
    rodada_atual: int = 0
    critica_atual: Optional[CriticaContraparte] = None

    # --- Controle ---
    gate1_aprovado: bool = False
    gate2_aprovado: bool = False
    usuario_finaliza: bool = False
    status: Literal[
        "intake", "gate1", "pesquisa", "gate2",
        "redacao", "adversarial", "revisao_humana",
        "verificacao", "entrega", "finalizado"
    ] = "intake"

    # --- Custos ---
    token_log: List[Dict] = Field(default_factory=list)
    custo_total_usd: float = 0.0

    # --- Verificacao ---
    verificacoes: List[Dict] = Field(default_factory=list)
```

### 5.3 Os 3 Sub-Grafos

O pipeline e dividido em 3 grafos independentes que se encadeiam. Isso evita um "God Graph" monolitico e facilita debug, teste e manutencao:

```
+====================+     +====================+     +======================+
|   IntakeGraph      | --> |  DraftingGraph     | --> |  AdversarialGraph    |
|                    |     |                    |     |                      |
|  intake            |     |  pesquisador       |     |  contraparte         |
|  classificacao     |     |  curadoria         |     |  anti_sycophancy     |
|  â˜… GATE 1 (pausa)  |     |  â˜… GATE 2 (pausa)  |     |  â˜… PAUSA HUMANA      |
+====================+     |  redator           |     |  redator_revisao â”€â”€â” |
                           +====================+     |  â˜… PAUSA HUMANA    â”‚ |
                                                      |  contraparte  <â”€â”€â”€â”€â”˜ |
                                                      |                      |
                                                      |  verificador         |
                                                      |  formatador          |
                                                      +======================+
```

### 5.4 Sub-Grafo 1: IntakeGraph

```
        +----------------+
        |     START      |
        +-------+--------+
                |
                v
        +----------------+
        |    intake      |  <-- Gemini Flash conversa com o advogado
        |                |      Le: fatos_brutos (input do usuario)
        |                |      Escreve: fatos_estruturados, provas,
        |                |               pontos_atencao
        +-------+--------+
                |
                v   <--- Loop: se falta informacao, volta pro intake
        +----------------+     (edge condicional: checklist completo?)
        | classificacao  |  <-- Classifica area do direito + tipo de peca
        +-------+--------+
                |
                v
        +----------------+
        |    GATE 1      |  <-- interrupt_before: o LangGraph PAUSA aqui
        |                |      Frontend mostra o dossie ao advogado
        | "Entendemos    |      Advogado clica [Aprovar] ou [Voltar]
        |  o problema?"  |      Se aprovar: gate1_aprovado = True
        +-------+--------+      Se voltar: volta pro no intake
                |
                v
           [FIM do IntakeGraph --> dispara DraftingGraph]
```

**Codigo:**

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

def intake_node(state: RatioEscritorioState) -> dict:
    """Agente Intake: conversa com o advogado."""
    resposta = gemini_flash.invoke(prompt_intake, state.fatos_brutos)
    return {
        "fatos_estruturados": resposta.fatos,
        "provas_disponiveis": resposta.provas,
        "status": "gate1"
    }

def classificacao_node(state: RatioEscritorioState) -> dict:
    """Classifica area e tipo de peca."""
    resultado = gemini_flash.invoke(prompt_classificacao, state.fatos_estruturados)
    return {
        "area_direito": resultado.area,
        "tipo_peca": resultado.tipo
    }

def gate1_router(state: RatioEscritorioState) -> str:
    """Edge condicional: advogado aprovou?"""
    if state.gate1_aprovado:
        return "drafting"
    return "intake"

# Montagem do grafo
intake_graph = StateGraph(RatioEscritorioState)
intake_graph.add_node("intake", intake_node)
intake_graph.add_node("classificacao", classificacao_node)
intake_graph.add_node("gate1", lambda s: s)  # no vazio â€” so serve de checkpoint

intake_graph.set_entry_point("intake")
intake_graph.add_edge("intake", "classificacao")
intake_graph.add_edge("classificacao", "gate1")
intake_graph.add_conditional_edges("gate1", gate1_router, {
    "drafting": END,
    "intake": "intake"
})

# Checkpoint no SQLite do caso
checkpointer = SqliteSaver.from_conn_string("casos/caso_047/caso.db")
intake_app = intake_graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["gate1"]   # <-- PAUSA AQUI e espera input humano
)
```

O `interrupt_before=["gate1"]` e o mecanismo central: o LangGraph executa `intake` â†’ `classificacao`, e quando chega no `gate1`, **para**. Devolve o state pro backend via API. O frontend mostra o dossie. Quando o advogado clica "Aprovar", o backend chama `intake_app.invoke(None, config)` e o grafo retoma de onde parou.

### 5.5 Sub-Grafo 2: DraftingGraph

```
        +----------------+
        |     START      |
        +-------+--------+
                |
                v
        +----------------+
        |  pesquisador   |  <-- Gemini Flash
        |                |      Le: fatos_estruturados, area_direito
        | (decomp teses  |      1. Decompoe em teses juridicas
        |  + busca)      |      2. Para cada tese: ratio_search() favoravel
        |                |      3. Para cada tese: ratio_search() contrario
        |                |      4. legislation_search()
        |                |      Escreve: teses[], pesquisa_jurisprudencia[]
        +-------+--------+
                |
                v
        +----------------+
        |   curadoria    |  <-- Ranqueia e seleciona os melhores resultados
        |                |      por tese. Remove duplicatas.
        +-------+--------+
                |
                v
        +----------------+
        |    GATE 2      |  <-- interrupt_before: PAUSA
        |                |      Frontend mostra dossie de pesquisa
        | "Base sufic.   |      Advogado ve teses + docs + lacunas
        |  para agir?"   |      [Aprovar] ou [Buscar Mais]
        +-------+--------+
                |   <--- Se "Buscar Mais": volta pro pesquisador
                v         com instrucao adicional do advogado
        +----------------+
        |    redator     |  <-- Gemini Pro
        |                |      Le: fatos + teses + pesquisa
        |                |      Escreve: peca_sections (Dict[str, str])
        |                |      Cada secao com proveniencia
        +-------+--------+
                |
                v
           [FIM do DraftingGraph --> dispara AdversarialGraph]
```

**Codigo:**

```python
drafting_graph = StateGraph(RatioEscritorioState)

drafting_graph.add_node("pesquisador", pesquisador_node)
drafting_graph.add_node("curadoria", curadoria_node)
drafting_graph.add_node("gate2", lambda s: s)
drafting_graph.add_node("redator", redator_node)

drafting_graph.set_entry_point("pesquisador")
drafting_graph.add_edge("pesquisador", "curadoria")
drafting_graph.add_edge("curadoria", "gate2")

# Gate 2: se advogado quer buscar mais, volta pro pesquisador
drafting_graph.add_conditional_edges("gate2", gate2_router, {
    "redigir": "redator",
    "buscar_mais": "pesquisador"  # <-- CICLO de refinamento
})
drafting_graph.add_edge("redator", END)

drafting_app = drafting_graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["gate2"]
)
```

### 5.6 Sub-Grafo 3: AdversarialGraph (o que tem o ciclo principal)

Este e o grafo mais importante porque contem o **loop adversarial**:

```
        +------------------+
        |      START       |
        +--------+---------+
                 |
                 v
      +--------------------+
      |    contraparte     |  <-- Claude (ou Gemini Flash fallback)
      |                    |      Le: APENAS peca_sections (nao ve pesquisa)
      |                    |      Executa: ratio_search() independente
      |                    |      Escreve: critica_atual (CriticaContraparte)
      +--------+-----------+
               |
               v
      +--------------------+
      |  anti_sycophancy   |  <-- Codigo Python (nao LLM)
      |                    |      Verifica: score_risco > 0?
      |                    |               arrays tem conteudo?
      |                    |      Se tudo vazio --> REJEITA, volta pro
      |                    |      contraparte com temperature + alta
      +--------+-----------+
               |
               v   <---- Se rejeicao: volta pro contraparte (max 2 retries)
      +--------------------+
      |   PAUSA HUMANA     |  <-- interrupt_before: PAUSA
      |                    |      Frontend mostra: peticao + criticas lado a lado
      |                    |      Advogado: edita secoes, faz apontamentos
      |                    |      Escolhe: [+ Rodada] ou [Finalizar]
      |                    |               ou [Importar Parecer Externo]
      +--------+-----------+
               |
               v
      +--------------------+
      |     DECISAO        |  <-- Edge condicional (codigo Python)
      |     (router)       |
      +---+------------+---+
          |            |
     finalizar?   + rodada?
          |            |
          v            v
      +-------+   +--------------------+
      |       |   |  redator_revisao   |  <-- Gemini Pro
      |       |   |                    |      Le: peca_sections + critica_atual
      |       |   |                    |           + edicoes do usuario
      |       |   |                    |      Revisa SO secoes afetadas
      |       |   |                    |      Escreve: peca_sections (atualizado)
      |       |   +--------+-----------+
      |       |            |
      |       |            v
      |       |   +--------------------+
      |       |   |   contraparte      |  <-- VOLTA PRO INICIO DO LOOP
      |       |   +--------------------+
      |       |
      v       |
+--------------------+
|   verificador      |  <-- Codigo Python (deterministico)
|                    |      Confere cada citacao contra a base
|                    |      Escreve: verificacoes[]
+--------+-----------+
         |
         v
+--------------------+
|   formatador       |  <-- Codigo Python (python-docx)
|                    |      Gera o .docx final
+--------+-----------+
         |
         v
        END
```

**Codigo:**

```python
adversarial_graph = StateGraph(RatioEscritorioState)

# Nos
adversarial_graph.add_node("contraparte", contraparte_node)
adversarial_graph.add_node("anti_sycophancy", anti_sycophancy_node)
adversarial_graph.add_node("pausa_humana", lambda s: s)  # checkpoint
adversarial_graph.add_node("redator_revisao", redator_revisao_node)
adversarial_graph.add_node("verificador", verificador_node)
adversarial_graph.add_node("formatador", formatador_node)

# Fluxo
adversarial_graph.set_entry_point("contraparte")
adversarial_graph.add_edge("contraparte", "anti_sycophancy")

# Anti-sycophancy: se critica vazia, volta pro contraparte
adversarial_graph.add_conditional_edges("anti_sycophancy", sycophancy_router, {
    "aceita": "pausa_humana",
    "rejeita": "contraparte"       # <-- CICLO de rejeicao (max 2 retries)
})

# Pausa humana â†’ decisao do advogado
adversarial_graph.add_conditional_edges("pausa_humana", decisao_advogado, {
    "mais_rodada": "redator_revisao",
    "finalizar": "verificador"
})

# Redator revisa â†’ volta pra contraparte â†’ CICLO PRINCIPAL
adversarial_graph.add_edge("redator_revisao", "contraparte")

# Fluxo final
adversarial_graph.add_edge("verificador", "formatador")
adversarial_graph.add_edge("formatador", END)

# Compilar com pausa humana
adversarial_app = adversarial_graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["pausa_humana"]
)
```

A linha `add_edge("redator_revisao", "contraparte")` e o que cria o ciclo. Depois que o Redator revisa, o fluxo volta pra Contraparte, que ataca de novo. Isso se repete ate o advogado clicar "Finalizar".

### 5.7 Como o Frontend Interage com os `interrupt`

O backend FastAPI expoe endpoints que controlam o grafo:

```python
@app.post("/api/escritorio/caso/{caso_id}/start")
async def iniciar_caso(caso_id: str, fatos: str):
    """Inicia o IntakeGraph."""
    state = RatioEscritorioState(caso_id=caso_id, fatos_brutos=fatos)
    result = intake_app.invoke(
        state,
        config={"configurable": {"thread_id": caso_id}}
    )
    # O grafo executou ate o interrupt_before do gate1
    # Retorna o state atual pro frontend exibir
    return result

@app.post("/api/escritorio/caso/{caso_id}/gate/{gate_num}")
async def aprovar_gate(caso_id: str, gate_num: int, aprovado: bool):
    """Advogado aprova ou rejeita um gate."""
    update = (
        {"gate1_aprovado": aprovado} if gate_num == 1
        else {"gate2_aprovado": aprovado}
    )
    # Retoma o grafo de onde parou
    result = intake_app.invoke(
        update,
        config={"configurable": {"thread_id": caso_id}}
    )
    return result

@app.post("/api/escritorio/caso/{caso_id}/rodada")
async def acao_rodada(
    caso_id: str,
    edicoes: Dict[str, str],
    apontamentos: str,
    finalizar: bool
):
    """Advogado fez edicoes e decidiu: + rodada ou finalizar."""
    update = {
        "edicoes_humanas": edicoes,
        "apontamentos_humanos": apontamentos,
        "usuario_finaliza": finalizar,
        "rodada_atual": state.rodada_atual + 1
    }
    # Retoma o AdversarialGraph de onde parou
    result = adversarial_app.invoke(
        update,
        config={"configurable": {"thread_id": caso_id}}
    )
    return result
```

### 5.8 Streaming via SSE

Enquanto cada no executa, o grafo emite eventos via `astream_events`. O frontend recebe em tempo real:

```python
@app.get("/api/escritorio/caso/{caso_id}/stream")
async def stream_caso(caso_id: str):
    """SSE stream â€” frontend recebe eventos em tempo real."""
    async def event_generator():
        async for event in adversarial_app.astream_events(
            None,
            config={"configurable": {"thread_id": caso_id}},
            version="v2"
        ):
            if event["event"] == "on_chat_model_stream":
                # Token da LLM chegou
                yield f"data: {json.dumps({
                    'type': 'token',
                    'agent': event['metadata']['agent'],
                    'content': event['data']['chunk'].content
                })}\n\n"

            elif event["event"] == "on_tool_end":
                # Uma ferramenta terminou (ratio_search, etc.)
                yield f"data: {json.dumps({
                    'type': 'tool_done',
                    'tool': event['name'],
                    'n_results': len(event['data']['output'])
                })}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

O frontend usa `EventSource` do browser:

```javascript
const sse = new EventSource(`/api/escritorio/caso/${casoId}/stream`);
sse.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'token') {
        // Adiciona token ao editor em tempo real
        appendToSection(data.agent, data.content);
    } else if (data.type === 'tool_done') {
        // Atualiza badge: "Pesquisador: 22 resultados encontrados"
        updateAgentStatus(data.tool, data.n_results);
    }
};
```

### 5.9 Checkpoint e Recuperacao

O `SqliteSaver` salva o state completo a cada transicao de no no `caso.db`:

```
No executou â†’ State atualizado â†’ Checkpoint salvo no SQLite
```

Se o app crashar no meio do `contraparte_node` (rodada 2):
1. Advogado reabre o caso
2. Backend carrega o ultimo checkpoint do `caso.db`
3. O state esta no ponto exato antes do `contraparte_node` da rodada 2
4. O grafo retoma dali â€” ondas 0, 1 e rodada 1 nao precisam re-executar
5. O advogado nao perde nada

### 5.10 Dependencias entre Secoes

Quando o usuario edita uma secao, o sistema verifica impacto em outras:

| Se editar... | Alerta impacto em... |
|---|---|
| `dos_fatos` | `do_direito`, `pedidos` |
| `do_direito` | `pedidos`, `preliminares` |
| `pedidos` | `valor_da_causa` |
| `preliminares` | `do_direito` |

O alerta e informativo â€” o usuario decide se quer que o Redator revise as secoes dependentes.

### 5.11 Visao Geral: Fluxo Completo

```
ADVOGADO              LANGGRAPH                         BACKEND/TOOLS
                      |                                 |
descreve caso ------> |  IntakeGraph                    |
                      |    intake_node -----------------> (Gemini Flash)
                      |    classificacao_node -----------> (Gemini Flash)
                      |    * INTERRUPT (gate1) <--------|
<-- ve dossie         |                                 |
aprova -------------> |  DraftingGraph                  |
                      |    pesquisador_node -------------> ratio_search() x N
                      |    curadoria_node               |
                      |    * INTERRUPT (gate2) <--------|
<-- ve pesquisa       |                                 |
aprova -------------> |    redator_node -----------------> (Gemini Pro)
                      |                                 |
                      |  AdversarialGraph               |
                      |  +-> contraparte_node -----------> (Claude) + ratio_search()
                      |  |   anti_sycophancy            |
                      |  |   * INTERRUPT (humano) <-----|
<-- ve criticas       |  |                              |
edita + rodada -----> |  |   redator_revisao ------------> (Gemini Pro)
                      |  +-----------------------------+|  <-- CICLO
                      |                                 |
edita + finaliza ---> |    verificador_node             |  (codigo puro)
                      |    formatador_node              |  (python-docx)
                      |    --> END                      |
<-- baixa DOCX        |                                 |
```

---

## 6. Ratio como Tool Layer

### 6.1 Arquitetura: Agentes com Ferramentas no LangGraph

No LangGraph, agentes com ferramentas seguem o padrao ReAct: o modelo decide se precisa chamar uma ferramenta, executa, recebe o resultado, e decide o proximo passo. Isso e implementado com `bind_tools()` no modelo e `ToolNode` para execucao.

```python
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langchain_google_genai import ChatGoogleGenerativeAI

# O modelo recebe as ferramentas disponiveis via bind_tools()
# Quando o modelo decide usar uma ferramenta, retorna um tool_call
# O ToolNode executa a ferramenta e retorna o resultado como ToolMessage
# O modelo recebe o resultado e decide: chamar outra ferramenta ou responder
```

### 6.2 Modulo `ratio_tools.py` â€” Ferramentas LangChain

Cada ferramenta e decorada com `@tool` do LangChain, que gera automaticamente o schema JSON que o modelo usa para decidir quando e como chama-la:

```python
# ratio_tools.py â€” importacao direta, sem HTTP

from typing import List, Dict, Optional
from langchain_core.tools import tool
from rag.query import run_query, search_lancedb, embed_query

# â”€â”€ Ferramenta 1: Busca de jurisprudencia favoravel â”€â”€

@tool
def buscar_jurisprudencia_favoravel(
    query: str,
    tese: str,
    tribunais: Optional[List[str]] = None,
    limite: int = 10
) -> List[Dict]:
    """Busca acordaos e decisoes favoraveis a uma tese juridica especifica.
    Use esta ferramenta quando precisar encontrar jurisprudencia que SUSTENTE
    um argumento. A query deve descrever a tese que se quer fundamentar.

    Args:
        query: Descricao da situacao fatica ou argumento a fundamentar.
        tese: A tese juridica especifica que se busca sustentar.
        tribunais: Lista de tribunais para filtrar (ex: ["STJ", "STF", "TJSP"]).
        limite: Numero maximo de resultados.

    Returns:
        Lista de documentos com: processo, tribunal, ementa, texto_integral,
        relator, orgao_julgador, data_julgamento, score, inteiro_teor_url.
    """
    # Persona "favoravel" instrui a geracao a destacar aspectos que sustentam a tese
    # Mas os DOCUMENTOS retornados sao os mesmos â€” a persona so afeta a resposta textual
    answer, docs = run_query(
        query=f"{tese}: {query}",
        tribunais=tribunais,
        return_meta=False,
        persona="visao_geral",
        persona_prompt=(
            f"Analise os documentos encontrados sob a otica de quem busca "
            f"sustentar a seguinte tese: '{tese}'. Destaque os trechos "
            f"que mais fortalecem essa posicao."
        ),
    )
    # Converter para schema padrao DocumentoColetado
    return [_doc_to_coletado(d, tese, "favoravel") for d in docs[:limite]]


# â”€â”€ Ferramenta 2: Busca de jurisprudencia contraria â”€â”€

@tool
def buscar_jurisprudencia_contraria(
    query: str,
    tese: str,
    tribunais: Optional[List[str]] = None,
    limite: int = 5
) -> List[Dict]:
    """Busca acordaos e decisoes que ENFRAQUECEM ou CONTRARIAM uma tese juridica.
    Use esta ferramenta quando precisar mapear riscos ou encontrar argumentos
    que a parte contraria poderia usar.

    Args:
        query: Descricao do argumento que se quer atacar/verificar vulnerabilidade.
        tese: A tese juridica que se busca refutar ou encontrar contra-argumentos.
        tribunais: Lista de tribunais para filtrar.
        limite: Numero maximo de resultados.

    Returns:
        Lista de documentos contrarios com mesma estrutura da busca favoravel.
    """
    answer, docs = run_query(
        query=f"jurisprudencia contraria a: {tese}. Situacao: {query}",
        tribunais=tribunais,
        return_meta=False,
        persona="visao_geral",
        persona_prompt=(
            f"Analise os documentos encontrados sob a otica de quem busca "
            f"REFUTAR a seguinte tese: '{tese}'. Destaque precedentes, sumulas "
            f"ou entendimentos que enfraquecem essa posicao."
        ),
    )
    return [_doc_to_coletado(d, tese, "contrario") for d in docs[:limite]]


# â”€â”€ Ferramenta 3: Verificacao de citacao â”€â”€

@tool
def verificar_citacao(referencia: str) -> Dict:
    """Verifica se uma citacao juridica (acordao, sumula, tema) existe na base real.
    NAO usa LLM â€” e verificacao deterministica por busca exata.

    Args:
        referencia: A citacao a verificar (ex: "REsp 1.059.663/MS",
                    "Sumula 548 do STJ", "Tema 952").

    Returns:
        Dict com: existe (bool), nivel_match (exact/strong/weak/unverified),
        texto_real (texto da decisao se encontrada), metadados.
    """
    # Normalizar a referencia (ver secao 8 para pipeline completo)
    normalizada = _normalizar_citacao(referencia)

    # Busca exata no LanceDB por numero de processo
    results = search_lancedb(
        query=normalizada,
        query_vector=embed_query(normalizada),
        top_k=5,
    )

    if not results:
        return {"existe": False, "nivel": "unverified", "referencia": referencia}

    # Verificar match por niveis (ver secao 8.2)
    best_match = _classificar_match(normalizada, results)
    return best_match


# â”€â”€ Ferramenta 4: Busca de legislacao â”€â”€

@tool
def buscar_legislacao(
    termos: str,
    codigo: Optional[str] = None
) -> List[Dict]:
    """Busca artigos de lei, codigos e legislacao. Primeiro busca no cache local
    (codigos pre-indexados do Planalto), depois via Gemini Search para leis esparsas.

    Args:
        termos: Descricao do que se busca (ex: "prazo prescricional dano moral",
                "responsabilidade objetiva prestador servico").
        codigo: Se sabe qual codigo, especifique (ex: "CC", "CPC", "CDC", "CF").

    Returns:
        Lista de artigos com: lei, numero, artigo, texto, url_planalto.
    """
    # Camada 1: Busca no LanceDB (codigos pre-indexados)
    local_results = _buscar_legislacao_local(termos, codigo)
    if local_results:
        return local_results

    # Camada 2: Gemini Search para leis esparsas
    return _buscar_legislacao_gemini(termos)


# â”€â”€ Ferramenta 5: Busca no Meu Acervo â”€â”€

@tool
def buscar_acervo(query: str, limite: int = 5) -> List[Dict]:
    """Busca no acervo privado do usuario (PDFs importados).
    Use quando o caso envolver documentos especificos que o advogado ja indexou.

    Args:
        query: Texto da busca.
        limite: Numero maximo de resultados.

    Returns:
        Lista de documentos do acervo do usuario.
    """
    answer, docs = run_query(
        query=query,
        sources=["user"],
        return_meta=False,
    )
    return docs[:limite]


# â”€â”€ Helper: converter doc do Ratio para schema padrao â”€â”€

def _doc_to_coletado(doc: Dict, tese: str, papel: str) -> Dict:
    """Converte um documento retornado por run_query() para o schema
    DocumentoColetado usado no dossie de pesquisa."""
    return {
        "doc_id": doc.get("doc_id", ""),
        "processo": doc.get("processo", ""),
        "tribunal": doc.get("tribunal", ""),
        "tipo": doc.get("tipo", ""),
        "relator": doc.get("relator", ""),
        "orgao_julgador": doc.get("orgao_julgador", ""),
        "data_julgamento": doc.get("data_julgamento", ""),
        "ementa": doc.get("texto_integral_excerpt", ""),
        "texto_integral_excerpt": doc.get("texto_integral_excerpt", ""),
        "texto_integral_full": doc.get("texto_integral_full", ""),
        "inteiro_teor_url": doc.get("inteiro_teor_url", ""),
        "score_final": doc.get("_final_score", 0.0),
        "score_semantico": doc.get("_semantic_score", 0.0),
        "tese_vinculada": tese,
        "papel": papel,  # "favoravel" ou "contrario"
    }
```

### 6.3 Binding de Ferramentas por Agente

Cada agente recebe APENAS as ferramentas que ele pode usar (controle de acesso):

```python
# Ferramentas por agente â€” controle de acesso explicito
TOOLS_PESQUISADOR = [
    buscar_jurisprudencia_favoravel,
    buscar_jurisprudencia_contraria,
    buscar_legislacao,
    buscar_acervo,
]

TOOLS_CONTRAPARTE = [
    buscar_jurisprudencia_contraria,  # Contraparte so busca CONTRA
    buscar_legislacao,
]

TOOLS_REDATOR = []  # Redator NAO tem ferramentas â€” so escreve com o que recebeu

# No LangGraph, cada agente-no usa ToolNode com suas ferramentas:
pesquisador_tools = ToolNode(TOOLS_PESQUISADOR)
contraparte_tools = ToolNode(TOOLS_CONTRAPARTE)

# O modelo do agente recebe as ferramentas via bind_tools:
modelo_pesquisador = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash"
).bind_tools(TOOLS_PESQUISADOR)

modelo_contraparte = ChatAnthropic(
    model="claude-sonnet-4-6"
).bind_tools(TOOLS_CONTRAPARTE)
```

### 6.4 Caminho de Integracao

- **MVP**: Importacao direta de `rag/query.py` como modulo Python. Mesmo processo, sem latencia de rede.
- **Futuro**: API REST (`/api/tools/buscar_favoraveis`) para desacoplamento.
- **Longo prazo**: MCP Server para interoperabilidade com outros frameworks.

---

## 7. Integracao de Legislacao

### 7.1 Fontes Pesquisadas

| Fonte | Status | Texto completo? | Decisao |
|---|---|---|---|
| Planalto (HTML direto) | Funciona | Sim (~1.8MB/lei) | **Pre-indexar** |
| api-legislacao (GitHub) | Heroku morto (404) | N/A | Descartado |
| API Senado (dadosabertos) | Funciona | Nao, so metadados | Descartado |
| API Camara | Funciona | Nao, so metadados | Descartado |
| LexML | Sem API publica | N/A | Descartado |

### 7.2 Estrategia Implementada

**Camada 1 â€” Pre-indexacao dos codigos principais:**
- Fazer scrape limpo dos ~15 codigos mais usados do Planalto.gov.br
- Usar BeautifulSoup para:
  - Extrair artigos (cada `<div id="artN">` e um artigo)
  - Detectar revogacoes (tags `<strike>`, CSS `text-decoration: line-through`)
  - Converter para texto limpo (Latin-1 -> UTF-8)
- Indexar no LanceDB (mesma infra da jurisprudencia)
- Cobre ~90% dos casos

Codigos prioritarios: CC, CPC, CDC, CLT, CF/88, CP, CPP, ECA, CTB, Lei de Locacoes (8.245), Lei de Licitacoes (14.133), Estatuto do Idoso, Estatuto da Cidade, Lei Maria da Penha, LINDB.

**Camada 2 â€” Busca dinamica para leis esparsas:**
- Gemini com Google Search grounding
- Para leis que nao estao no cache local

**Camada 3 â€” Verificacao deterministica:**
- Apos o agente citar um artigo, fetch direto no Planalto para confirmar
- Se parser falhar ou confianca baixa: `[VERIFICAR TEXTO - Art. X, Lei Y]` com link

### 7.3 Estrutura HTML do Planalto (confirmada)

```html
<div id="art186">
  <p align="justify">
    <a name="art186"></a>Art. 186. Aquele que, por acao ou omissao voluntaria,
    negligencia ou imprudencia, violar direito e causar dano a outrem, ainda que
    exclusivamente moral, comete ato ilicito.
  </p>
</div>
```

- Anchors nomeados: `<a name="artN">`
- IDs: `<div id="artN">`
- Encoding: Latin-1 (converter para UTF-8)
- URLs previsiveis: `/ccivil_03/leis/2002/l10406.htm` (CC)

---

## 8. Verificacao Deterministica de Citacoes

### 8.1 Arquitetura em Camadas

A verificacao nao e regex puro. E um pipeline de 5 camadas:

**Camada 1 â€” Normalizacao:**
- Remover acentos, espacos extras, hifens variaveis
- Normalizar caixa
- Mapear aliases de tribunal (STJ, S.T.J., Superior Tribunal de Justica)
- Normalizar classes (REsp, RESP, Recurso Especial)

Funcoes de normalizacao ja existentes no codebase (reutilizar):

```python
# rag/query.py:1111 â€” normalizacao de texto
def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))

# backend/juris_update.py:138 â€” normalizacao de espacos
def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

# backend/juris_update.py:157 â€” remocao de acentos
def _remove_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))
```

Tabela de expansao de abreviaturas (ja existente em `app.py`):

```python
LEGAL_EXPANSIONS = {
    "REsp": "Recurso Especial",
    "RE": "Recurso ExtraordinÃ¡rio",
    "HC": "Habeas Corpus",
    "RHC": "Recurso OrdinÃ¡rio em Habeas Corpus",
    "MS": "Mandado de SeguranÃ§a",
    "RMS": "Recurso OrdinÃ¡rio em Mandado de SeguranÃ§a",
    "ARE": "Agravo em Recurso ExtraordinÃ¡rio",
    "AI": "Agravo de Instrumento",
    "AgInt": "Agravo Interno",
    "AgRg": "Agravo Regimental",
    "EDcl": "Embargos de DeclaraÃ§Ã£o",
    "ADI": "AÃ§Ã£o Direta de Inconstitucionalidade",
    "ADC": "AÃ§Ã£o DeclaratÃ³ria de Constitucionalidade",
    "ADPF": "ArguiÃ§Ã£o de Descumprimento de Preceito Fundamental",
    "IRDR": "Incidente de ResoluÃ§Ã£o de Demandas Repetitivas",
    "IAC": "Incidente de AssunÃ§Ã£o de CompetÃªncia",
    # Codigos
    "CC": "CÃ³digo Civil (Lei nÂº 10.406/2002)",
    "CPC": "CÃ³digo de Processo Civil",
    "CPP": "CÃ³digo de Processo Penal",
    "CP": "CÃ³digo Penal",
    "CF": "ConstituiÃ§Ã£o Federal",
    "CDC": "CÃ³digo de Defesa do Consumidor",
    "CLT": "ConsolidaÃ§Ã£o das Leis do Trabalho",
}
```

**Camada 2 â€” Extracao hibrida (regex + parser + NER leve):**

Regex verificados e testados contra o codebase existente:

```python
# â”€â”€ Formato CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO â”€â”€
# Estrutura: 7 digitos sequenciais, 2 digitos verificadores,
#            4 ano, 1 justica, 2 tribunal, 4 origem
RE_CNJ = r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}'
# Match: 1234567-89.2025.8.26.0100

# â”€â”€ Classes processuais do STJ (de backend/juris_update.py) â”€â”€
STJ_PROCESS_CLASS_PATTERN = (
    r"(?:ProAfR|AgRg|AgInt|Ag|EDcl|EAREsp|EREsp|AREsp|REsp|RHC|HC|RMS|CC|"
    r"Pet|MC|RCL|Rcl|MS|AI|AR|SE|CR|SD|RPV|SS|SLS|RO|APn|IDC|QC|TutCautAnt|"
    r"PUIL|AC|RvCr|IF|Inq|HDE|MI|ExSusp|ExeMS|SEC|SIRDR)"
)

# â”€â”€ Citacao de caso: REsp 1.234.567/SP â”€â”€
RE_CASO = (
    r'\b(' + STJ_PROCESS_CLASS_PATTERN +
    r')\s+(?:nÂº?\s*)?\d+(?:[.,]\d{3})*\s*/\s*[A-Z]{2}'
)
# Match: REsp 1.234.567/SP, AgInt no AREsp 1.799.837/SP

# â”€â”€ Citacao de caso com composicao (AgInt no REsp...) â”€â”€
RE_CASO_COMPOSTO = (
    r'(' + STJ_PROCESS_CLASS_PATTERN +
    r'(?:\s+(?:no|na|nos|nas)\s+' + STJ_PROCESS_CLASS_PATTERN + r'){0,2}'
    r'\s+\d[\d\.\-/A-Z]*)'
)

# â”€â”€ Sumula â”€â”€
RE_SUMULA = r'\b(?:SÃºmula|SÃºm\.?)\s+(?:Vinculante\s+)?(?:nÂº?\s*)?\d+(?:\s*(?:do|da|/)\s*(?:STF|STJ|TST))?'
# Match: SÃºmula 385 do STJ, SÃºm. Vinculante 26, SÃºmula 548/STJ

# â”€â”€ Tema Repetitivo â”€â”€
RE_TEMA = r'\bTema(?:\s+Repetitivo)?\s+(?:nÂº?\s*)?\d+(?:\.\d+)?(?:\s+(?:do|/)\s*(?:STJ|STF))?'
# Match: Tema 952 do STJ, Tema Repetitivo nÂº 1.016

# â”€â”€ Artigo de lei â”€â”€
RE_ARTIGO = r'\b(?:Art|art)\.?\s+(?:nÂº?\s*)?\d+[A-Za-zÂ§\-]*(?:\s*[,;]\s*(?:Â§|inciso|alinea|caput)[\w\s]*)*'
# Match: Art. 186 do CC, art. 5Âº, inciso XXXV da CF

# â”€â”€ Lei (numero + ano) â”€â”€
RE_LEI = r'\bLei\s+(?:nÂº?\s*)?\d+(?:[.,/]\d+)*(?:\s+de\s+\d{1,2}\s+de\s+[a-zÃ§]+\s+de\s+\d{4})?'
# Match: Lei nÂº 10.406/2002, Lei 13.465/2017

# â”€â”€ Relator â”€â”€
RE_RELATOR = (
    r'Rel(?:ator)?\.?\s*(?:p/?\s*)?(?:para\s+acÃ³rdÃ£o\s*)?'
    r'((?:Min\.?|Ministro|Ministra)\s+[A-ZÃ€-Ã–Ã˜-Ã¶Ã¸-Ã¿][A-ZÃ€-Ã–Ã˜-Ã¶Ã¸-Ã¿\s\.\'"-]+?)'
    r'(?=\s*(?:,|\(|\n|$))'
)

# â”€â”€ Data de julgamento â”€â”€
RE_DATA_JULG = r'julgado\s+em\s+(\d{1,2}/\d{1,2}/\d{4})'

# â”€â”€ Data de publicacao (DJe) â”€â”€
RE_DATA_PUB = r'DJE(?:N)?(?:\s+de)?\s+(\d{1,2}/\d{1,2}/\d{4})'
```

**Validacao de digitos verificadores CNJ (ISO 7064 Mod 97, Base 10):**

```python
def validar_cnj(numero_cnj: str) -> bool:
    """Valida digitos verificadores de numero CNJ.
    Formato: NNNNNNN-DD.AAAA.J.TR.OOOO
    Algoritmo: ISO 7064 Mod 97 Base 10
    """
    # Extrair componentes
    limpo = re.sub(r'[\-\.]', '', numero_cnj)
    if len(limpo) != 20:
        return False

    n = limpo[0:7]    # sequencial
    dd = limpo[7:9]   # digitos verificadores
    aaaa = limpo[9:13] # ano
    j = limpo[13:14]  # justica
    tr = limpo[14:16] # tribunal
    oooo = limpo[16:20] # origem

    # Reposicionar: N6..N0 A3..A0 J T1R0 O3..O0 D1D0
    valor = int(n + aaaa + j + tr + oooo + dd)
    return valor % 97 == 1
```

**Camada 3 â€” Resolucao para identificador canonico:**

```python
class CitacaoCanonica(BaseModel):
    """Identificador canonico de uma citacao juridica."""
    tipo: Literal["jurisprudencia", "sumula", "tema_repetitivo", "legislacao"]
    tribunal: Optional[str]          # "STJ", "STF", "TJSP"
    classe: Optional[str]            # "REsp", "HC", "ADI"
    numero: str                      # "1234567" (sem pontos/separadores)
    uf: Optional[str]                # "SP", "RJ"
    relator: Optional[str]
    orgao_julgador: Optional[str]
    data: Optional[str]              # "2025-03-15"
    # Para legislacao:
    lei_numero: Optional[str]        # "10406"
    lei_ano: Optional[str]           # "2002"
    artigo: Optional[str]            # "186"
    paragrafo: Optional[str]
    inciso: Optional[str]
    # Forma canonica para comparacao:
    canonical_key: str               # Ex: "resp_1234567_sp" ou "sumula_385_stj"
```

Funcao de canonicalizacao:

```python
def canonicalizar(citacao_raw: str) -> CitacaoCanonica:
    """Converte citacao bruta em forma canonica para comparacao."""
    normalizada = _remove_accents(_normalize_space(citacao_raw)).lower()

    # Tentar cada regex em ordem de especificidade
    if m := re.search(RE_CNJ, citacao_raw):
        # Numero CNJ completo
        return CitacaoCanonica(
            tipo="jurisprudencia",
            numero=re.sub(r'[\-\.]', '', m.group()),
            canonical_key=f"cnj_{re.sub(r'[\-\.]', '', m.group())}"
        )

    if m := re.search(RE_CASO, citacao_raw):
        classe = m.group(1)
        numero = re.sub(r'[.,\s]', '', ...)
        uf = ...
        return CitacaoCanonica(
            tipo="jurisprudencia", classe=classe, numero=numero, uf=uf,
            canonical_key=f"{classe.lower()}_{numero}_{uf.lower()}"
        )

    if m := re.search(RE_SUMULA, citacao_raw, re.IGNORECASE):
        # Extrair numero e tribunal
        ...
        return CitacaoCanonica(
            tipo="sumula", numero=num, tribunal=trib,
            canonical_key=f"sumula_{num}_{trib.lower()}"
        )

    # ... tema, artigo, lei
```

**Camada 4 â€” Matching em niveis:**

| Nivel | Criterio | Confianca | Acao |
|---|---|---|---|
| `exact_match` | `canonical_key` identico no banco | 100% | Confirmada |
| `strong_match` | numero + tribunal + classe confere | 90% | Confirmada |
| `weak_match` | numero confere, metadados parciais | 60% | `[VERIFICAR]` |
| `unverified` | nenhum match ou match ambiguo | 0% | `[NAO VERIFICADO]` |

**Camada 5 â€” Validacao de proveniencia:**
- Confirma que a citacao usada na secao esta no evidence pack daquela secao
- Confirma que o texto do acordao sustenta a afirmacao feita na peca
- Nao basta existir no banco â€” precisa ser relevante pro argumento

### 8.2 Coverage Registry

Catalogo versionado de formatos suportados por fonte:

| Tipo | Formatos cobertos | Regex principal |
|---|---|---|
| Jurisprudencia CNJ | `NNNNNNN-DD.AAAA.J.TR.OOOO` | `RE_CNJ` |
| Jurisprudencia legado | `REsp 1.234.567/SP`, `HC 123456` | `RE_CASO`, `RE_CASO_COMPOSTO` |
| Sumulas | Simples, vinculantes, STJ/STF/TST | `RE_SUMULA` |
| Temas repetitivos | `Tema 952`, `Tema Repetitivo nÂº 1.016/STJ` | `RE_TEMA` |
| Legislacao | `Art. 186 do CC`, `Lei nÂº 10.406/2002` | `RE_ARTIGO`, `RE_LEI` |
| Relator | `Rel. Min. NANCY ANDRIGHI` | `RE_RELATOR` |
| Datas | `julgado em DD/MM/AAAA`, `DJe DD/MM/AAAA` | `RE_DATA_JULG`, `RE_DATA_PUB` |

Cada novo erro real em producao gera nova regra no registry. O catalogo e versionado e testado contra um corpus de 50+ citacoes reais extraidas de peticoes.

---

## 9. UX â€” Dashboard, Interface e Identidade Visual

### 9.1 Estrutura Geral e Navegacao

O Ratio Escritorio e uma **nova aba no Ratio** (nao produto separado). Compartilha backend, LanceDB, API keys.

Acesso via rail lateral esquerda (64px), mesmo padrao dos botoes existentes:
```
[R]  (brand)
[Pesquisa]        â† rail-btn existente (icone search)
[Historico]       â† rail-btn existente (icone clock)
[Salvos]          â† rail-btn existente (icone bookmark)
[Sobre]           â† rail-btn existente (icone info)
[Informativo]     â† rail-btn existente (icone newspaper)
[Alertas]         â† rail-btn existente (icone bell)
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
[Escritorio]      â† NOVO rail-btn (icone briefcase ou scale)
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
[Meu Acervo]      â† rail-btn existente (icone folder)
[Tema]            â† rail-btn existente (icone sun/moon)
[Config]          â† rail-btn existente (icone settings)
```

### 9.2 Identidade Visual â€” Obrigatoria

O Ratio Escritorio DEVE seguir a identidade visual existente do Ratio. As cores, tipografia e componentes sao os mesmos â€” nao e uma aplicacao separada.

**Paleta de cores (Warm Obsidian):**

| Variavel | Light mode | Dark mode | Uso |
|---|---|---|---|
| `--stone-50` | #fafaf9 | #141210 | Fundo principal (chat-main) |
| `--stone-100` | #f5f5f4 | #1c1917 | Fundo do body / surfaces |
| `--stone-200` | #e7e5e4 | #2e2a27 | Bordas, separadores |
| `--stone-300` | #d6d3d1 | #3a3633 | Bordas ativas, destaques |
| `--stone-400` | #a8a29e | #6b6662 | Texto secundario, icones inativos |
| `--stone-500` | #78716c | #9a948f | Texto terciario |
| `--stone-700` | #44403c | #c4bfba | Texto secundario ativo |
| `--stone-800` | #292524 | #d6d1cc | Texto primario |
| `--stone-900` | #1c1917 | #e8e5e2 | Texto principal / titulos |
| Accent (gold) | â€” | #c4a882 | Links, active indicators, headings border |

**Tipografia:**
- Corpo: Inter 400/500/600/700
- Titulos de secao juridica: Cormorant Garamond (serif) â€” ver uso existente em respostas
- MonoespaÃ§ado: JetBrains Mono â€” chips, badges, dados tecnicos
- Citacoes/ementas: Merriweather (serif italic)

**Componentes reutilizaveis do Ratio existente:**
- `.rail-btn` â€” botoes da rail lateral (32x32, border-radius 6px, hover com bg rgba)
- `.rail-btn.active::before` â€” indicator dourado a esquerda (#c4a882 no dark)
- `.chip-btn` â€” botoes pequenos (JetBrains Mono 12px, bg #232019 dark)
- `.top-header` â€” barra superior 64px com backdrop-filter blur
- `.composer` â€” area de input flutuante com gradiente e sombra
- `.panel-shell` â€” modais/paineis com fundo #232019 dark

**O que os mockups gerados NAO respeitam (corrigir na implementacao):**
- Mockups usam paleta navy blue (#1a1a2e) â€” o Ratio usa Warm Obsidian (#1c1917 / #141210)
- Mockups usam cards com borda azul â€” o Ratio usa bordas stone (#2e2a27 / #3a3633)
- Mockups usam accent azul (#1565c0) â€” o Ratio usa accent dourado (#c4a882)
- Na implementacao real, TODOS os componentes devem usar as variaveis CSS `--stone-*` existentes
- Os mockups servem como referencia de LAYOUT e ESTRUTURA, nao de cores

### 9.3 Comportamento da Aba â€” Nao e um Chat

O Ratio Escritorio NAO e uma interface de chat. E um **workspace de caso** com 3 modos distintos conforme a onda:

**Modo 1 â€” Intake (Onda 0): Interface de chat**
- Este e o UNICO momento com interface de chat
- Reutiliza o layout `.chat-main` + `.composer` do Ratio existente
- Mensagens do usuario a direita, do Intake a esquerda (mesmo padrao `.msg-user` / `.msg-assistant`)
- Ao concluir: transicao animada para o dashboard do caso
- Componentes: `.thread` (scroll), `.composer` (input), `.msg-*` (bolhas)

**Modo 2 â€” Pesquisa e Dashboard (Ondas 1-3): Interface de workspace**
- Layout de grid com cards, tabelas e paineis â€” nao chat
- O advogado NAO "conversa" com o sistema nessa fase
- Ele VE resultados, APROVA gates, EDITA secoes, CLICA em acoes
- Layout 3 colunas para o editor (secao 9.5)
- Cards de tese, criticas, verificacao â€” componentes proprios

**Modo 3 â€” Entrega (Onda 4): Interface de resultado**
- Tela de resumo com botao de download
- Relatorio de verificacao, custo total, metricas

**Transicoes entre modos:**
- Animacao suave (fade + slide, ~300ms, cubic-bezier)
- Stepper no topo mostrando progresso: `Intake âœ“ Â· Pesquisa â— Â· Redacao â—‹ Â· Entrega â—‹`
- O advogado pode voltar para qualquer modo anterior (intake, pesquisa) se precisar ajustar

### 9.4 Tela "Meus Casos"

Ponto de entrada. Lista de casos com:
- Nome do caso
- Tipo de peca
- Status (intake / pesquisa / redacao / adversarial / finalizado)
- Rodada atual
- Custo acumulado
- Ultima acao
- Data de criacao / modificacao

### 9.5 Dashboard do Caso (Cards Hierarquicos)

**Maximo 2 niveis de hierarquia + master-detail:**

```
Nivel 1: CASO
  Status geral | Risco | Custo | Proxima acao

Nivel 2: TESES (cards expansiveis)
  Tese 1: Responsabilidade objetiva | Confianca: Alta | 5 acordaos
  Tese 2: Dano moral presumido | Confianca: Media | 3 acordaos

Drill-down (master-detail): Autoridades, acoes, detalhes
```

Cada nivel responde UMA pergunta:
- **Caso** = o que priorizar?
- **Tese** = o que defender?
- **Autoridade** (drill-down) = em que base?
- **Acao** (drill-down) = o que fazer agora?

### 9.6 Auditabilidade Total â€” Principio Inegociavel

Todo trabalho de todo agente deve ser auditavel. O advogado deve ser capaz de verificar:
(a) quais documentos serviram de base para cada agente trabalhar,
(b) qual foi o output gerado por cada agente,
(c) o conteudo completo de cada documento citado, e
(d) os links externos para inteiro teor (PDF do STF, STJ, etc.) quando disponiveis.

O principio e: **nada e opaco**. O advogado pode exibir ou ocultar qualquer camada de detalhe conforme sua necessidade, mas a informacao deve existir e estar acessivel.

#### 9.6.1 Dossie de Pesquisa â€” Artefato Central Persistente

O Dossie de Pesquisa e o artefato mais importante do sistema. Ele documenta TODA a pesquisa realizada, com todos os documentos na integra, para posterior consulta e validacao.

**Estrutura do Dossie:**

```python
class DocumentoColetado(BaseModel):
    """Um documento retornado pelo Ratio e preservado no dossie."""
    doc_id: str                          # ID unico no LanceDB
    processo: str                        # Ex: "REsp 1.059.663/MS"
    tribunal: str                        # Ex: "STJ"
    tipo: str                            # Ex: "acordao", "sumula"
    relator: str
    orgao_julgador: str
    data_julgamento: str

    # â”€â”€ Conteudo em 3 camadas â”€â”€
    ementa: str                          # Ementa extraida (sempre presente)
    texto_integral_excerpt: str          # Trecho relevante retornado pelo Ratio
    texto_integral_full: Optional[str]   # Texto completo se disponivel no banco

    # â”€â”€ Links externos â”€â”€
    inteiro_teor_url: Optional[str]      # URL do PDF no tribunal (ex: STF, STJ)
    inteiro_teor_cached: bool = False    # Se o PDF ja foi baixado localmente

    # â”€â”€ Metadados de relevancia â”€â”€
    score_final: float                   # Score do reranker
    score_semantico: float
    tese_vinculada: str                  # Qual tese esse doc sustenta/refuta
    papel: Literal["favoravel", "contrario", "neutro"]
    trecho_citado_na_peca: Optional[str] # Qual trecho foi usado na peticao

    # â”€â”€ Ementa analisada por LLM â”€â”€
    ementa_analise: Optional[str]        # Analise da LLM sobre o que a ementa diz
                                         # em relacao a tese (gerada sob demanda)

class DossiePesquisa(BaseModel):
    """Dossie completo de pesquisa do caso â€” artefato persistente."""
    caso_id: str
    gerado_em: datetime
    teses: List[TeseJuridica]
    documentos: List[DocumentoColetado]  # TODOS os docs retornados, nao so os top
    queries_executadas: List[Dict]       # {query, filtros, n_resultados, timestamp}
    legislacao_encontrada: List[Dict]    # Artigos de lei identificados
    resumo_por_tese: Dict[str, str]      # Tese â†’ resumo do que foi encontrado
```

**Infra existente que sustenta isso:**

O Ratio atual ja retorna por documento (via `run_query()` â†’ `top_docs`):
- `texto_integral_full` â€” texto completo quando indexado
- `texto_integral_excerpt` â€” trecho relevante
- `texto_busca` â€” texto usado na busca
- `inteiro_teor_url` â€” URL do PDF no tribunal
- `processo`, `tribunal`, `relator`, `orgao_julgador`, `data_julgamento`
- Scores: `_final_score`, `_semantic_score`, `_lexical_score`

O painel de evidencias (`.evidence-panel`, `.source-card`) ja renderiza esses dados com botao "Ler inteiro teor" (link externo ou inline). O Escritorio reutiliza essa infra.

#### 9.6.2 Niveis de Visibilidade â€” O Usuario Controla

Toda informacao existe, mas o advogado escolhe o nivel de detalhe que quer ver:

**Nivel 1 â€” Resumo (padrao):**
- Por tese: "22 julgados favoraveis, 3 contrarios. Forca: Alta."
- O advogado que quer rapidez ve so isso e confia no sistema.

**Nivel 2 â€” Ementas (1 clique):**
- Lista de decisoes com: ementa, tribunal, processo, data, relator
- Botao [Copiar ementa] (ja existe no Ratio)
- Analise da LLM: "Esta decisao confirma que o prazo de 5 dias uteis da Sumula 548 se aplica mesmo quando a quitacao e parcial" â€” gerada sob demanda quando o usuario expande

**Nivel 3 â€” Texto completo (1 clique):**
- Texto integral do acordao/decisao (campo `texto_integral_full`)
- Trecho que foi citado na peticao destacado em amarelo
- Se nao houver texto completo no banco: botao [Buscar inteiro teor] tenta fetch

**Nivel 4 â€” Fonte original (link externo):**
- Link para o PDF no site do tribunal (campo `inteiro_teor_url`)
- Ex: link direto para o PDF do acordao no site do STF/STJ
- Listados no dossie com status: [PDF disponivel] ou [Sem link externo]

**UI: Toggle de visibilidade**
```
[Resumo] [Ementas] [Texto completo] [Links externos]
   â—        â—‹            â—‹                â—‹
```
O advogado clica no nivel desejado. Pode alternar a qualquer momento. A informacao esta la independentemente do toggle â€” ele so controla o que aparece na tela.

#### 9.6.3 Analise de Ementa por LLM (sob demanda)

Quando o advogado expande uma decisao no dossie, o sistema oferece um botao:

**[Analisar ementa]**

A LLM (Gemini Flash, custo minimo) le a ementa e o contexto da tese, e gera uma analise curta:

> "Esta decisao do STJ (3a Turma, 2025) confirma que a manutencao de negativacao apos quitacao integral configura dano moral in re ipsa, independentemente de prova do abalo. O relator enfatiza que o prazo de 5 dias uteis da Sumula 548 e peremptorio. **Relevancia para o caso:** diretamente aplicavel â€” mesma situacao fatica (quitacao comprovada + manutencao da negativacao)."

Essa analise e salva no campo `ementa_analise` do `DocumentoColetado` e nao precisa ser regenerada.

**Por que sob demanda e nao automatico?**
- Economia de tokens (pode ser 40+ documentos por caso)
- O advogado decide quais ementas valem a pena analisar
- Evita "analise de tudo" que dilui a atencao

#### 9.6.4 Registro de Execucao por Agente (Agent Ledger)

Cada execucao de cada agente gera um registro imutavel:

```python
class AgentExecution(BaseModel):
    agent: str                      # "Intake", "Pesquisador", etc.
    timestamp: datetime
    round_number: int
    input_summary: str              # Resumo do que o agente recebeu
    input_documents: List[str]      # IDs dos DocumentoColetado de entrada
    output_raw: str                 # Output completo do agente (texto cru)
    output_structured: Optional[Dict]  # Output parseado (JSON/Pydantic)
    output_documents: List[str]     # IDs dos DocumentoColetado que o agente produziu/selecionou
    model_used: str                 # "gemini-2.5-flash", "claude-sonnet-4-6"
    tokens_in: int
    tokens_out: int
    cost_brl: float
    tools_called: List[Dict]        # [{tool, input, output_ids}] por chamada
```

Acessivel no UI via botao **[Ver execucao]** em cada card de agente.
Para cada tool_called, o advogado pode ver: a query enviada, os documentos retornados, e o que o agente fez com eles.

#### 9.6.5 Trilha de Auditoria no Dashboard

O dashboard do caso tem uma aba **"Trilha de Auditoria"** que mostra cronologicamente:

```
[10:02] Intake â€” Coletou 6 fatos, 4 documentos â†’ [ver dossie]
[10:03] Gate 1 â€” Aprovado pelo usuario
[10:04] Pesquisador â€” Decompos em 4 teses â†’ [ver teses]
        â”œâ”€ Query: "manutencao negativacao apos quitacao" â†’ 22 docs â†’ [ver todos]
        â”œâ”€ Query: "dano moral in re ipsa negativacao" â†’ 11 docs â†’ [ver todos]
        â”œâ”€ Query: "responsabilidade objetiva banco CDC" â†’ 6 docs â†’ [ver todos]
        â”œâ”€ Query: "majoracao dano moral perda credito" â†’ 4 docs â†’ [ver todos]
        â””â”€ Query: "excludente responsabilidade banco" â†’ 3 docs â†’ [ver todos]
[10:05] Gate 2 â€” Aprovado pelo usuario
[10:06] Redator â€” Gerou peticao v1 (5 secoes) â†’ [ver output]
        â””â”€ Docs usados: 14 de 46 disponÃ­veis â†’ [ver quais e por que]
[10:08] Contraparte â€” Score 35/100, 2 criticas, 1 lacuna â†’ [ver criticas]
        â”œâ”€ Query: "prescricao dano moral..." â†’ 5 docs â†’ [ver todos]
        â””â”€ Query: "requisitos tutela art 300..." â†’ 3 docs â†’ [ver todos]
[10:09] Usuario â€” Editou secao "dos_pedidos" â†’ [ver diff]
[10:10] Redator â€” Revisou 2 secoes â†’ [ver output] [ver diff v1â†’v2]
[10:11] Contraparte â€” Score 12/100 â†’ [ver criticas]
[10:12] Verificador â€” 7/8 citacoes confirmadas â†’ [ver relatorio]
[10:12] Formatador â€” DOCX gerado â†’ [baixar]
```

Cada `[ver todos]` abre a lista completa de documentos retornados pela query, com todos os 4 niveis de visibilidade disponiveis (resumo, ementa, texto completo, link externo).

#### 9.6.6 Dossie Exportavel

O advogado pode exportar o Dossie de Pesquisa completo como:

**Opcao 1 â€” Dentro do DOCX da peticao (anexo):**
- Secao "Anexo â€” Dossie de Pesquisa" ao final do documento
- Lista todas as decisoes citadas com ementa e link
- Util para arquivo pessoal

**Opcao 2 â€” Arquivo separado (JSON ou DOCX):**
- Dossie completo com todos os documentos, queries, analises
- Para consulta futura ou compartilhamento com colegas
- Inclui: queries executadas, docs retornados, scores, ementas, textos, links PDF

**Opcao 3 â€” Nao exportar (padrao):**
- O dossie fica salvo no SQLite local, acessivel pela interface a qualquer momento

### 9.7 Layout do Editor (3 colunas)

```
+-------------------+-------------------------+----------------------+
| NAVEGACAO SECOES  | EDITOR DA SECAO         | CONTEXTO OPERACIONAL |
|                   |                         |                      |
| > Preliminares    | [texto editavel]        | Apontamentos usuario |
|   Dos Fatos    *  |                         | Criticas Contraparte |
|   Do Direito      | Toggle:                 | Jurisprudencia usada |
|   Pedidos         |  [Final] [Diff] [v1]   | Jurisp. contraria    |
|   Valor da Causa  |                         | Checklist citacoes   |
|                   | Botoes rapidos:         |                      |
| * = editado       | [Aprofundar]            | Dependencias:        |
|                   | [Enxugar]               | "Editar dos_fatos    |
|                   | [Trocar tese]           |  impacta do_direito  |
|                   | [Inserir precedente]    |  e pedidos"          |
|                   | [Corrigir tom]          |                      |
|                   |                         |                      |
|                   | Campo livre:            |                      |
|                   | [________________]      |                      |
|                   |                         |                      |
|                   | [+ Rodada] [Finalizar]  |                      |
+-------------------+-------------------------+----------------------+
```

### 9.5 Burn Meter (Custo em Tempo Real)

```
+----------------------------------------------------+
| Caso: Silva vs. Empresa X                           |
| Gasto atual: R$ 3,10                               |
| Se revisar 3 secoes criticadas: +R$ 1,40 estimado  |
| Se rodar mais uma rodada adversarial: +R$ 2,10     |
+----------------------------------------------------+
```

**Ledger por evento:**
- Cada chamada registra: agente, modelo, provider, tokens_in, tokens_out, custo unitario, custo total, latencia, caso_id, secao_id, rodada
- Custos separados por categoria: intake, pesquisa, redacao, contraparte, revisao
- **Estimativa ANTES de executar** cada etapa

### 9.6 Streaming

O usuario ve a peticao sendo escrita em tempo real, token por token. Os cards dos agentes atualizam com status em tempo real.

**Estrutura do evento de streaming:**
```json
{
    "event": "token_stream",
    "agent": "Redator",
    "section": "do_direito",
    "token": "O autor alega..."
}

{
    "event": "agent_status",
    "agent": "Contraparte",
    "status": "tool_start",
    "tool": "ratio_search",
    "tool_input": {"query": "prescricao dano moral consumerista"}
}

{
    "event": "cost_update",
    "total_usd": 0.0031,
    "total_brl": 0.016,
    "agent": "Pesquisador"
}
```

### 9.7 Protocolo de Comunicacao

**Opcao A â€” SSE + POST (mais simples, recomendado para MVP):**
- SSE (Server-Sent Events) para streaming servidor -> cliente
- HTTP POST para acoes do usuario (editar secao, aprovar gate, mais rodada)
- Mais simples, reconexao automatica nativa do EventSource

**Opcao B â€” WebSocket (mais poderoso, para evolucao):**
- Bidirecional, menor latencia
- Necessario se quisermos interrupcao em tempo real durante geracao
- Mais complexo de implementar e manter

**Decisao: SSE + POST para MVP. Migrar para WebSocket se necessario.**

---

## 10. Persistencia

### 10.1 Um Banco SQLite por Caso

Cada caso gera seu proprio arquivo SQLite. A estrutura de diretorio e:

```
ratio_escritorio/
â”œâ”€â”€ index.db                    â† Indice global (lista de casos, config)
â”œâ”€â”€ casos/
â”‚   â”œâ”€â”€ caso_047_silva_v_banco_x/
â”‚   â”‚   â”œâ”€â”€ caso.db             â† Banco do caso (state, execucoes, dossie)
â”‚   â”‚   â”œâ”€â”€ docs/               â† Documentos do cliente (uploads)
â”‚   â”‚   â”‚   â”œâ”€â”€ comprovante_quitacao.pdf
â”‚   â”‚   â”‚   â”œâ”€â”€ certidao_spc.pdf
â”‚   â”‚   â”‚   â””â”€â”€ email_recusa_caixa.pdf
â”‚   â”‚   â””â”€â”€ output/             â† Artefatos gerados
â”‚   â”‚       â”œâ”€â”€ peticao_v1.json
â”‚   â”‚       â”œâ”€â”€ peticao_v2.json
â”‚   â”‚       â””â”€â”€ Peticao_Inicial_Silva_v_Banco_X.docx
â”‚   â”œâ”€â”€ caso_048_oliveira_v_seguradora/
â”‚   â”‚   â”œâ”€â”€ caso.db
â”‚   â”‚   â”œâ”€â”€ docs/
â”‚   â”‚   â””â”€â”€ output/
â”‚   â””â”€â”€ ...
```

**Por que um banco por caso (e nao um banco global)?**

| Aspecto | Banco global | Banco por caso |
|---|---|---|
| Backup | Backup tudo ou nada | Backup/exportar um caso especifico |
| Exclusao | `DELETE WHERE caso_id=X` (dados orfaos possiveis) | Deletar a pasta inteira â€” limpo |
| Compartilhamento | Impossivel sem exportacao | Zipar a pasta e enviar pro colega |
| Isolamento | Cross-case leak possivel | Impossivel por design |
| Arquivo morto | Complexo | Mover pasta pra `arquivo/` |
| Performance | Tabelas crescem com N casos | Cada banco e pequeno e rapido |
| Migracao de schema | Migrar banco global com N casos | Migrar caso a caso (ou so novos) |

O `index.db` global contem apenas:

```sql
-- index.db (leve, so metadados para a tela "Meus Casos")
CREATE TABLE casos_index (
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    tipo_peca TEXT NOT NULL,
    area_direito TEXT,
    status TEXT NOT NULL DEFAULT 'intake',
    rodada_atual INTEGER DEFAULT 0,
    custo_total_brl REAL DEFAULT 0,
    path TEXT NOT NULL,           -- caminho relativo da pasta do caso
    created_at TEXT,
    updated_at TEXT
);
```

### 10.2 Schema do Banco por Caso

```sql
-- caso.db (dentro da pasta do caso)

CREATE TABLE state (
    key TEXT PRIMARY KEY,
    value_json TEXT,              -- Estado serializado do LangGraph
    updated_at TEXT
);

CREATE TABLE dossie_intake (
    id INTEGER PRIMARY KEY,
    fatos_json TEXT,              -- DossieIntake serializado (Pydantic)
    documentos_declarados TEXT,   -- Lista de docs que o usuario afirma ter
    created_at TEXT
);

CREATE TABLE teses (
    id TEXT PRIMARY KEY,
    descricao TEXT NOT NULL,
    forca TEXT,                   -- "muito_alta", "alta", "moderada", "baixa"
    n_favoraveis INTEGER DEFAULT 0,
    n_contrarios INTEGER DEFAULT 0,
    resumo TEXT,
    created_at TEXT
);

CREATE TABLE documentos_pesquisa (
    id TEXT PRIMARY KEY,
    tese_id TEXT REFERENCES teses(id),
    doc_id_lancedb TEXT,          -- Referencia ao doc no LanceDB global
    processo TEXT,
    tribunal TEXT,
    tipo TEXT,
    relator TEXT,
    orgao_julgador TEXT,
    data_julgamento TEXT,
    ementa TEXT,
    texto_excerpt TEXT,
    texto_integral TEXT,
    inteiro_teor_url TEXT,
    score_final REAL,
    papel TEXT,                   -- "favoravel", "contrario", "neutro"
    trecho_citado TEXT,           -- Trecho usado na peticao (se usado)
    ementa_analise TEXT,          -- Analise da LLM (sob demanda)
    created_at TEXT
);

CREATE TABLE documentos_cliente (
    id TEXT PRIMARY KEY,
    nome_original TEXT NOT NULL,  -- Nome do arquivo enviado
    tipo TEXT,                    -- "contrato", "comprovante", "certidao", etc.
    descricao TEXT,               -- Descricao do usuario
    path_local TEXT,              -- Caminho em docs/
    conteudo_extraido TEXT,       -- Texto extraido por OCR/vision (se processado)
    processado BOOLEAN DEFAULT 0,
    created_at TEXT
);

CREATE TABLE execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agente TEXT NOT NULL,
    round_number INTEGER,
    input_summary TEXT,
    input_doc_ids TEXT,           -- JSON array de IDs
    output_raw TEXT,
    output_structured TEXT,       -- JSON
    output_doc_ids TEXT,          -- JSON array de IDs
    model_used TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_brl REAL,
    tools_called TEXT,            -- JSON array
    timestamp TEXT
);

CREATE TABLE peticao_versoes (
    version INTEGER PRIMARY KEY,
    sections_json TEXT,           -- Dict[str, str] serializado
    criticas_json TEXT,           -- CriticaContraparte da rodada
    edicoes_usuario TEXT,         -- Edicoes manuais do usuario
    score_risco INTEGER,
    created_at TEXT
);

CREATE TABLE verificacao_citacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    citacao_raw TEXT,
    citacao_normalizada TEXT,
    tipo TEXT,                    -- "jurisprudencia", "sumula", "legislacao"
    status TEXT,                  -- "confirmada", "nao_verificada"
    match_level TEXT,             -- "exact", "strong", "weak", "unverified"
    texto_real TEXT,              -- Texto confirmado no banco
    doc_pesquisa_id TEXT,         -- Referencia ao DocumentoColetado
    created_at TEXT
);
```

### 10.3 Salvamento Automatico

- Auto-save a cada transicao de estado no LangGraph (nao so por onda, mas por no do grafo)
- Se o processo quebrar na onda 3 rodada 2, ao reabrir o caso o sistema retoma exatamente dali
- Cada versao da peticao e salva (tabela `peticao_versoes`), contrariando a decisao anterior de "so ultima versao" â€” o custo de armazenamento e irrisorio e o advogado pode querer comparar versoes

---

## 10B. Documentacao do Cliente â€” Upload vs Declaracao

### 10B.1 A Pergunta Central

O advogado diz "tenho o comprovante de quitacao". O sistema precisa LER esse comprovante, ou basta SABER que ele existe?

**Resposta: depende do tipo de documento e do tipo de peca.**

### 10B.2 Tres Categorias de Documento

#### Categoria 1 â€” Documentos que o sistema precisa LER (upload obrigatorio)

| Documento | Por que precisa ler | Caso de uso |
|---|---|---|
| Peticao da parte contraria | E o input principal da contestacao | Contestacao |
| Contrato relevante | Clausulas especificas fundamentam a tese | Peticao onde o contrato e central |
| Decisao judicial anterior | Analisar o que o juiz ja decidiu | Recurso, embargos |

Para esses, o sistema aceita **PDF ou imagem** e extrai o texto via:
- PDF com texto: extrai direto (PyMuPDF / pdfplumber)
- PDF escaneado / imagem: Gemini Vision (modelo com capacidade multimodal)

O texto extraido e salvo em `documentos_cliente.conteudo_extraido` e alimenta o Intake e o Pesquisador como contexto adicional.

#### Categoria 2 â€” Documentos que o sistema referencia mas nao precisa ler (upload opcional)

| Documento | O que o sistema precisa saber | Exemplo |
|---|---|---|
| Comprovante de pagamento | Que existe, data, valor | "Quitacao em 15/01/2026" |
| Certidao do SPC | Que existe e mostra negativacao ativa | "Negativacao constatada em 10/03/2026" |
| Protocolos de atendimento | Que existem, numeros | "Protocolos #111, #222, #333" |
| Boletim de ocorrencia | Que existe, data, delegacia | "BO n.Âº X, DP Y" |

Para esses, o Intake **pergunta os dados relevantes** e o advogado responde em texto. O upload e opcional â€” se o advogado quiser anexar o PDF para referencia, o sistema aceita e armazena na pasta `docs/` do caso, mas nao precisa processar o conteudo.

Na peticao, esses documentos sao referenciados como "conforme doc. n.Âº 3 anexo" independentemente de terem sido uploadados ou apenas declarados.

#### Categoria 3 â€” Documentos que o sistema gera (nunca uploadados)

| Documento | Gerado por quem |
|---|---|
| Dossie de pesquisa | Pesquisador |
| Versoes da peticao | Redator |
| Relatorio de verificacao | Verificador |
| DOCX final | Formatador |

### 10B.3 Fluxo de Upload no Intake

O Intake, ao coletar documentos, segue este fluxo:

```
Intake: "Voce mencionou um comprovante de quitacao.
         Preciso saber: data do pagamento, valor, e se
         o documento tem timbre do banco."

         [Responder em texto]  [Enviar documento]
```

Se o advogado clica `[Enviar documento]`:
1. Seletor de arquivo (PDF, JPG, PNG)
2. Sistema classifica automaticamente: "Este parece ser um comprovante de pagamento"
3. Se for Categoria 1: extrai texto via PDF/Vision e alimenta o contexto
4. Se for Categoria 2: armazena na pasta `docs/`, pergunta os dados-chave em texto
5. Confirmacao: "Documento salvo como Doc. n.Âº 2 â€” Comprovante de quitaÃ§Ã£o"

Se o advogado clica `[Responder em texto]`:
1. Responde normalmente
2. O Intake registra no dossie: "Doc. 2 â€” Comprovante de quitaÃ§Ã£o (declarado, nÃ£o anexado)"
3. A peticao referencia igualmente como "doc. n.Âº 2 anexo"

### 10B.4 Processamento de Documentos Escaneados

Para documentos Categoria 1 que sao PDFs escaneados ou imagens:

```python
def extrair_texto_documento(file_path: str) -> str:
    """Extrai texto de PDF ou imagem."""
    # Tenta extracao direta primeiro (PDF com texto)
    text = extrair_texto_pdf(file_path)
    if text and len(text.strip()) > 50:
        return text

    # Fallback: Gemini Vision para OCR
    # Envia a imagem/pagina do PDF para o modelo multimodal
    # Prompt: "Extraia todo o texto deste documento juridico.
    #          Preserve a formatacao original. Identifique:
    #          tipo de documento, partes envolvidas, datas, valores."
    return extrair_via_vision(file_path)
```

**Custo:** Gemini Flash com vision e barato (~US$0.01 por pagina). Documentos longos (contratos de 30+ paginas) mostram estimativa de custo antes de processar.

**Importante:** O texto extraido e mostrado ao advogado para validacao antes de ser usado:
> "Extraimos o seguinte texto do documento. Esta correto?"
> [texto extraido]
> [Confirmar] [Corrigir manualmente]

Isso evita que OCR ruim contamine o caso silenciosamente.

### 10B.5 Decisao para MVP

No MVP:
- **Declaracao sempre funciona** â€” o advogado descreve o documento em texto
- **Upload aceito** â€” arrasta arquivo ou seleciona, salvo na pasta do caso
- **Extracao de texto** â€” apenas para PDFs com texto nativo (sem OCR/vision no MVP)
- **OCR/Vision** â€” pos-MVP (Gemini Vision), porque adiciona complexidade e custo

A excecao e a **contestacao**: o advogado PRECISA fornecer a peticao da parte contraria. Nesse caso, o upload e obrigatorio e a extracao de texto e essencial. Se for PDF escaneado, o MVP pode aceitar que o advogado cole o texto manualmente como alternativa ao OCR.

---

## 10C. Parecer Externo â€” Segunda Opiniao Verificada

### 10C.1 O Problema

Mesmo com loop adversarial robusto, o advogado pode querer colar a peticao em outra IA (ChatGPT, Gemini, etc.) para obter uma segunda opiniao independente. Se o sistema ignorar esse comportamento, o advogado faz por fora e perde confianca no Ratio quando a IA externa encontra algo que o sistema nao encontrou.

**Solucao: absorver o comportamento em vez de lutar contra ele.**

O Parecer Externo e uma funcionalidade opcional no loop adversarial que permite ao advogado exportar a peticao para revisao externa, importar a resposta, e ter cada afirmacao verificada contra a base real do Ratio.

### 10C.2 Fluxo Completo

```
PASSO 1 â€” Exportar (1 clique)
  |  Botao [Copiar para revisao externa]
  |  Sistema formata peticao + prompt adversarial otimizado
  |  Copia para area de transferencia
  |  Advogado cola no ChatGPT / Gemini / Claude
  |
PASSO 2 â€” Importar
  |  Botao [Importar Parecer Externo]
  |  Advogado cola a resposta crua da IA externa
  |  Campo de texto livre (aceita qualquer formato)
  |
PASSO 3 â€” Extracao de Claims
  |  LLM (Gemini Flash) parseia o texto e extrai claims discretos
  |  Cada claim e uma afirmacao verificavel
  |
PASSO 4 â€” Classificacao
  |  Para cada claim:
  |    - Cita fonte especifica? (sumula, artigo, julgado)
  |    - E argumento logico puro? (sem fonte)
  |    - E opiniao generica? ("argumento fraco")
  |
PASSO 5 â€” Verificacao via Ratio
  |  Claims com fonte citada:
  |    ratio_search(fonte) â†’ existe? texto bate?
  |    Se existe e bate: VALIDADO
  |    Se nao existe: ALUCINACAO
  |    Se existe mas diz coisa diferente: ALUCINACAO
  |
  |  Claims com argumento logico:
  |    ratio_search(tese contraria formulada)
  |    Se encontrou jurisprudencia sustentando: VALIDADO
  |    Se nao encontrou: NAO VERIFICADO
  |
  |  Claims genericos:
  |    OBSERVACAO (sem peso de evidencia)
  |
PASSO 6 â€” Dashboard
  |  Tabela com 4 status por claim
  |  Comparacao: Contraparte interna vs Parecer externo
  |  Overlap destacado
  |
PASSO 7 â€” Incorporacao
  |  Apenas claims VALIDADOS entram no loop adversarial
  |  Advogado confirma quais incorporar
```

### 10C.3 Schemas

```python
class ClaimExterno(BaseModel):
    """Uma afirmacao extraida do parecer externo."""
    texto_original: str              # Trecho do parecer que contem o claim
    fonte_citada: Optional[str]      # Ex: "Sumula 297 do STJ" (se citou)
    tipo_claim: Literal[
        "com_fonte",                 # Cita sumula/artigo/julgado especifico
        "argumento_logico",          # Argumento sem fonte, mas verificavel
        "opiniao_generica"           # "argumento fraco", sem fundamentacao
    ]

class ClaimVerificado(BaseModel):
    """Resultado da verificacao de um claim externo."""
    claim: ClaimExterno
    status: Literal[
        "validado",                  # Fonte confirmada ou argumento com lastro
        "nao_verificado",            # Sem lastro encontrado no Ratio
        "alucinacao",                # Fonte citada nao existe ou diz outra coisa
        "observacao"                 # Opiniao sem fonte, aceita como nota
    ]
    evidencia_ratio: Optional[str]   # Texto/ementa que comprova ou refuta
    docs_encontrados: List[str]      # IDs dos DocumentoColetado relevantes
    overlap_contraparte: bool        # A Contraparte interna ja tinha encontrado?
    explicacao: str                  # Ex: "Sumula 297 trata de FGTS, nao dano moral"

class ParecerExterno(BaseModel):
    """Parecer externo completo, apos verificacao."""
    fonte: str                       # "ChatGPT", "Gemini", "Outro"
    texto_bruto: str                 # Resposta crua colada pelo advogado
    claims: List[ClaimVerificado]
    resumo: Dict[str, int]           # {"validado": 2, "alucinacao": 1, ...}
    incorporados: List[str]          # IDs dos claims que o advogado aceitou
    timestamp: datetime
```

### 10C.4 Prompt de Exportacao

O sistema gera um prompt otimizado que e copiado junto com a peticao:

```
Voce e um advogado senior especialista em {area_direito}.
Analise a peticao abaixo com olhar critico e adversario.

Para cada problema encontrado, indique:
- Secao afetada (dos fatos, do direito, pedidos, etc.)
- Tipo: processual / material / logica / jurisprudencia fraca / outro
- Gravidade: alta / media / baixa
- Como a parte contraria usaria essa falha

Seja especifico. Cite numeros de sumulas, artigos de lei e julgados
quando fundamentar suas criticas.

---
PETICAO:
{peticao_completa}
---
```

### 10C.5 Integracao com o LangGraph

O Parecer Externo NAO e um no do grafo. E uma acao do usuario durante o `interrupt` do AdversarialGraph:

```python
@app.post("/api/escritorio/caso/{caso_id}/parecer-externo")
async def importar_parecer(caso_id: str, texto_bruto: str, fonte: str):
    """Importa parecer externo e verifica cada claim."""

    # Passo 1: Extrair claims via Gemini Flash
    claims = await extrair_claims(texto_bruto)

    # Passo 2: Verificar cada claim contra o Ratio
    claims_verificados = []
    for claim in claims:
        verificado = await verificar_claim(claim, caso_id)
        claims_verificados.append(verificado)

    # Passo 3: Montar o ParecerExterno
    parecer = ParecerExterno(
        fonte=fonte,
        texto_bruto=texto_bruto,
        claims=claims_verificados,
        resumo=contar_status(claims_verificados),
        incorporados=[],
        timestamp=datetime.now()
    )

    # Passo 4: Salvar no banco do caso
    salvar_parecer(caso_id, parecer)

    return parecer


async def verificar_claim(claim: ClaimExterno, caso_id: str) -> ClaimVerificado:
    """Verifica um claim individual contra a base do Ratio."""

    if claim.tipo_claim == "opiniao_generica":
        return ClaimVerificado(
            claim=claim,
            status="observacao",
            explicacao="Opiniao sem fonte especifica",
            docs_encontrados=[],
            overlap_contraparte=False
        )

    if claim.tipo_claim == "com_fonte" and claim.fonte_citada:
        # Busca exata da fonte citada
        resultado = verificar_citacao(claim.fonte_citada)
        if not resultado["existe"]:
            return ClaimVerificado(
                claim=claim,
                status="alucinacao",
                explicacao=f"'{claim.fonte_citada}' nao encontrada na base",
                docs_encontrados=[],
                overlap_contraparte=False
            )
        # Fonte existe â€” verificar se o texto bate com o que o claim alega
        consistente = await verificar_consistencia(
            claim.texto_original,
            resultado["texto_real"]
        )
        if not consistente:
            return ClaimVerificado(
                claim=claim,
                status="alucinacao",
                explicacao=f"'{claim.fonte_citada}' existe mas diz coisa diferente",
                evidencia_ratio=resultado["texto_real"],
                docs_encontrados=[resultado["doc_id"]],
                overlap_contraparte=False
            )
        return ClaimVerificado(
            claim=claim,
            status="validado",
            evidencia_ratio=resultado["texto_real"],
            docs_encontrados=[resultado["doc_id"]],
            overlap_contraparte=check_overlap(caso_id, claim)
        )

    # argumento_logico: busca se existe jurisprudencia sustentando
    answer, docs = run_query(
        query=claim.texto_original,
        return_meta=False
    )
    if docs and docs[0].get("_final_score", 0) > 0.5:
        return ClaimVerificado(
            claim=claim,
            status="validado",
            evidencia_ratio=docs[0].get("ementa", ""),
            docs_encontrados=[d["doc_id"] for d in docs[:3]],
            overlap_contraparte=check_overlap(caso_id, claim)
        )
    return ClaimVerificado(
        claim=claim,
        status="nao_verificado",
        explicacao="Sem lastro encontrado na base de jurisprudencia",
        docs_encontrados=[],
        overlap_contraparte=False
    )
```

### 10C.6 Incorporacao no Loop

Quando o advogado clica `[Incorporar Validados]`:

1. Claims validados sao convertidos em `FalhaCritica` (mesmo schema da Contraparte)
2. Adicionados ao `critica_atual` do state com flag `origem="parecer_externo"`
3. O Redator recebe na proxima rodada junto com as criticas da Contraparte
4. No dashboard, aparecem com badge distinto: "Parecer Externo" vs "Contraparte Ratio"

### 10C.7 Tabela SQL

```sql
-- Dentro do caso.db
CREATE TABLE pareceres_externos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte TEXT NOT NULL,              -- "ChatGPT", "Gemini", etc.
    texto_bruto TEXT NOT NULL,
    claims_json TEXT,                 -- List[ClaimVerificado] serializado
    resumo_json TEXT,                 -- {"validado": 2, "alucinacao": 1, ...}
    incorporados_json TEXT,           -- IDs dos claims aceitos
    rodada INTEGER,                   -- Em qual rodada adversarial foi importado
    created_at TEXT
);
```

---

## 11. Seguranca e Privacidade

### 11.1 PII Detection

Antes de enviar dados para APIs externas (Gemini, Claude), detectar e anonimizar:
- CPFs, CNPJs
- Enderecos
- Numeros de telefone
- Dados bancarios
- Nomes de partes (quando possivel)

Usar regex + heuristica para deteccao. Substituir por placeholders (`[CPF_1]`, `[ENDERECO_1]`). Re-substituir no output final.

### 11.2 Dados Locais

- Todos os dados do caso ficam no SQLite do caso (pasta isolada)
- Jurisprudencia e legislacao indexadas no LanceDB global (compartilhado entre casos)
- Documentos do cliente ficam na pasta do caso â€” nunca saem da maquina
- Unico trafego externo: chamadas de API para LLMs (Gemini, Claude)
- Explicitar ao usuario quais dados sao enviados para APIs externas
- Documentos uploadados NUNCA sao enviados para APIs externas sem consentimento explicito

---

## 12. Saida DOCX

### 12.1 Padrao de Formatacao Forense Brasileiro

| Elemento | Padrao | Implementacao python-docx |
|---|---|---|
| Fonte | Times New Roman 12pt | `style.font.name = 'Times New Roman'`; `style.font.size = Pt(12)` |
| Espacamento | 1,5 entre linhas | `style.paragraph_format.line_spacing = 1.5` |
| Margens | 3cm esq/sup, 2cm dir/inf | `section.left_margin = Cm(3)` etc. |
| Paragrafos | Recuo 2cm primeira linha | `style.paragraph_format.first_line_indent = Cm(2)` |
| Numeracao | Paginas no rodape (campo PAGE) | XML field code `w:fldChar` + `PAGE` |
| Cabecalho | Dados do processo | `section.header.paragraphs[0]` |
| Vocativo | Configuravel por escritorio | Template parametrizado |

### 12.2 Implementacao do Formatador

```python
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


class FormatadorPeticao:
    """Gera DOCX nos padroes forenses brasileiros."""

    def __init__(self):
        self.doc = Document()
        self._setup_documento()

    def _setup_documento(self):
        """Configura margens, fonte e espacamento globais."""
        # Margens: 3cm esq/sup, 2cm dir/inf
        for section in self.doc.sections:
            section.left_margin = Cm(3)
            section.top_margin = Cm(3)
            section.right_margin = Cm(2)
            section.bottom_margin = Cm(2)

        # Estilo Normal: Times New Roman 12pt, espacamento 1.5, recuo 2cm
        style = self.doc.styles['Normal']
        style.font.name = 'Times New Roman'
        style.font.size = Pt(12)
        style.paragraph_format.line_spacing = 1.5
        style.paragraph_format.first_line_indent = Cm(2)

        # Headings: Times New Roman bold, sem recuo
        for level in range(1, 4):
            h = self.doc.styles[f'Heading {level}']
            h.font.name = 'Times New Roman'
            h.font.bold = True
            h.font.size = Pt(14 if level == 1 else 12)
            h.font.color.rgb = RGBColor(0, 0, 0)
            h.paragraph_format.first_line_indent = Cm(0)

    def add_cabecalho(self, tribunal: str, vara: str, processo: str):
        """Cabecalho com dados do juizo."""
        header = self.doc.sections[0].header
        header.paragraphs[0].text = ''
        p = header.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r1 = p.add_run(f'{tribunal}\n')
        r1.font.name = 'Times New Roman'
        r1.font.size = Pt(11)
        r1.bold = True
        r2 = p.add_run(f'{vara}\n')
        r2.font.name = 'Times New Roman'
        r2.font.size = Pt(10)
        r3 = p.add_run(f'Processo: {processo}')
        r3.font.name = 'Times New Roman'
        r3.font.size = Pt(10)

    def add_numeracao_paginas(self):
        """Adiciona campo PAGE no rodape (renderizado pelo Word)."""
        for section in self.doc.sections:
            footer = section.footer
            p = footer.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run()
            fld_begin = OxmlElement('w:fldChar')
            fld_begin.set(qn('w:fldCharType'), 'begin')
            run._element.append(fld_begin)
            instr = OxmlElement('w:instrText')
            instr.set(qn('xml:space'), 'preserve')
            instr.text = "PAGE"
            run._element.append(instr)
            fld_end = OxmlElement('w:fldChar')
            fld_end.set(qn('w:fldCharType'), 'end')
            run._element.append(fld_end)

    def add_secao(self, titulo: str, conteudo: str):
        """Adiciona uma secao da peticao (DOS FATOS, DO DIREITO, etc.)."""
        self.doc.add_heading(titulo, level=1)
        self.doc.add_paragraph(conteudo)

    def add_citacao(self, texto: str, verificada: bool = True):
        """Formata citacao: verificada (bold+italic) ou nao (highlight amarelo)."""
        p = self.doc.add_paragraph()
        run = p.add_run(texto)
        run.font.name = 'Times New Roman'
        run.font.size = Pt(12)
        if verificada:
            run.bold = True
            run.italic = True
        else:
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            # Adiciona marcador [VERIFICAR]
            marker = p.add_run(' [VERIFICAR]')
            marker.font.name = 'Times New Roman'
            marker.font.size = Pt(12)
            marker.font.bold = True
            marker.font.color.rgb = RGBColor(255, 0, 0)
            marker.font.highlight_color = WD_COLOR_INDEX.YELLOW

    def gerar(self, state: 'RatioEscritorioState', verificacoes: list) -> str:
        """Gera o DOCX final a partir do state e verificacoes."""
        # Cabecalho (se houver dados do processo)
        if state.caso_id:
            self.add_cabecalho(
                tribunal="",  # Determinado pela area/juizo
                vara="",
                processo=state.caso_id
            )

        # Secoes dinamicas
        for titulo, conteudo in state.peca_sections.items():
            self.add_secao(titulo.upper().replace("_", " "), conteudo)

        # Numeracao de paginas
        self.add_numeracao_paginas()

        # Salvar
        filepath = f"casos/{state.caso_id}/output/peticao_final.docx"
        self.doc.save(filepath)
        return filepath
```

### 12.3 Formatacao Diferenciada de Citacoes

| Status da citacao | Formatacao visual |
|---|---|
| Confirmada (exact/strong match) | Bold + italic, cor preta |
| Nao verificada (weak match) | Highlight amarelo + `[VERIFICAR]` vermelho |
| Nao encontrada (unverified) | Highlight amarelo + `[NAO VERIFICADO]` vermelho |

Isso garante que o advogado identifique visualmente no DOCX final quais citacoes precisam de revisao manual antes de protocolar.

### 12.4 Limitacoes do python-docx

| Feature | Status | Workaround |
|---|---|---|
| Numeracao de paginas | Parcial | Campo XML `PAGE` (Word renderiza ao abrir) |
| Sumario automatico | Parcial | Campo XML `TOC` (Word gera ao abrir) |
| Margens/fonte/espacamento | Completo | API nativa |
| Bold/italic/highlight | Completo | API nativa |
| Header/footer | Completo | API nativa |

### 12.5 Pacote Final

- Peticao/contestacao formatada (.docx) com citacoes coloridas por status
- Relatorio de verificacao de citacoes (inline no DOCX ou anexo separado)
- Custo total detalhado por etapa
- Opcao: Dossie de pesquisa como anexo (secao 9.6.6)

---

## 13. Stack Tecnologico

| Camada | Tecnologia | Justificativa |
|---|---|---|
| Orquestracao | LangGraph | Ciclos nativos, state, HITL, checkpointing |
| Sub-grafos | IntakeGraph, DraftingGraph, AdversarialGraph | Evita God Graph |
| Modelo (redacao) | Gemini Pro | Melhor qualidade de texto em portugues |
| Modelo (operacional) | Gemini Flash | Rapido e barato para intake/pesquisa |
| Modelo (critica) | Claude | Melhor raciocinio critico/adversarial |
| Jurisprudencia | Ratio (run_query) | Busca hibrida + rerank ja existente |
| Legislacao | Gemini Search + Planalto | Dinamico + pre-indexado |
| Frontend (novo) | React | SPA nova aba, coexiste com frontend atual |
| Backend | FastAPI (existente) | Novos endpoints para escritorio |
| Streaming | SSE (MVP) | Simples, reconexao automatica |
| Persistencia | SQLite | Local, sem dependencias externas |
| Saida | python-docx | Formatacao DOCX programatica |
| Schemas | Pydantic | Validacao, tipagem, serializacao |

---

## 14. Quality Assurance

### 14.1 Arquitetura de Testes em 3 Camadas

**Camada 1 â€” Unit Tests (comportamento individual de cada agente):**

| Agente | Dataset | Metrica principal | Target |
|---|---|---|---|
| Contraparte | 20-30 peticoes reais com falhas documentadas | Precisao + recall de deteccao de falhas | P > 0.80, R > 0.75 |
| Pesquisador | 10-15 casos-marco com jurisprudencia mapeada | Cobertura de jurisprudencia relevante | > 80% |
| Redator | 5-10 casos com estrutura esperada | Coerencia logica (LLM-as-Judge, 1-5) | > 3.5/5 |
| Verificador | 100+ citacoes (corretas, erradas, fabricadas) | Precisao/recall de verificacao | P > 0.95, R > 0.90 |

**Camada 2 â€” Integration Tests (pipeline ponta a ponta):**
- Caso completo rodando todos os agentes em sequencia
- Verificar que output final e coerente e defensavel
- Medir tempo total e custo total

**Camada 3 â€” Adversarial Tests:**
- Injetar contradicoes sutis nos fatos
- Usar argumentos juridicos deliberadamente fracos
- Testar com fatos incompletos ou ambiguos
- Medir graceful degradation (sistema deve sinalizar, nao inventar)

### 14.2 Metricas por Agente

**Contraparte:**
- **Flaw Detection Precision:** TP / (TP + FP) â€” % das falhas apontadas que sao reais
- **Flaw Detection Recall:** TP / (TP + FN) â€” % das falhas reais que foram encontradas
- **Severity Calibration:** Correlacao de Spearman entre gravidades atribuidas e labels de especialista
- **False Alarm Rate:** Quantas falhas inexistentes sao apontadas? (target < 10%)

**Verificador:**
- **Citation Detection Precision:** % das citacoes detectadas que sao validas
- **Citation Detection Recall:** % das citacoes reais que foram encontradas
- **Citation Accuracy:** Extracao correta de classe, numero, tribunal, ano
- **Hallucination Detection Rate:** % das citacoes fabricadas corretamente identificadas como inexistentes

**Pesquisador:**
- **Jurisprudence Coverage:** % da jurisprudencia relevante que deveria ser citada mas nao foi
- **Thesis Decomposition Quality:** Identificou 3-5 teses juridicas distintas? (LLM-as-Judge)
- **Precedent-Thesis Linking:** Para cada tese, os casos citados sao realmente relevantes?

**Redator:**
- **Logical Coherence:** Fluxo argumentativo logico (LLM-as-Judge, rubrica)
- **Argumentative Strength:** Premissas adequadamente sustentadas
- **Completeness:** Todos os pontos juridicos relevantes abordados
- **Hallucination Rate:** Citacoes no texto que nao existem no dossie de pesquisa

### 14.3 Evaluation Harness â€” Casos de Teste

Dataset de referencia com saidas esperadas:

| # | Caso | Armadilha inserida | Contraparte deve encontrar | Verificador deve detectar |
|---|---|---|---|---|
| 1 | Dano moral consumerista | Prescricao vencida | Prescricao + prazo CDC | Sumula 548 existe |
| 2 | Usucapiao extraordinaria | Posse sem justo titulo | Falta justo titulo + boa-fe | Art. 1238 CC existe |
| 3 | Rescisao trabalhista | Justa causa sem advertencia previa | Falta gradacao punitiva | Sumula 443 TST |
| 4 | Responsabilidade medica | Inversao de onus indevida | CDC vs CC (relacao contratual) | Art. 14 CDC vs Art. 951 CC |
| 5 | Dano moral bancario | Citacao fabricada (REsp inexistente) | Argumento sem lastro | `unverified` para REsp falso |

Cada caso inclui:
- Fatos de entrada (input pro Intake)
- Ground truth: falhas que a Contraparte DEVE encontrar
- Ground truth: citacoes corretas e incorretas para o Verificador
- Ground truth: secoes esperadas do Redator

### 14.4 Deteccao de Prompt Drift

**Baseline:**
1. Rodar suite completa contra modelo/prompt atual
2. Registrar todas as metricas em JSON versionado:

```json
{
  "model": "gemini-2.5-flash",
  "prompt_version": "v1.0",
  "date": "2026-04-06",
  "contraparte_precision": 0.87,
  "contraparte_recall": 0.82,
  "verificador_precision": 0.94,
  "verificador_recall": 0.91,
  "pesquisador_coverage": 0.85,
  "redator_coherence": 4.1
}
```

**Drift Detection (semanal ou a cada update de modelo/prompt):**
1. Rodar mesma suite no novo modelo/prompt
2. Comparar metricas: degradacao > 5% = YELLOW, > 10% = RED
3. Comparar trajetorias de raciocinio: agente mudou ordem de tool calls?
4. 3+ casos de teste com reasoning diferente = drift confirmado

**Template de Relatorio de Drift:**

```
MODEL UPDATE: gemini-2.5-flash â†’ gemini-3.0-flash
Date: 2026-XX-XX

METRIC CHANGES:
- Contraparte precision: 0.87 â†’ 0.84 (YELLOW: -3.4%)
- Contraparte recall: 0.82 â†’ 0.78 (RED: -4.9%)
- Verificador precision: 0.94 â†’ 0.93 (GREEN: -1%)

TRAJECTORY DRIFT:
- Agente agora chama tool X antes de tool Y
- 3/50 casos mudaram raciocinio mas mantiveram output

RECOMMENDATION: Monitorar / Rollback de prompt
```

### 14.5 Framework Recomendado

| Framework | Uso | Custo | Prazo de setup |
|---|---|---|---|
| **LangSmith** (primario) | Captura trajetoria completa, UI de debug, comparacao entre experimentos | Free tier â†’ $20-40/mes | 2-3 dias |
| **DeepEval** (secundario) | Metricas customizadas juridicas, integracao CI/CD, interface pytest-like | Open source | 1-2 dias |
| **RAGAS** (opcional) | Avaliacao especifica de retrieval (citation quality) | Open source | 1 dia |

**Integracao no CI:**

```python
# eval_suite.py â€” roda no CI a cada commit que toca prompts
from langsmith import Client
from langsmith.evaluation import evaluate

client = Client()
dataset = client.read_dataset(dataset_name="ratio_escritorio_test_v1")

def eval_contraparte_precision(output, expected):
    """Precisao: % das falhas apontadas que sao reais."""
    real = {f["id"] for f in expected["falhas"]}
    found = {f["id"] for f in output.get("falhas", [])}
    if not found:
        return {"score": 0}
    return {"score": len(found & real) / len(found)}

results = evaluate(
    lambda x: contraparte_agent(x["peticao"]),
    data=dataset,
    evaluators=[eval_contraparte_precision],
)
# LangSmith UI: comparar runs, ver diferencas por caso
```

### 14.6 Testes de Regressao

Suite automatizada que roda antes de cada release:

- **Peticoes defeituosas** intencionais para testar Contraparte (5 peticoes com falhas conhecidas)
- **Citacoes fabricadas** para testar Verificador (20 citacoes: 10 reais, 5 erradas, 5 inventadas)
- **Artigos revogados** para testar integracao de legislacao (3 artigos revogados, 3 vigentes)
- **Pipeline completo** em 2 casos de referencia (dano moral + usucapiao): resultado deve ser >= baseline

**Checklist pre-release:**
- [ ] Todas as metricas >= baseline (nenhuma RED)
- [ ] 0 citacoes fabricadas passaram como "confirmada"
- [ ] Pipeline completo em < 5 min e < R$5 por caso de teste
- [ ] Nenhuma regressao no Verificador (precisao >= 0.95)

---

## 15. Roadmap de Implementacao

### 15.0 Status Real do Branch (2026-04-06)

| Frente | Status real | Observacao |
|---|---|---|
| Fundacao backend-first | IMPLEMENTADO | estrutura modular, persistence, tools, workflow minimo e API base |
| Intake / ciclo do caso | IMPLEMENTADO | state, checklist, eventos, gates e endpoints |
| Adversarial loop backend-first | IMPLEMENTADO | critica, anti-sycophancy, dismiss, revisao e payload filtrado |
| DraftingGraph completo com pesquisa por tese | PENDENTE | ainda falta integrar pesquisador/redator reais do Escritorio |
| Verificador deterministico | PENDENTE | ainda nao existe pipeline de 5 camadas em codigo |
| Formatador DOCX | PENDENTE | ainda nao existe modulo de entrega final |
| Frontend React do Escritorio | PENDENTE | backend-first mantido ate aqui |

### 15.1 Andamento Consolidado (2026-04-06)

- Fase 1: majoritariamente implementada
  ratio_tools.py, workflow minimo, router do Escritorio, store SQLite, state, intake/ciclo de caso e testes ja existem
- Fase 2: parcialmente implementada
  loop adversarial backend-first, dismiss humano, revisao por secao e anti-sycophancy ja existem; faltam pesquisador/redator reais e verificador
- Fase 3: nao iniciada
- Fase 4: nao iniciada

### Fase 1 â€” Fundacao (Semanas 1-3)
| Semana | Entrega |
|---|---|
| 1 | `ratio_tools.py` â€” wrappers sobre `run_query()`. Testar isoladamente. |
| 2 | Setup LangGraph + grafo minimo 3 nos (Pesquisador -> Redator -> Verificador) rodando no terminal. |
| 3 | IntakeGraph com chat dinamico. Gemini Flash para classificacao + perguntas. |

### Fase 2 â€” Pipeline Completo (Semanas 4-6)

| Semana | Entrega |
|---|---|
| 4 | DraftingGraph completo: Estrategista + Pesquisador por tese + Redator por secoes. |
| 5 | AdversarialGraph: Contraparte (Claude) + loop + anti-sycophancy + interrupt. |
| 6 | Verificador deterministico + Formatador DOCX + integracao legislacao (Planalto pre-indexado). |

### Fase 3 â€” Frontend React (Semanas 7-10)

| Semana | Entrega |
|---|---|
| 7 | Setup React na nova aba. Tela "Meus Casos" + persistencia SQLite. |
| 8 | Dashboard de cards + editor de secoes (3 colunas). |
| 9 | Streaming SSE + burn meter + botoes rapidos de apontamento. |
| 10 | Integracao completa + gates humanos + contestacao (polaridade invertida). |

### Fase 4 â€” Polimento (Semanas 11-12)

| Semana | Entrega |
|---|---|
| 11 | PII detection, semantic caching, evaluation harness. |
| 12 | Testes com advogados reais, ajuste de prompts, empacotamento. |

**Total estimado: 12 semanas para MVP funcional.**

---

## 16. Decisoes Tecnicas Registradas

| # | Decisao | Alternativas consideradas | Justificativa |
|---|---|---|---|
| 1 | LangGraph para orquestracao | CrewAI, Autogen, Python puro | Ciclos nativos, state, HITL, checkpointing |
| 2 | Importacao direta do Ratio (nao HTTP) | API REST, MCP | Sem latencia, mesmo processo, MVP |
| 3 | Gemini Pro + Flash + Claude | Modelo unico | Diversidade real entre agentes |
| 4 | React para frontend novo | Vue, Svelte, vanilla JS | Ecossistema, componentizacao, streaming |
| 5 | SSE + POST (nao WebSocket) | WebSocket | Mais simples, suficiente para MVP |
| 6 | SQLite (nao PostgreSQL) | PostgreSQL, MongoDB | Local, zero config, suficiente |
| 7 | Planalto pre-indexado + Gemini Search | Scraping real-time, LexML | LexML sem API, scraping fragil |
| 8 | Sectioned state (Dict[str,str]) | Blob unico | Economia de tokens, edicao parcial |
| 9 | Sub-grafos separados | Grafo unico | Debug, manutenibilidade |
| 10 | Contraparte com Claude | Mesmo modelo | Melhor raciocinio critico |
| 11 | Verificacao em camadas (nao regex puro) | Regex, LLM | Cobertura + confiabilidade |
| 12 | Nome: "Ratio Escritorio" | "Law Office", "Ratio Pro" | Publico brasileiro, identidade |

---

## 17. Riscos e Mitigacoes

| Risco | Probabilidade | Impacto | Mitigacao |
|---|---|---|---|
| Alucinacao de citacoes | Alta | Critico | Verificacao deterministica + `[NAO VERIFICADO]` |
| Contraparte complacente | Media | Alto | Anti-sycophancy + rejeicao interna + Claude |
| Planalto muda layout | Baixa | Medio | Pre-indexacao + fallback Gemini Search |
| Custo excessivo por peca | Media | Alto | Burn meter + estimativa previa + budget controls |
| Prompt drift (modelo atualiza) | Media | Alto | Evaluation harness + versionamento de prompts |
| RAM insuficiente (local) | Baixa | Alto | Testar em maquinas minimas + otimizar |
| SQLite concorrencia | Baixa | Medio | WAL mode + processo unico |
| Advogado nao confia no sistema | Media | Critico | Transparencia total + proveniencia + gates |

---

## Apendice A â€” Creditos de Revisao

Este documento foi produzido em sessao colaborativa com 4 perspectivas de IA:

- **Claude Opus 4.6**: Arquitetura principal, analise do codebase, consolidacao
- **Gemini 3.1 Pro**: Refatoracao do monolito, deploy local, verificacao deterministica, schema de state, WebSocket vs SSE
- **Gemini 2.5 Flash**: Prompt engineering adversarial, Chain of Thought, evaluation harness, reflection pattern, progressive disclosure
- **GPT-5.4**: Pesquisa guiada por tese, gates obrigatorios, dependencias entre secoes, proveniencia por paragrafo, verificacao em camadas, botoes rapidos, burn meter com projecao

Cada insight foi avaliado criticamente e incorporado apenas quando adicionava valor real ao desenho.

---

## Apendice B â€” Revisao Final (Gemini 3.1 Pro Preview, 2026-04-06)

Review completa em `docs/reviews/review_gemini_3.1_pro.md`.

### Falhas Criticas Identificadas (resolver antes do primeiro deploy)

| # | Falha | Secao | Solucao proposta | Status |
|---|---|---|---|---|
| 1 | **Explosao de contexto no loop adversarial** ? `RatioEscritorioState` acumula historico completo, estoura janela do LLM na rodada 3+ | 5.2 | State Trimming: `redator_revisao_node` recebe apenas versao atual + critica da rodada + resumo condensado das rodadas anteriores | IMPLEMENTADO na foundation (`build_redator_revision_payload` + payload filtrado da revisao humana) |
| 2 | **Gargalo de latencia nas Tools** ? 12+ chamadas sequenciais de tool por caso, timeout e rate limits | 6.2 | `asyncio.gather` para chamadas independentes + exponential backoff com jitter no `ratio_tools.py` | PARCIAL ? primitives implementadas em `ratio_tools.py`; falta ligar no pesquisador real por tese |
| 3 | **Prompt injection no Parecer Externo** ? texto livre colado pelo usuario pode conter instrucoes maliciosas | 10C | Isolar texto com delimitadores estritos, `temperature=0`, schema de saida forcado | IMPLEMENTADO na camada `security.py` |
| 4 | **Concorrencia no LanceDB** ? FastAPI async + multiplos agentes acessando banco vetorial simultaneamente | 6.2 | Singleton thread-safe para conexao LanceDB, read-only durante fluxo do grafo | IMPLEMENTADO via `LanceDBReadonlyRegistry` |

### Riscos Nao Cobertos (adicionar ao documento)

| # | Risco | Mitigacao sugerida |
|---|---|---|
| 1 | Upload de PDFs gigantes (300+ pags com anexos) engasga o Intake | RAG local + sumarizacao em chunks para docs de entrada do usuario |
| 2 | Redator sobrescreve estilo pessoal do advogado ao revisar secoes editadas manualmente | Instrucao de "preservar ancoras de texto humano" no prompt do Redator |
| 3 | Queda de conexao no meio do streaming perde geracao parcial (checkpoint so salva ao final do no) | Checkpoint intermediario ou buffer de streaming com recovery |

### Sugestoes de Melhoria Aceitas

| # | Sugestao | Prioridade | Fase |
|---|---|---|---|
| 1 | Veto humano em criticas individuais (dismiss antes do Redator processar) | Alta | MVP |
| 2 | Analise de ementa em background (async) para top 3 docs por tese | Media | MVP |
| 3 | Peso temporal no reranker (recency bias â€” 2024 > 2014) | Media | MVP |
| 4 | Diff visual real no editor (diff-match-patch, insercoes verde/delecoes riscado) | Alta | Fase 3 |

### Atualizacao de Implementacao (2026-04-06)
- Veto humano em criticas individuais: implementado no backend-first via dismiss por `finding_id`
- Peso temporal no reranker: implementado na tool layer
- Analise de ementa em background: pendente
- Diff visual real no editor: pendente
- Preservacao de ancoras humanas: parcialmente encaminhada via preserve_human_anchors=True no payload de revisao; prompt final do Redator ainda pendente

### Veredicto

> "Este e um dos documentos de arquitetura para IA juridica mais maduros e bem fundamentados que ja avaliei. [...] Esta pronto para implementacao, com a condicao estrita de que as falhas criticas de gerenciamento de estado (context overflow) e concorrencia de tools sejam resolvidas antes do primeiro deploy."
>
> â€” Gemini 3.1 Pro Preview, 2026-04-06

---

## Apendice C — Plano de Implementacao Fase 2 (pos-foundation)

**Data:** 2026-04-06
**Pre-requisito:** branch `codex/ratio-escritorio-foundation` merged em main
**Autor:** Claude Opus 4.6 (review da foundation do Codex)

### C.0 Contexto e Objetivo

A Fase 1 (foundation) entregou: schemas Pydantic, store SQLite, intake heuristico, loop adversarial backend-first, ratio_tools async com retry/jitter, LanceDB singleton, security isolation, e API REST completa com 10 endpoints.

A Fase 2 transforma os stubs em agentes reais: LLMs chamando tools, grafo com ciclos, verificador completo, e DOCX final. Ao final da Fase 2, o pipeline roda ponta a ponta no terminal (sem frontend).

### C.1 Divergencias da Foundation vs Plano (corrigir primeiro)

Estas divergencias devem ser resolvidas ANTES de prosseguir com nos reais, pois afetam a estrutura base.

#### C.1.1 Store centralizado → SQLite por caso

**Problema:** O plano (Secao 10.1) exige um SQLite por caso em `casos/{caso_id}/caso.db`. A foundation usa um banco unico `escritorio_cases.db`. Isso impede backup/export individual, delecao limpa, e compartilhamento de casos.

**Arquivos afetados:**
- `backend/escritorio/store.py` — refatorar `EscritorioStore` para receber `caso_dir` ao inves de `db_path` global
- `backend/escritorio/api.py` — `_resolve_escritorio_db_path()` vira `_resolve_case_dir(caso_id)`
- Todos os testes em `tests/escritorio/test_case_store.py`, `test_case_cycle.py`, `test_case_api.py`

**Mudanca concreta:**

```python
# ANTES (foundation)
class EscritorioStore:
    def __init__(self, db_path: str | Path):  # banco unico
        ...

# DEPOIS (fase 2)
class CaseStore:
    “””Um store por caso — isolamento total.”””
    def __init__(self, case_dir: str | Path):
        self.case_dir = Path(case_dir)
        self.db_path = self.case_dir / “caso.db”
        self.docs_dir = self.case_dir / “docs”
        self.output_dir = self.case_dir / “output”
        # criar dirs se nao existem
        ...

class CaseIndex:
    “””Indice global leve — so metadados para tela 'Meus Casos'.”””
    def __init__(self, index_path: str | Path):
        self.db_path = Path(index_path) / “index.db”
        # tabela unica: casos_index(id, nome, tipo_peca, status, path, created_at, updated_at)
        ...
```

**Estrutura de diretorios resultante:**
```
ratio_escritorio/
├── index.db                         ← CaseIndex (lista de casos)
├── casos/
│   ├── caso_047_silva_v_banco_x/
│   │   ├── caso.db                  ← CaseStore (state, snapshots, events)
│   │   ├── docs/                    ← uploads do cliente
│   │   └── output/                  ← DOCX gerado, versoes
│   └── caso_048_.../
```

**Impacto na API:** Os endpoints `GET /cases` usam `CaseIndex`. Todos os endpoints `/{caso_id}/...` resolvem o `CaseStore` do caso especifico.

#### C.1.2 StateGraph(dict) → StateGraph(RatioEscritorioState)

**Problema:** `graph/workflows.py` usa `StateGraph(dict)`, perdendo validacao Pydantic. O plano (Secao 5.2) usa `StateGraph(RatioEscritorioState)`.

**Mudanca:** Substituir `StateGraph(dict)` por `StateGraph(RatioEscritorioState)` nos 3 sub-grafos. Os nos recebem e retornam `RatioEscritorioState` (ou dicts parciais que o LangGraph mergeia).

```python
# graph/workflows.py
from backend.escritorio.models import RatioEscritorioState

def build_adversarial_graph():
    graph = StateGraph(RatioEscritorioState)
    # ...nos e edges...
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=[“pausa_humana”]
    )
```

#### C.1.3 Tools sem @tool decorator

**Problema:** `ratio_tools.py` define funcoes async puras. O LangGraph precisa de `@tool` do `langchain_core.tools` para `bind_tools()` e `ToolNode`.

**Solucao:** Manter as funcoes atuais como logica interna (sao boas). Criar wrappers `@tool` em arquivo separado:

**Novo arquivo: `backend/escritorio/tools/langchain_tools.py`**

```python
from langchain_core.tools import tool
from backend.escritorio.tools.ratio_tools import ratio_search, search_tese_bundle
import asyncio

@tool
def buscar_jurisprudencia_favoravel(
    query: str,
    tese: str,
    tribunais: list[str] | None = None,
    limite: int = 10,
) -> list[dict]:
    “””Busca acordaos e decisoes favoraveis a uma tese juridica especifica.
    Use quando precisar encontrar jurisprudencia que SUSTENTE um argumento.

    Args:
        query: Descricao da situacao fatica ou argumento a fundamentar.
        tese: A tese juridica que se busca sustentar.
        tribunais: Tribunais para filtrar (ex: [“STJ”, “STF”, “TJSP”]).
        limite: Numero maximo de resultados.

    Returns:
        Lista de documentos com processo, tribunal, ementa, relator, score.
    “””
    result = asyncio.run(ratio_search(
        f”{tese}: {query}”,
        tribunais=tribunais,
        prefer_recent=True,
        persona=”parecer”,
    ))
    return result[“docs”][:limite]


@tool
def buscar_jurisprudencia_contraria(
    query: str,
    tese: str,
    tribunais: list[str] | None = None,
    limite: int = 5,
) -> list[dict]:
    “””Busca acordaos que ENFRAQUECEM ou CONTRARIAM uma tese juridica.
    Use quando precisar mapear riscos ou argumentos da parte contraria.

    Args:
        query: Descricao do argumento a atacar.
        tese: A tese que se busca refutar.
        tribunais: Tribunais para filtrar.
        limite: Numero maximo de resultados.

    Returns:
        Lista de documentos contrarios.
    “””
    result = asyncio.run(ratio_search(
        f”jurisprudencia contraria a: {tese}. Situacao: {query}”,
        tribunais=tribunais,
        prefer_recent=True,
        persona=”parecer”,
    ))
    return result[“docs”][:limite]


@tool
def buscar_legislacao(termos: str, codigo: str | None = None) -> list[dict]:
    “””Busca artigos de lei, codigos e legislacao.

    Args:
        termos: Descricao do que se busca (ex: “prazo prescricional dano moral”).
        codigo: Codigo especifico se souber (ex: “CC”, “CPC”, “CDC”, “CF”).

    Returns:
        Lista de artigos com lei, artigo, texto.
    “””
    # Camada 1: busca via ratio_search com filtro de legislacao
    result = asyncio.run(ratio_search(
        f”{codigo + ': ' if codigo else ''}{termos}”,
        persona=”parecer”,
    ))
    return result[“docs”][:10]


@tool
def verificar_citacao(referencia: str) -> dict:
    “””Verifica se uma citacao juridica existe na base real.
    NAO usa LLM — verificacao deterministica.

    Args:
        referencia: Citacao a verificar (ex: “REsp 1.059.663/MS”, “Sumula 548 do STJ”).

    Returns:
        Dict com: existe (bool), nivel_match, texto_real, metadados.
    “””
    from backend.escritorio.verifier import extract_citation_candidates
    candidates = extract_citation_candidates(referencia)
    if not candidates:
        return {“existe”: False, “nivel”: “unverified”, “referencia”: referencia}
    # TODO: match contra LanceDB na fase de verificador completo
    return {
        “existe”: False,
        “nivel”: “unverified”,
        “referencia”: referencia,
        “candidates”: [c.model_dump() for c in candidates],
    }


@tool
def buscar_acervo(query: str, limite: int = 5) -> list[dict]:
    “””Busca no acervo privado do usuario (PDFs importados).

    Args:
        query: Texto da busca.
        limite: Numero maximo de resultados.

    Returns:
        Lista de documentos do acervo do usuario.
    “””
    result = asyncio.run(ratio_search(
        query,
        sources=[“user”],
        prefer_recent=False,
    ))
    return result[“docs”][:limite]


# ── Binding por agente ──

TOOLS_PESQUISADOR = [
    buscar_jurisprudencia_favoravel,
    buscar_jurisprudencia_contraria,
    buscar_legislacao,
    buscar_acervo,
]

TOOLS_CONTRAPARTE = [
    buscar_jurisprudencia_contraria,
    buscar_legislacao,
]
```

---

### C.2 Implementacao dos 3 Sub-Grafos Reais

Apos as correcoes de C.1, implementar os grafos com ciclos e interrupts conforme o plano (Secoes 5.4–5.6).

#### C.2.1 IntakeGraph (reescrever `graph/workflows.py`)

**Arquivo:** `backend/escritorio/graph/intake_graph.py`

```
START → intake_node → classificacao_node → gate1 (interrupt_before)
                                              ↓
                                         gate1_router
                                        /           \
                                   “intake”      “drafting” → END
                                   (volta)
```

**Detalhes do `intake_node`:**
- Usa Gemini Flash para gerar perguntas dinamicas (substituir o intake heuristico atual por LLM)
- Recebe: `fatos_brutos`, `intake_history`
- Retorna: `fatos_estruturados`, `provas_disponiveis`, `pontos_atencao`, `intake_checklist`
- O checklist heuristico atual (`intake.py`) continua como FALLBACK se a LLM falhar
- Temperature: 0.4

**Preservar:** A logica de `compute_checklist()` e `checklist_ready()` em `intake.py` — usar como validacao pos-LLM (a LLM gera perguntas, mas o checklist heuristico decide se pode avancar).

**interrupt_before:** `[“gate1”]` — o grafo PAUSA antes do gate1. O frontend (ou o terminal no MVP) mostra o dossie e espera aprovacao.

#### C.2.2 DraftingGraph

**Arquivo:** `backend/escritorio/graph/drafting_graph.py`

```
START → pesquisador_node → curadoria_node → gate2 (interrupt_before)
                                               ↓
                                          gate2_router
                                         /           \
                                  “buscar_mais”    “redigir”
                                  (volta pesq.)       ↓
                                                 redator_node → END
```

**Detalhes do `pesquisador_node`:**
- Modelo: Gemini Flash com `bind_tools(TOOLS_PESQUISADOR)`
- Prompt de sistema conforme Secao 4.2 (Agente 2)
- Executa ReAct loop: decompoe em teses → para cada tese chama `buscar_jurisprudencia_favoravel`, `contraria`, `buscar_legislacao`
- Usa `search_tese_bundle()` (ja implementado com asyncio.gather) para paralelizar buscas por tese
- Escreve: `teses[]`, `pesquisa_jurisprudencia[]`, `pesquisa_legislacao[]`
- ToolNode: `ToolNode(TOOLS_PESQUISADOR)` com conditional edge “has_tool_calls → tools → pesquisador” loop

**Detalhes do `curadoria_node`:**
- Codigo puro (sem LLM): ranqueia resultados por tese, remove duplicatas, calcula confianca
- Usa `merge_ranked_results()` de `ratio_tools.py`

**Detalhes do `redator_node`:**
- Modelo: Gemini Pro (raciocinio profundo)
- Temperature: 0.2
- Prompt conforme Secao 4.2 (Agente 3)
- Recebe: fatos + teses + pesquisa curada
- NAO tem tools (so escreve com o que recebeu)
- Escreve: `peca_sections: Dict[str, str]` com secoes dinamicas

#### C.2.3 AdversarialGraph (o ciclo principal)

**Arquivo:** `backend/escritorio/graph/adversarial_graph.py`

```
START → contraparte_node → anti_sycophancy_node
                               ↓
                          sycophancy_router
                         /              \
                    “rejeita”       “aceita”
                    (volta          ↓
                     contraparte,   pausa_humana (interrupt_before)
                     max 2x)            ↓
                                   decisao_router
                                  /              \
                            “mais_rodada”    “finalizar”
                                 ↓                ↓
                        redator_revisao_node  verificador_node
                                 ↓                ↓
                        contraparte_node     formatador_node
                        (CICLO)                   ↓
                                                 END
```

**Detalhes do `contraparte_node`:**
- Modelo: Claude (`claude-sonnet-4-6`) com `bind_tools(TOOLS_CONTRAPARTE)`
- Temperature: 0.5
- Prompt conforme Secao 4.2 (Agente 4) — adversarial agressivo
- Recebe: APENAS `peca_sections` (nao ve dossie, pesquisa, edicoes)
- Saida estruturada: `CriticaContraparte` (Pydantic) via structured output
- Executa pesquisa independente via `buscar_jurisprudencia_contraria`

**Detalhes do `anti_sycophancy_node`:**
- Reutilizar `_is_empty_sycophantic_critique()` de `adversarial.py` (ja implementado)
- Contador de retries no state (`_contraparte_retries: int`)
- Se rejeita e retries < 2: volta pro contraparte com temperature incrementada (+0.15)
- Se rejeita e retries >= 2: aceita com warning

**Detalhes do `redator_revisao_node`:**
- Modelo: Gemini Pro
- Temperature: 0.2
- Recebe: payload de `build_redator_revision_payload()` (ja implementado — state trimming)
- `preserve_human_anchors=True` no payload (ja implementado)
- Revisa APENAS secoes criticadas/editadas (campo `edited_sections` no payload)
- Prompt inclui instrucao: “Preservar paragrafos editados manualmente pelo usuario. Nao reescrever texto que o usuario escolheu manter.”

**Detalhes do `verificador_node`:**
- Codigo puro (ver C.3 abaixo)

**Detalhes do `formatador_node`:**
- Codigo puro (ver C.4 abaixo)

**Codigo do AdversarialGraph:**

```python
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from backend.escritorio.models import RatioEscritorioState
from backend.escritorio.tools.langchain_tools import TOOLS_CONTRAPARTE

adversarial_graph = StateGraph(RatioEscritorioState)

adversarial_graph.add_node(“contraparte”, contraparte_node)
adversarial_graph.add_node(“anti_sycophancy”, anti_sycophancy_node)
adversarial_graph.add_node(“contraparte_tools”, ToolNode(TOOLS_CONTRAPARTE))
adversarial_graph.add_node(“pausa_humana”, lambda s: s)
adversarial_graph.add_node(“redator_revisao”, redator_revisao_node)
adversarial_graph.add_node(“verificador”, verificador_node)
adversarial_graph.add_node(“formatador”, formatador_node)

adversarial_graph.set_entry_point(“contraparte”)

# Contraparte pode chamar tools (ReAct loop)
adversarial_graph.add_conditional_edges(“contraparte”, route_contraparte_tools, {
    “tools”: “contraparte_tools”,
    “done”: “anti_sycophancy”,
})
adversarial_graph.add_edge(“contraparte_tools”, “contraparte”)

# Anti-sycophancy
adversarial_graph.add_conditional_edges(“anti_sycophancy”, sycophancy_router, {
    “aceita”: “pausa_humana”,
    “rejeita”: “contraparte”,
})

# Decisao humana
adversarial_graph.add_conditional_edges(“pausa_humana”, decisao_advogado, {
    “mais_rodada”: “redator_revisao”,
    “finalizar”: “verificador”,
})

# Ciclo principal
adversarial_graph.add_edge(“redator_revisao”, “contraparte”)

# Fluxo final
adversarial_graph.add_edge(“verificador”, “formatador”)
adversarial_graph.add_edge(“formatador”, END)

adversarial_app = adversarial_graph.compile(
    checkpointer=checkpointer,
    interrupt_before=[“pausa_humana”]
)
```

---

### C.3 Verificador Deterministico Completo

Expandir `backend/escritorio/verifier.py` de 3 para 7 padroes de regex, e implementar as 5 camadas.

**Padroes faltantes (adicionar ao verifier.py existente):**

```python
# Ja implementados na foundation:
_ARTICLE_PATTERN   # Art. N do CC/CPC/etc
_SUMULA_PATTERN    # Sumula N do STJ/STF
_RESP_PATTERN      # REsp N / recurso especial N

# ADICIONAR:
_CNJ_PATTERN = re.compile(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}')
_TEMA_PATTERN = re.compile(
    r'(?i)\btema(?:\s+repetitivo)?\s+(?:n[ºo]?\s*)?\d+(?:\.\d+)?(?:\s+(?:do|/)\s*(?:stj|stf))?'
)
_LEI_PATTERN = re.compile(
    r'(?i)\blei\s+(?:n[ºo]?\s*)?\d+(?:[.,/]\d+)*'
)
_CASO_COMPOSTO_PATTERN = re.compile(
    r'(?i)\b(AgInt|AgRg|EDcl|EAREsp|EREsp|AREsp)\s+(?:no|na)\s+'
    r'(REsp|HC|MS|RMS|ARE|AI)\s+\d[\d\.\-/A-Z]*'
)
```

**Implementar as 5 camadas (conforme Secao 8.1 atualizada):**

1. **Normalizacao** — `normalize_legal_text()` ja existe. Adicionar mapeamento de aliases de classe (`_CLASS_ALIASES` ja tem base, expandir).
2. **Extracao hibrida** — `extract_citation_candidates()` ja existe. Adicionar os 4 patterns novos.
3. **Resolucao canonica** — Nova funcao `canonicalize(candidate) -> CitationCandidate` com `canonical_key` para comparacao (ex: `”resp_1234567_sp”`).
4. **Match em niveis** — Nova funcao `match_against_lancedb(canonical, lancedb_registry) -> MatchResult` com niveis exact/strong/weak/unverified. Usa `LanceDBReadonlyRegistry` (ja implementado).
5. **Validacao de proveniencia** — Nova funcao `validate_provenance(citation, section_evidence_pack) -> bool` que confirma que a citacao esta no evidence pack da secao onde foi usada.

**Validacao de digitos CNJ (ISO 7064 Mod 97):**

```python
def validar_cnj(numero_cnj: str) -> bool:
    limpo = re.sub(r'[\-\.]', '', numero_cnj)
    if len(limpo) != 20:
        return False
    n, dd, aaaa, j, tr, oooo = limpo[0:7], limpo[7:9], limpo[9:13], limpo[13:14], limpo[14:16], limpo[16:20]
    valor = int(n + aaaa + j + tr + oooo + dd)
    return valor % 97 == 1
```

**Arquivo resultante:** `backend/escritorio/verifier.py` (~250 linhas, vs ~113 atuais)

---

### C.4 Formatador DOCX

**Novo arquivo:** `backend/escritorio/formatter.py`

Implementar a classe `FormatadorPeticao` conforme Secao 12.2 atualizada do plano:

- Margens: 3cm esq/sup, 2cm dir/inf
- Fonte: Times New Roman 12pt
- Espacamento: 1.5 entre linhas
- Recuo: 2cm primeira linha
- Headings: nivel 1 (14pt bold) para secoes da peca
- Cabecalho: tribunal + vara + processo
- Numeracao de paginas: campo XML PAGE no rodape
- Citacoes verificadas: bold + italic
- Citacoes nao verificadas: highlight amarelo + `[VERIFICAR]` vermelho
- Saida: `.docx` na pasta `output/` do caso

**Dependencia:** `python-docx` (adicionar ao `requirements.txt`)

**Integracao no grafo:** O `formatador_node` chama `FormatadorPeticao.gerar(state, verificacoes)` e salva o caminho do DOCX no state.

---

### C.5 Orquestrador Principal

**Novo arquivo:** `backend/escritorio/graph/orchestrator.py`

Conecta os 3 sub-grafos sequencialmente:

```python
async def run_escritorio_pipeline(caso_id: str, store: CaseStore):
    “””Executa o pipeline completo do Escritorio.”””
    state = store.load_latest_state(caso_id)

    # Fase 1: Intake (se ainda nao passou gate1)
    if not state.gate1_aprovado:
        state = await run_intake_graph(state, store)
        # Pausa no gate1 — retorna ao frontend

    # Fase 2: Drafting (se gate1 aprovado mas nao gate2)
    if state.gate1_aprovado and not state.gate2_aprovado:
        state = await run_drafting_graph(state, store)
        # Pausa no gate2 — retorna ao frontend

    # Fase 3: Adversarial (loop ate usuario finalizar)
    if state.gate2_aprovado and not state.usuario_finaliza:
        state = await run_adversarial_graph(state, store)
        # Pausa em cada rodada — retorna ao frontend

    return state
```

Cada `run_*_graph()` usa `app.invoke()` com checkpointer do SQLite do caso.

---

### C.6 Testes da Fase 2

Expandir a suite de testes para cobrir os novos componentes:

| Teste | Arquivo | O que verifica |
|---|---|---|
| IntakeGraph com LLM mock | `tests/escritorio/test_intake_graph.py` | Fluxo intake → classificacao → gate1 interrupt |
| DraftingGraph com tools mock | `tests/escritorio/test_drafting_graph.py` | Pesquisador chama tools → curadoria → gate2 → redator |
| AdversarialGraph ciclo | `tests/escritorio/test_adversarial_graph.py` | Contraparte → anti-syco → pausa → revisao → volta contraparte |
| Verifier 7 padroes | `tests/escritorio/test_verifier_full.py` | Todos os 7 regex + CNJ validation + canonicalizacao |
| Formatador DOCX | `tests/escritorio/test_formatter.py` | Gera DOCX, verifica margens, fonte, secoes, citacoes coloridas |
| Store por caso | `tests/escritorio/test_case_store_v2.py` | CaseStore + CaseIndex isolados, backup, delete pasta |
| LangChain tools | `tests/escritorio/test_langchain_tools.py` | @tool wrappers geram schema JSON correto, bind_tools funciona |
| Pipeline ponta a ponta | `tests/escritorio/test_pipeline_e2e.py` | Caso completo com LLMs mockados: intake → pesquisa → redacao → adversarial → verificacao → DOCX |

**Padrao de mock para LLMs:**

```python
# Usar langchain_core.language_models.fake para mock de LLM nos testes
from langchain_core.language_models.fake import FakeListLLM

mock_llm = FakeListLLM(responses=[“resposta esperada do pesquisador...”])
```

---

### C.7 Ordem de Execucao (6 tarefas sequenciais)

| # | Tarefa | Arquivos | Depende de | Estimativa |
|---|---|---|---|---|
| 1 | **Migrar store para SQLite-por-caso** | `store.py`, `api.py`, testes | — | 1 sessao |
| 2 | **Criar langchain_tools.py** com @tool wrappers | `tools/langchain_tools.py`, testes | — | 1 sessao |
| 3 | **Expandir verifier.py** com 4 regex + 5 camadas + CNJ | `verifier.py`, testes | — | 1 sessao |
| 4 | **Implementar IntakeGraph + DraftingGraph** com LLM e tools reais | `graph/intake_graph.py`, `graph/drafting_graph.py`, testes | #1, #2 |  1-2 sessoes |
| 5 | **Implementar AdversarialGraph** com ciclo, interrupt, Claude | `graph/adversarial_graph.py`, orquestrador, testes | #2, #4 | 1-2 sessoes |
| 6 | **Implementar formatador DOCX** | `formatter.py`, testes | #3, #5 | 1 sessao |

Tarefas 1, 2 e 3 sao independentes e podem ser executadas em paralelo.
Tarefas 4 e 5 sao sequenciais (DraftingGraph alimenta AdversarialGraph).
Tarefa 6 depende de 3 (verifier) e 5 (pipeline completo).

### C.8 Dependencias a Adicionar ao requirements.txt

```
langchain-core>=0.3.0
langchain-google-genai>=2.0.0    # ChatGoogleGenerativeAI
langchain-anthropic>=0.3.0       # ChatAnthropic (Contraparte)
python-docx>=1.1.0               # Formatador DOCX
```

`langgraph==1.0.10` ja foi adicionado pela foundation.

### C.9 Criterios de Aceite da Fase 2

A Fase 2 esta completa quando:

- [ ] `pytest tests/escritorio/` passa 100% (incluindo testes novos)
- [ ] Pipeline roda ponta a ponta no terminal com LLMs mockados
- [ ] Pipeline roda ponta a ponta com Gemini Flash + Claude reais em 1 caso de teste
- [ ] Verificador detecta corretamente 7 tipos de citacao
- [ ] DOCX gerado abre no Word com formatacao correta
- [ ] Store isolado por caso: criar, listar, deletar pasta funciona
- [ ] Nenhum teste existente do backend principal quebra (`pytest tests/test_api_contract.py`)

### C.10 O que NAO fazer na Fase 2

- Frontend React (Fase 3)
- Streaming SSE (Fase 3)
- Parecer externo / importacao (Fase 3)
- PII detection (Fase 4)
- Evaluation harness automatizado (Fase 4)
- Deploy / empacotamento (Fase 4)

O foco e: **pipeline funcional no terminal, com agentes reais e DOCX final.**




















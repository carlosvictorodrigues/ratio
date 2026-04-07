# Ratio Escritorio Backend-First Design

**Data:** 2026-04-06  
**Fonte de verdade:** `docs/plans/2026-04-06-ratio-escritorio-architecture.md`  
**Review obrigatoria incorporada:** `docs/reviews/review_gemini_3.1_pro.md`

---

## Objetivo

Implementar o Ratio Escritorio em etapas, com foco inicial no backend, sem contaminar o backend atual de pesquisa jurisprudencial e sem depender da nova UI React para validar o nucleo do produto.

## Decisoes de Arquitetura

1. **Bounded context novo em `backend/escritorio/`.**  
   O Escritorio nasce como modulo proprio, com estado, adapters, ferramentas, grafo e API isolados. `backend/main.py` apenas registra o router novo.

2. **Backend-first antes da UI nova.**  
   O primeiro marco entrega dominio, persistencia, tools endurecidas, workflow minimo e endpoints. A UI React entra depois, consumindo contratos ja testados.

3. **Reuso do motor atual via adapters.**  
   `rag/query.py` continua sendo o motor de retrieval. O Escritorio nao reimplementa busca; ele encapsula `run_query()` em wrappers de dominio (`ratio_tools.py`) com contrato proprio.

4. **Resolver as falhas criticas antes do primeiro fluxo real.**  
   O Apendice B do documento principal e tratado como requisito de entrada:
   - state trimming no loop de revisao;
   - tools paralelas com backoff e jitter;
   - isolamento contra prompt injection em texto externo;
   - acesso LanceDB encapsulado, thread-safe e read-only durante o grafo.

5. **Persistencia por caso em SQLite.**  
   Cada caso tera identidade, metadados, snapshots de estado, eventos e artefatos em estrutura local previsivel. Isso preserva o principio "pasta por caso" do documento de arquitetura.

## Estrutura Modular Proposta

```text
backend/escritorio/
  __init__.py
  config.py
  models.py
  state.py
  store.py
  security.py
  api.py
  tools/
    __init__.py
    ratio_tools.py
    legislation_tools.py
    lancedb_access.py
  graph/
    __init__.py
    nodes.py
    workflows.py
tests/escritorio/
  test_models.py
  test_store.py
  test_security.py
  test_ratio_tools.py
  test_workflow.py
  test_api.py
```

## Ordem de Implementacao

### Marco 1 - Fundacao Backend

- Criar o pacote `backend/escritorio/`
- Definir schemas de dominio e helpers de state trimming
- Implementar store SQLite por caso
- Criar camada de seguranca para texto externo
- Implementar `ratio_tools.py` com paralelismo, retry e recency bias
- Implementar acesso LanceDB seguro e read-only
- Subir workflow minimo `Pesquisador -> Redator -> Verificador`
- Expor router FastAPI novo

### Marco 2 - Intake e Ciclo do Caso

- Intake dinamico
- Gates humanos
- persistencia incremental do caso
- retomada de execucao por caso

### Marco 3 - Loop Adversarial

- Contraparte
- dismiss de criticas
- revisao por secao
- preservacao de ancoras humanas
- checkpointing do loop

### Marco 4 - Entrega Final

- verificador em camadas
- DOCX
- pacote final
- contratos para a UI React

## Integracao com o Backend Atual

- `backend/main.py` continua dono do app FastAPI.
- O Escritorio entra como router separado, com prefixo proprio.
- O contrato de pesquisa atual (`/api/query`, `/api/query/stream`) nao muda.
- Testes do Escritorio devem seguir o padrao atual do repositorio: stubs, monkeypatch e `TestClient`.

## Principios de Implementacao

- **Arquitetura modular por default**
- **TDD em cada componente novo**
- **Sem logica nova em `backend/main.py` alem do registro do router**
- **Sem acesso bruto a `rag/query.py` fora dos adapters**
- **Sem estado infinito enviado ao LLM**
- **Falhar fechado sempre que houver ambiguidade juridica ou tecnica**

## Criterio de Sucesso do Primeiro Marco

O Marco 1 esta pronto quando:

- existe um caso persistido em SQLite;
- o workflow minimo roda ponta a ponta sem UI React;
- tools independentes executam em paralelo com retry;
- o estado enviado ao redator e reduzido por trimming;
- o router novo responde em testes de contrato;
- a suite nova do Escritorio passa sem quebrar a suite existente.

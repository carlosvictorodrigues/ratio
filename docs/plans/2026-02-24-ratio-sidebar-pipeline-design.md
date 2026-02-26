# Ratio Sidebar + Pipeline Visual Design

Data: 2026-02-24

## Contexto
A interface do Ratio tinha sobreposicao semantica entre `Fixar` e `Marcar`, cards muito densos na lateral e pipeline de processamento textual. O objetivo e simplificar organizacao de conversas, melhorar legibilidade responsiva e substituir o estado de carregamento por um visual mais rico, sem necessidade de refletir progresso real.

## Decisoes Aprovadas

### 1. Unificacao de acao de colecao
- `Fixar` e `Marcar` serao unificados em uma acao unica: `Salvar`.
- Modos da biblioteca lateral passam a ser:
  - `Historico`
  - `Salvos`
- Migracao de sessao antiga:
  - `saved = saved || pinned || marked`
- Interface removendo a dualidade evita ambiguidade funcional e reduz atrito cognitivo.

### 2. Biblioteca lateral em lista compacta (sempre)
- Desktop e mobile usam o mesmo padrao compacto.
- Cada item exibe apenas:
  - pergunta truncada
  - status
  - quantidade de fontes
  - data/hora
- Acoes discretas no item:
  - `Abrir`
  - `Salvar`/`Remover`

### 3. Pipeline visual no card de resposta em processamento (ajuste final)
- Devido a percepcao de "tela presa" no modo canvas, o card foi simplificado para um estilo linear:
  - barra de progresso
  - lista de etapas
  - badge da etapa atual
  - timer decorrido
- O componente continua visual (nao precisa refletir estado real do backend) e roda em loop discreto enquanto a resposta nao chega.
- A pergunta atual aparece como preview no topo do card.

### 4. Clareza do status (substitui foco em query vector)
- O feedback foi direcionado para entendimento imediato de pipeline:
  - etapa ativa em destaque
  - dicas curtas por etapa
  - pontos animados na descricao ativa
  - estado textual objetivo (etapa + tempo)

### 5. Encoding e padrao de texto
- `rag-visual.html` estava com caracteres corrompidos.
- O componente final sera normalizado em UTF-8 e textos padronizados em pt-BR sem artefatos de encoding.

### 6. Microanimacao curta na geracao de resposta
- Ao concluir a resposta, aplicar revelacao curta de caracteres somente no inicio (curto periodo), em seguida mostrar o texto completo.
- Em `prefers-reduced-motion`, animacao deve ser minimizada/ignoravel.

## Nao-objetivos
- Sincronizar visual de pipeline com progresso real do backend.
- Criar um modo alternativo detalhado para desktop.
- Introduzir novos paines laterais alem de Historico/Salvos.

## Impacto em arquitetura
- Frontend apenas (`frontend/index.html`, `frontend/styles.css`, `frontend/app.js`).
- Sem alteracao de contrato de API backend.
- Sessao local com migracao de dados antigos para novo campo `saved`.

## Criterios de aceite
- Nao existe mais `Fixar`/`Marcar` em UI nem no estado novo.
- Biblioteca mostra apenas `Historico` e `Salvos`, ambos compactos.
- Card de processamento mostra visual animado em loop com query real.
- Cena de query vector explicita top-k e legenda de projecao 2D.
- Resposta final tem microrevelacao curta de caracteres.
- Testes e validacao local sem regressao.

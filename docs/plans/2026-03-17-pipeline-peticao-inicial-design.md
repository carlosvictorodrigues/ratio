# Pipeline De Peticao Inicial Design

**Data:** 2026-03-17
**Status:** Aprovado
**Escopo:** MVP de robustez argumentativa para peticao inicial

---

## Posicionamento

O MVP do Ratio para peticao inicial e um pipeline de robustez argumentativa para advogado experiente. A promessa nao e "escrever por voce". A promessa e esta: voce monta a inicial sabendo, antes de protocolar, quais precedentes reais, riscos processuais e fragilidades probatorias podem ser usados contra ela.

O diferencial competitivo e a simulacao adversarial ancorada em acordaos reais da propria base brasileira do Ratio. O produto nao disputa o mesmo espaco de "pesquisa com IA" ou "redacao com IA". Ele usa a base real para encontrar o melhor ataque possivel contra a propria tese do usuario.

---

## Camadas De Valor

- `Camada 1`: dossie estruturado + analise de cobertura da minuta
- `Camada 2`: stress test adversarial com agente-reu e agente-juiz
- `Camada 3`: redacao interna da minuta, fora do MVP

---

## Fluxo Do Produto

### 1. Caso

O advogado informa briefing, pedido, fatos, contexto processual e envia documentos.

### 2. Matriz Do Caso

O sistema normaliza isso em fatos, pedidos, provas, restricoes processuais e contexto decisorio.

### 3. Proposicao De Eixos

O Ratio sugere teses, subteses, pedidos, riscos e pontos de prova.

### 4. Confirmacao Humana Obrigatoria

Nada segue sem revisao do advogado. Ele confirma, remove ou adiciona eixos. Esse e o principal gate de qualidade do pipeline.

### 5. Pesquisa Dual

Para cada eixo confirmado, o sistema executa:

- `buscar_favoraveis`
- `buscar_contrarios`

Essas buscas podem rodar em paralelo por eixo.

### 6. Consolidacao Agressiva

O Ratio filtra precedente forte versus citacao ornamental. O criterio central e: mesmo ponto controvertido em contexto fatico suficientemente analogo. "Mesmo tema" nao basta.

### 7. Montagem Do Dossie

O produto gera o pacote estruturado de tese, ataque, prova e restricao processual.

### 8. Exportacao Para Redacao

Na camada 1, o advogado usa Claude, Gemini ou outro redator externo com pacote controlado.

### 9. Importacao Da Minuta

A inicial volta ao Ratio.

### 10. Analise De Cobertura

Antes do adversarial, o sistema mostra:

- o que da minuta esta ancorado no dossie;
- o que entrou sem respaldo;
- o que foi pesquisado e ficou de fora.

Essa etapa funciona como gate automatico contra alucinacao e desperdicio.

### 11. Stress Test

O agente-reu ataca a peticao concreta com novas buscas. O agente-juiz testa admissibilidade, suficiencia e riscos processuais com abordagem hibrida.

### 12. Fila De Ataque

A saida final e ordenada por impacto:

1. o que pode causar indeferimento ou derrota estrutural;
2. o que enfraquece pedidos especificos;
3. melhorias argumentativas e redacionais.

---

## Estrutura Do Dossie

O dossie do MVP tem 10 blocos fixos:

### Bloco 1: Matriz Do Caso

- resumo factual controlado
- partes
- pedido principal e subsidiarios
- juizo ou tribunal-alvo
- rito ou urgencia
- documentos enviados
- fatos confirmados versus fatos ainda nao comprovados

### Bloco 2: Mapa De Eixos Juridicos

Cada eixo contem:

- nome do eixo
- tipo: `tese`, `subtese`, `pedido`, `risco`, `prova`
- status: `proposto pelo sistema`, `confirmado pelo advogado`, `adicionado pelo advogado`, `removido`
- prioridade
- observacao livre do advogado

### Bloco 3: Kit Favoravel Por Eixo

- precedentes favoraveis prioritarios
- trecho nuclear
- tribunal, relator e data
- forca estimada
- motivo da relevancia para o caso
- sugestao de uso: `abrir tese`, `reforcar pedido`, `fundar tutela`, `rebater objecao`

### Bloco 4: Kit Contrario Por Eixo

- precedentes potencialmente contrarios
- tese contraria resumida
- risco para a inicial
- intensidade do risco
- precedente base
- possivel distincao
- possivel contra-ataque

### Bloco 5: Legislacao E Enunciados

- artigos de lei relevantes
- sumulas
- temas repetitivos e repercussao geral
- precedentes qualificados
- vinculo com cada eixo do caso

### Bloco 6: Mapa De Prova

- fato alegado
- documento que sustenta
- documento ausente
- risco probatorio
- impacto no pedido
- acao recomendada: `anexar`, `complementar`, `nao alegar`, `alegar com ressalva`

### Bloco 7: Mapa De Pedidos

- pedido
- fundamento juridico
- prova de suporte
- risco de excesso
- dependencia logica
- versao principal e subsidiaria

### Bloco 8: Restricoes Processuais

- competencia
- prescricao e decadencia
- interesse de agir
- procedimento administrativo previo obrigatorio
- documentos indispensaveis
- risco de inepcia ou indeferimento liminar

### Bloco 9: Fila Preliminar De Robustez

- fragilidade identificada
- tipo: `jurisprudencial`, `legal`, `probatoria`, `logica`, `redacional`
- gravidade
- precedente base
- acao sugerida
- eixo afetado

### Bloco 10: Pacote De Exportacao

- fatos autorizados
- teses autorizadas
- teses vedadas
- precedentes favoraveis
- precedentes contrarios
- distincoes sugeridas
- legislacao
- mapa de prova
- instrucoes de estilo
- limite de prolixidade
- obrigacao de citar apenas material validado

---

## Operacoes Internas

Essas operacoes devem nascer como API interna do produto, nao como logica acoplada a UI:

- `criar_matriz_do_caso`
- `propor_eixos`
- `confirmar_eixos`
- `buscar_favoraveis`
- `buscar_contrarios`
- `consolidar_autoridades`
- `extrair_tese_nuclear`
- `sugerir_distincoes`
- `mapear_provas`
- `avaliar_restricoes_processuais`
- `montar_dossie`
- `exportar_pacote_redacao`
- `analisar_minuta`
- `avaliar_cobertura_da_minuta`
- `atacar_minuta_com_rag`
- `revisar_minuta_com_juiz_hibrido`
- `gerar_fila_de_ataque`
- `reconciliar_revisoes`

### Dependencias Principais

1. `propor_eixos` depende de `criar_matriz_do_caso`.
2. `confirmar_eixos` trava o restante.
3. `buscar_favoraveis` e `buscar_contrarios` podem rodar em paralelo por eixo.
4. `mapear_provas` e `avaliar_restricoes_processuais` podem rodar em paralelo com as buscas.
5. `analisar_minuta` deve preceder o stress test.
6. `atacar_minuta_com_rag` deve usar busca nova sobre a minuta concreta.

---

## Comportamento Dos Agentes

### Agente-Reu

**Objetivo:** encontrar a melhor defesa possivel contra a inicial concreta.

Comportamento:

- le a minuta real e extrai os argumentos efetivamente usados;
- gera novas consultas ao RAG a partir do texto escrito, nao so do briefing original;
- busca precedentes contrarios, distincoes ausentes, preliminares defensivas, fragilidades probatorias e pedidos excessivos;
- sugere distincao ancorada quando houver precedente util para neutralizar o ataque.

Formato de saida:

- objecao
- fundamento
- precedente base
- gravidade: `matador`, `relevante`, `melhoria`
- acao sugerida

Regras:

- nao pode atacar sem precedente base ou base normativa ou probatoria clara;
- prioriza o que pode realmente mudar o desfecho;
- nao gera objecao generica sem base verificavel.

### Agente-Juiz

**Objetivo:** simular o olhar de admissibilidade e suficiencia da inicial.

Abordagem hibrida:

- `Regras` para o que e calculavel: datas para prescricao, documentos minimos por tipo de acao, competencia formal quando parametrizavel.
- `LLM` para o que exige interpretacao: suficiencia de fundamentacao, coerencia entre causa de pedir e pedido, excesso retorico.

Verifica:

- inepcia ou confusao do pedido
- falta de documento indispensavel
- incompetencia
- prescricao e decadencia
- ausencia de interesse de agir
- tutela de urgencia mal fundamentada
- excesso argumentativo sem ganho decisorio

Formato de saida:

- risco processual
- fundamento
- precedente base ou norma
- gravidade
- acao sugerida

### Ordenacao Da Fila De Ataque

Dentro de cada nivel de gravidade:

1. o que causa indeferimento ou derrota estrutural;
2. o que enfraquece pedidos especificos;
3. questao redacional ou de estilo.

---

## UX Do MVP

### Telas Essenciais

- `Caso`
- `Eixos`
- `Pesquisa`
- `Dossie`
- `Minuta`
- `Stress test`

### Principios De UX

- transparencia: a decomposicao juridica e editavel e auditavel;
- criterio explicito: cada precedente exibido traz o motivo de entrada;
- filtro agressivo: o padrao mostra poucos precedentes fortes, nao tudo;
- bloco processual visivel: card proprio acima do mapa de pedidos;
- sem chat generico: stress test e fila operacional, nao conversa;
- acoes do advogado na fila: `aceitar`, `rejeitar`, `distinguir`, `pedir mais base`, `marcar irrelevante`.

### Painel Lateral Da Fila De Ataque

Cada item abre:

- resumo da objecao
- precedente base clicavel
- trecho-chave do precedente
- por que isso se aplica ao caso
- possivel distincao sugerida, ancorada quando disponivel
- botoes de acao do advogado

---

## Fora Do MVP

Ficam explicitamente fora:

- redacao integral dentro do Ratio
- contestacao, recurso e memorial
- automacao de protocolo
- gestao completa do processo
- agente conversacional generico
- busca aberta sem vinculo com eixo, pedido ou risco

---

## Criterios De Sucesso

O MVP esta certo se entregar:

- menos citacao ornamental na minuta final
- menos argumentos sem lastro
- mais uso efetivo do que foi pesquisado
- identificacao precoce de riscos processuais e precedentes contrarios
- percepcao clara de diferencial frente a pesquisador juridico comum

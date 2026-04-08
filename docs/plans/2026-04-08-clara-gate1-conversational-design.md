# Clara Gate1 Conversational Design

**Goal:** Fazer a Clara se comportar como uma analista jurídica conversacional no intake, devolvendo perguntas-chave e um dossiê vivo antes da aprovação do `gate1`.

**Design Summary:** O usuário continua conversando com a Clara no mesmo chat do intake, mas o resultado de `Analisar com Clara` passa a incluir um bloco conversacional da própria Clara, com `perguntas_pendentes`, `triagem_suficiente` e convite para complementar os fatos ou prosseguir assim mesmo. O `gate1` deixa de ser apenas um overlay técnico e vira uma decisão explícita do usuário sobre um dossiê já organizado.

## Backend contract

O intake deve passar a produzir, além de:
- `fatos_estruturados`
- `provas_disponiveis`
- `pontos_atencao`

os seguintes campos novos:
- `resposta_conversacional_clara`
- `perguntas_pendentes`
- `triagem_suficiente`

A Clara não trava o usuário. Mesmo com lacunas, o usuário sempre pode optar por `Prosseguir assim mesmo`.

## UX contract

Depois de `Analisar com Clara`, o intake mostra:
- mensagem conversacional da Clara
- dossiê estruturado
- perguntas pendentes
- três ações:
  - `Responder perguntas da Clara`
  - `Reanalisar`
  - `Prosseguir assim mesmo`

O caso só sai do intake quando o usuário aprova explicitamente o `gate1`.

## Rules for Clara

- Fazer no máximo 1 a 3 perguntas por rodada.
- Perguntar apenas o que muda a peça.
- Distinguir lacunas críticas de lacunas desejáveis sem bloquear o usuário.
- Sempre encerrar com abertura conversacional, como:
  - “Se quiser, posso fechar a triagem assim mesmo ou você pode me complementar esses pontos.”

## Out of scope

- Motor completo de entrevista multi-turn com memória estratégica.
- Banco curado de perguntas por área do direito.
- Novo layout do Escritório fora do intake atual.

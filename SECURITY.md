# Security Policy

## Supported versions

Projeto em fase inicial de open source.
Correcoes de seguranca serao aplicadas primeiro na branch principal.

## Reporting a vulnerability

Se voce identificar uma vulnerabilidade:

1. Nao publique exploit detalhado em issue publica.
2. Abra uma issue com o titulo `[security]` contendo apenas impacto alto nivel.
3. Solicite canal privado para envio dos detalhes tecnicos.

Enquanto private reporting do GitHub nao estiver habilitado, use esse fluxo.

## Response target

- Triagem inicial: ate 5 dias uteis.
- Atualizacao de status: ate 10 dias uteis.
- Correcao ou mitigacao inicial: conforme severidade e reproducibilidade.

## Scope

Itens de maior prioridade:

- exposicao de chave/API secret
- bypass de validacoes de input
- endpoints com execucao indevida de comandos
- vazamento de dados locais indexados


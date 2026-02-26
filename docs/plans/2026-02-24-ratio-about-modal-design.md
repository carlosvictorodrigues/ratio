# Ratio About Modal Design

Data: 2026-02-24

## Objetivo
Mover conteudo institucional (`Sobre o acervo` e `Sobre o autor`) para fora de `Configuracoes` e disponibilizar um modal central grande dedicado, aberto por novo botao na barra lateral esquerda.

## Decisao aprovada
- Abordagem 1: modal central grande com abas.
- Abas:
  - `Acervo`
  - `Estrutura documental`
  - `Autor e apoio`

## Requisitos funcionais
- Remover `Sobre o acervo` e `Sobre o autor e apoio` da area de `Configuracoes`.
- Adicionar novo botao `Sobre` na barra lateral esquerda.
- Novo modal `Sobre o Ratio` deve abrir em camada central e ser independente do modal de onboarding Gemini.
- Aba `Acervo`:
  - mostrar dimensao da base (documentos, caracteres, paginas/livros, armazenamento);
  - visual de escala sem ASCII, inspirado em `teste.html`.
- Aba `Estrutura documental`:
  - explicar tipos documentais (sumula, sumula vinculante, tema de repercussao geral, tema repetitivo STJ, acordao, decisao monocratica, informativo).
- Aba `Autor e apoio`:
  - Contato publico do autor (Instagram e e-mail) exibido apenas no modal final
  - Chave PIX completa + botao copiar (dados reais apenas na interface final)
  - QR code de `apoio-pix.jpeg`

## Diretrizes de UX/UI
- Manter identidade visual atual (tons stone, tipografia e bordas discretas).
- Modal responsivo:
  - desktop: centralizado com largura ampla;
  - mobile: modo fullscreen deslizante vertical.
- Navegacao por abas com estado ativo claro e sem poluicao visual.
- Fechamento por `X`, `overlay` e tecla `Esc`.

## Impacto tecnico
- `frontend/index.html`: novo botao lateral, novo modal e remocao das duas secoes do settings.
- `frontend/styles.css`: estilos do modal, abas e visual de escala nao-ASCII.
- `frontend/app.js`: estado de abertura/fechamento do modal, troca de abas e copia da chave PIX.
- `tests/test_frontend_sidebar_saved.py`: cobertura de regressao para garantir nova arquitetura de UI.

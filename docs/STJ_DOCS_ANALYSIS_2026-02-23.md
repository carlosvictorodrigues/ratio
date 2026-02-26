# Analise de Novos PDFs STJ (docs)

Data da analise: 2026-02-23
Escopo: `stj_informativos_pdf/docs` -> enriquecimento incremental em `data/stj_informativos/stj_informativos.db`.

## Inventario de documentos

### Inf0877.pdf
- Tamanho: 0.64 MB
- Paginas: 23
- Primeiras linhas relevantes:
  - Informativo de Jurisprudência n. 877     18 de fevereiro de 2026.
  - Este periódico destaca teses jurisprudenciais e não consiste em repositório oficial de jurisprudência.
  - RECURSOS REPETITIVOS
  - PROCESSO
  - REsp  2.193.673-SC,  Rel.  Ministra  Maria  Thereza  de  Assis  Moura,
  - Primeira  Seção,  por  unanimidade,  julgado  em  11/2/2026.  (Tema
  - 1385).
  - REsp  2.203.951-SC,  Rel.  Ministra  Maria  Thereza  de  Assis  Moura,
- Marcadores estruturais (amostra das 15 primeiras paginas):
  - PROCESSO: 7
  - RAMO DO DIREITO: 7
  - DESTAQUE: 7
  - VEJA MAIS: 0
  - S[?U]MULA: 0
  - TEMA REPETITIVO: 2
  - DIREITO ...: 2

### SelecaoRepetitivos20260223124915847.pdf
- Tamanho: 3.68 MB
- Paginas: 1063
- Primeiras linhas relevantes:
  - SUMÁRIO
  - SUMÁRIO
  - DIREITO ADMINISTRATIVO
  - 9
  - ÁGUA E ESGOTO
  - 9
  - ATIVIDADE DE ENFERMAGEM
  - 14
- Marcadores estruturais (amostra das 15 primeiras paginas):
  - PROCESSO: 0
  - RAMO DO DIREITO: 0
  - DESTAQUE: 0
  - VEJA MAIS: 0
  - S[?U]MULA: 0
  - TEMA REPETITIVO: 3
  - DIREITO ...: 17

### SumulasSTJ.pdf
- Tamanho: 38.39 MB
- Paginas: 2654
- Primeiras linhas relevantes:
  - SUMÁRIO
  - SUMÁRIO
  - Súmula 1
  - DIREITO CIVIL - INVESTIGAÇÃO DE PATERNIDADE
  - 39
  - Súmula 2
  - DIREITO PROCESSUAL CIVIL - HABEAS DATA
  - 41
- Marcadores estruturais (amostra das 15 primeiras paginas):
  - PROCESSO: 0
  - RAMO DO DIREITO: 0
  - DESTAQUE: 0
  - VEJA MAIS: 0
  - S[?U]MULA: 0
  - TEMA REPETITIVO: 0
  - DIREITO ...: 52

### SumulasSTJ_Ramos.pdf
- Tamanho: 38.43 MB
- Paginas: 2642
- Primeiras linhas relevantes:
  - SUMÁRIO
  - SUMÁRIO
  - DIREITO ADMINISTRATIVO - ÁGUA E ESGOTO
  - 30
  - Súmula 407
  - 30
  - Súmula 412
  - 33
- Marcadores estruturais (amostra das 15 primeiras paginas):
  - PROCESSO: 0
  - RAMO DO DIREITO: 1
  - DESTAQUE: 0
  - VEJA MAIS: 0
  - S[?U]MULA: 0
  - TEMA REPETITIVO: 0
  - DIREITO ...: 31

### VerbetesSTJ.pdf
- Tamanho: 0.4 MB
- Paginas: 93
- Primeiras linhas relevantes:
  - G SÚMULA 676
  - VEJA MAIS
  - Em razão da Lei n. 13.964/2019, não é mais possível ao juiz, de ofício, decretar ou converter prisão
  - em flagrante em prisão preventiva. (TERCEIRA SEÇÃO, julgado em 11/12/2024, DJe de 17/12/2024)
  - G SÚMULA 675
  - VEJA MAIS
  - É legítima a atuação dos órgãos de defesa do consumidor na aplicação de sanções  administrativas
  - previstas no CDC quando a conduta praticada ofender direito  consumerista, o que não exclui nem
- Marcadores estruturais (amostra das 15 primeiras paginas):
  - PROCESSO: 0
  - RAMO DO DIREITO: 0
  - DESTAQUE: 0
  - VEJA MAIS: 101
  - S[?U]MULA: 0
  - TEMA REPETITIVO: 1
  - DIREITO ...: 0

## Classificacao estrutural

- `Inf0877.pdf`: formato de Informativo STJ moderno (blocos por `PROCESSO`, `RAMO DO DIREITO`, `TEMA`, `DESTAQUE`).
- `SelecaoRepetitivos20260223124915847.pdf`: compilado tematico de precedentes repetitivos com hierarquia por ramo/assunto + temas repetitivos.
- `SumulasSTJ.pdf`: compendio de sumulas (sumario e corpo), util para mapeamento numero -> ramo/assunto.
- `SumulasSTJ_Ramos.pdf`: compendio de sumulas reorganizado por ramos/assuntos (forte valor para taxonomia).
- `VerbetesSTJ.pdf`: verbetes de sumulas com enunciado e metadados (orgao, data de julgamento, DJe).

## Verificacao de existencia no banco (antes/depois)

- Antes desta ingestao incremental, a tabela `stj_informativos` nao tinha registros do Informativo 877.
- O banco nao possuia tabelas para sumulas/verbetes/repetitivos STJ com estrutura dedicada.
- Depois da ingestao, os 5 PDFs ficaram registrados em `stj_document_sources` com status `ok`.

## Delta aplicado no banco

- `stj_informativos`: 4915 registros totais (inclui `informativo_numero=877`: 12 registros).
- `stj_sumulas`: 641 registros totais (641 sumulas distintas, faixa 1-676).
- `stj_sumula_ramos`: 2378 registros totais (676 sumulas distintas mapeadas, faixa 1-676).
- `stj_temas_repetitivos`: 689 registros totais (661 temas distintos, faixa 1-1390).

## Processamento por arquivo (rastreado)

- `Inf0877.pdf` | tipo=`informativo` | status=`ok`
  - stj_informativos_inserted: 12
  - stj_informativos_skipped_existing_source: 0
  - observacao: Informativo records parsed: 12
- `SelecaoRepetitivos20260223124915847.pdf` | tipo=`repetitivos` | status=`ok`
  - stj_temas_repetitivos_inserted: 689
  - stj_temas_repetitivos_ignored_duplicates: 0
  - observacao: Repetitivos entries parsed: 689
- `SumulasSTJ.pdf` | tipo=`sumulas` | status=`ok`
  - stj_sumula_ramos_inserted: 1390
  - stj_sumula_ramos_ignored_duplicates: 0
  - observacao: Sumula ramo links parsed: 1390
- `SumulasSTJ_Ramos.pdf` | tipo=`sumulas_ramos` | status=`ok`
  - stj_sumula_ramos_inserted: 988
  - stj_sumula_ramos_ignored_duplicates: 0
  - observacao: Sumula ramo links parsed: 988
- `VerbetesSTJ.pdf` | tipo=`verbetes` | status=`ok`
  - stj_sumulas_inserted: 641
  - stj_sumulas_ignored_duplicates: 0
  - observacao: Verbetes sumulas parsed: 641

## Robustez de ingestao

- Pipeline incremental sem overwrite.
- Controle por hash SHA-256 por arquivo em `stj_document_sources` para evitar retrabalho em reexecucoes.
- Chaves unicas + `INSERT OR IGNORE` nas tabelas novas para deduplicacao por entidade.
- `stj_informativos` protegido por dedupe por `source_pdf` (nao reinsere o mesmo PDF).

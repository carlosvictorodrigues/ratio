# TJRS Ingest - Estimativa e Passo a Passo

## Escopo

- **Tribunal:** TJRS (Tribunal de Justica do Rio Grande do Sul)
- **Periodo:** 01/01/2015 a 20/03/2026 (~10 anos, ~4.097 dias)
- **Fonte:** Solr do TJRS via Playwright (scraper pronto em `scrapers/tjrs_scraper.py`)

## Dados da Simulacao (amostra real)

- **Periodo testado:** 01/03/2026 a 06/03/2026 (6 dias)
- **Decisoes coletadas:** 1.777
- **Taxa:** ~296 decisoes/dia
- **Tamanho medio da ementa:** ~1.244 caracteres (~310 tokens)
- **DB local:** `data/tjrs/tjrs_jurisprudencia.db` (SQLite, tabela `acordaos`)

### Composicao por tipo

| Tipo | Qtd | % |
|------|-----|---|
| Monocratica | 1.351 | 76% |
| Admissibilidade | 413 | 23% |
| Acordao | 13 | 1% |

## Estimativa para 10 anos

| Metrica | Valor |
|---------|-------|
| Total estimado | ~1.213.000 decisoes |
| Tokens totais (embedding) | ~376M tokens |
| Custo embedding (Gemini, $0.15/1M) | **~US$ 56** |
| Armazenamento LanceDB estimado | ~3-4 GB |

## Passo a Passo

### 1. Scraping (~20-24h)

```bash
python scrapers/tjrs_scraper.py --start 01/01/2015 --end 20/03/2026
```

- 0.5s delay entre requests, 10 resultados/pagina
- Split recursivo de datas quando > 9.990 resultados
- Retry com backoff exponencial (3 tentativas)
- Progresso salvo em `scrape_progress` (retomavel)
- Saida: SQLite em `data/tjrs/tjrs_jurisprudencia.db`

### 2. Ingest/Embedding (~3-4h)

```bash
python rag/ingest.py --source tjrs --mode append
```

- Modelo: `gemini-embedding-001` (768 dimensoes)
- Batch: 100 docs por request
- Tabela LanceDB: `tjrs_jurisprudencia` (isolada, como TJSP)
- Requer chave Gemini valida no `.env`

### 3. Validacao

- Verificar contagem: `python -c "import lancedb; db=lancedb.connect('lancedb_store'); print(len(db.open_table('tjrs_jurisprudencia')))"`
- Testar query com filtro TJRS no app
- Verificar balanceamento no Informativo Juridico

### 4. Release

- Atualizar `NATIVE_SOURCE_CONFIG` em `rag/query.py` se necessario
- Adicionar filtro TJRS no frontend (como feito com TJSP)
- Novo release com manifest atualizado

## Observacoes

- Custo muito baixo (< US$ 60 total)
- Scraping e o gargalo principal (~1 dia), nao o custo
- Pode paralelizar scraping por faixas de data
- Free tier do Gemini tem rate limit (429 errors) — usar tier pago para ingest grande

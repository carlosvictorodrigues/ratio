# Ratio - RAG Project Context & Status

Este repositÃ³rio contÃ©m um sistema **RAG (Retrieval-Augmented Generation)** construÃ­do para realizar buscas semÃ¢nticas mistas sobre uma base consolidada da JurisprudÃªncia do STF e STJ, gerando respostas fundamentadas com a API do **Gemini**.

## ðŸš€ Arquitetura

O sistema Ã© dividido em fases lÃ³gicas que transformam dados extraÃ­dos da web em tensores semÃ¢nticos consultÃ¡veis.

1. **ExtraÃ§Ã£o Original (`scrapers/` e `download_stj.py`)** 
   - Downloads de decisÃµes via API Elasticsearch do STF e web scraping de PDFs de Informativos do STJ.
2. **Processamento e EstruturaÃ§Ã£o (`processors/` e `data/`)**
   - NormalizaÃ§Ã£o dos dados "sujos" em bancos `SQLite` padronizados, extraÃ§Ã£o de texto em PDFs com regex.
3. **Database Vetorial e IngestÃ£o (`rag/ingest.py` e `lancedb_store/`)**
   - Uso de **LanceDB** serverless (no disco).
   - Embedding: `gemini-embedding-001` (DimensÃ£o 768).
   - Busca HÃ­brida nativa na DB (Embeddings + Full-Text Search).
4. **Engine de Busca e Reranking (`rag/query.py`)**
   - Realiza a Vector Search + BM25 combinadas.
   - Aplica Reranker `cross-encoder/ms-marco-MiniLM-L-6-v2` nas amostras encontradas para precisÃ£o mÃ¡xima.
5. **GeraÃ§Ã£o LLM com Strict Citation (`rag/query.py`)**
   - O Gemini (PadrÃ£o: `gemini-3-flash-preview` / RaciocÃ­nio: `gemini-3.1-pro-preview`) recebe os documentos formatados com um prompt restritivo (`REGRA 2: NÃ£o invente, diga 'NÃ£o encontrei' se nÃ£o houver no acervo`).

---

## ðŸ“‚ Estrutura de Pastas e Arquivos

```text
â”œâ”€â”€ data/                       # Bancos locais SQLite limpos (Fase 0)
â”‚   â”œâ”€â”€ acordaos/               # STF AcÃ³rdÃ£os (~223k registros)
â”‚   â”œâ”€â”€ informativos/           # STF Informativos (~11k)
â”‚   â”œâ”€â”€ monocraticas/           # STF MonocrÃ¡ticas (~712k)
â”‚   â”œâ”€â”€ sumulas/                # STF SÃºmulas (736)
â”‚   â””â”€â”€ stj_informativos/       # STJ Informativos (4.9k)
â”œâ”€â”€ lancedb_store/              # Arquivos binÃ¡rios do LanceDB (Fase 1 e 2)
â”‚   â””â”€â”€ jurisprudencia.lance/   # Banco vetorial criado no run de ingest.py
â”œâ”€â”€ processors/                 # Scripts Python que limpam, criam SQLite e padronizam
â”‚   â”œâ”€â”€ organize_stj_informativos.py
â”‚   â””â”€â”€ parse_stj_to_sqlite.py  # Parser PDF -> SQLite para o STJ
â”œâ”€â”€ rag/                        # Pipeline do RAG e Query Engine (Fase 3 e 4)
â”‚   â”œâ”€â”€ ingest.py               # Leitor SQLite -> Gemini Embedding -> LanceDB
â”‚   â””â”€â”€ query.py                # Interface de Busca (Busca hÃ­brida -> Reranker -> LLM)
â”œâ”€â”€ scrapers/                   # CÃ³digos para download bruto (Fase -1)
â”‚   â””â”€â”€ ...
â”œâ”€â”€ .env                        # [NecessÃ¡rio criar] VariÃ¡veis como GEMINI_API_KEY
â”œâ”€â”€ download_stj.py             # Script de download automatizado de PDFs do STJ
â”œâ”€â”€ README.md                   # RepositÃ³rio documentation
â””â”€â”€ RAG_CONTEXT.md              # Este contexto
```

---

## âš¡ Como acelerar a IngestÃ£o (Embeddings)?

Ao rodar `py rag/ingest.py --source all`, o processo enviarÃ¡ milhares de textos para o Google. Atualmente o script tem `time.sleep(1.0)` para nÃ£o bater na parede de limite de taxa gratuita (Rate Limit `429 RESOURCE_EXHAUSTED`). 

### OpÃ§Ãµes para Agilizar:
1. **Tier Pago / Upgrade no Google AI Studio / Google Cloud (Pay-as-you-go):**
   - Acesse o Google Cloud Console ou o [Google AI Studio](https://aistudio.google.com/).
   - Adicione dados de faturamento (Billing) na sua Google Cloud Project associada Ã  sua API Key.
   - O modelo `gemini-embedding-001` passarÃ¡ a aceitar milhares de requests por minuto (RPM) em vez do limite do Tier Gratuito.
   - Uma vez feito o upgrade de conta, edite em `rag/ingest.py` a variÃ¡vel `EMBED_DELAY = 1.0` para `EMBED_DELAY = 0.0` e aumente o `EMBED_BATCH_SIZE` atÃ© o limite pago da sua cota.

2. **Google Batch API [OpÃ§Ã£o para ProdutizaÃ§Ã£o via GCP]:**
   - O Google Cloud suporta enviar os textos para armazenamento no Cloud Storage (GCS) em massa como um arquivo JSONL, executar um Job Batch AssÃ­ncrono com desconto de 50%, e devolver todos os embeddings de uma sÃ³ vez (sem limite prÃ¡tico de Rate Limit). Isso exige criar Cloud Storage Buckets.

---

## ðŸ› ï¸ Como Instalar e Rodar

### Requisitos:
- Python 3.10+
- Conta Google e API Key (Google AI Studio ou Vertex AI).

### InstalaÃ§Ã£o:
```bash
# Instalar principais pacotes via pip
pip install lancedb google-genai python-dotenv pyarrow sentence-transformers PyMuPDF
```

### ConfiguraÃ§Ã£o:
Crie um arquivo `.env` na raiz do projeto com sua chave e configure:
```
GEMINI_API_KEY="SUA_CHAVE_GEMINI_AQUI"
```

### IngestÃ£o (Gerando o LanceDB Vetorial)
```bash
py rag/ingest.py --source sumulas       # Teste rÃ¡pido
py rag/ingest.py --source stj           # Demorado (VÃ¡rios minutos, ~5k requests)
py rag/ingest.py --source informativos  # Bem Demorado (~11k requests)
py rag/ingest.py --source acordaos      # Apenas caso Premium Tier! (223k reqs)
```

### Consulta (RAG Query)
```bash
# Busca RÃ¡pida (Flash 3.0)
py rag/query.py "Qual o entendimento do STJ sobre IPTU em zona rural?"

# Busca Complexa / RaciocÃ­nio Lento e AnalÃ­tico (Pro 3.1)
py rag/query.py "Discorra sobre a repercussÃ£o geral tema X em face dos precedentes..." --reasoning
```


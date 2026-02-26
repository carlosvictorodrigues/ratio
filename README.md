# Ratio - Pesquisa Jurisprudencial

Ratio is a local legal research application for STF/STJ jurisprudence.

This Git package is focused on running the app on the user's computer.
It intentionally excludes scraping pipelines and large local databases.

## What is included

- Backend API (`backend/`)
- Frontend web (`frontend/`)
- Query and reranking engine (`rag/query.py`)
- Start/stop scripts for Windows
- OSS docs, tests, and CI

## What is not included

- Raw scraping scripts for STF/STJ data collection
- Large local datasets (`data/`)
- Prebuilt vector index (`lancedb_store/`)
- Generated outputs and runtime logs

## Requirements

- Python 3.10+
- Gemini API key (`GEMINI_API_KEY`)
- Internet on first reranker download

Install dependencies:

```bash
py -m pip install -r requirements.txt
```

## Build executavel .exe (Windows)

Use o script de empacotamento:

```text
build_windows_exe.bat
```

O script prioriza `Python 3.12` (via `py -3.12`) e usa `py` como fallback.

Ao final, o executavel fica em:

```text
dist\Ratio\Ratio.exe
```

No computador final, o usuario nao precisa de Python instalado.
O build inclui automaticamente `lancedb_store` em `dist\Ratio\` e cria backup preventivo do banco anterior em `build\database_backups\` quando existir.

Passos para distribuir:

1. Envie a pasta completa `dist\Ratio\`.
2. Inclua `.env` (opcional; a chave Gemini pode ser cadastrada no onboarding).
3. O usuario final executa apenas `Ratio.exe`.

## Environment setup

1. Copy `.env.example` to `.env`.
2. Configure at least:

```text
GEMINI_API_KEY=...
```

### TTS (provedor configuravel)

O endpoint `/api/tts` agora suporta dois provedores:

- `legacy_google` (padrao): Google Cloud Text-to-Speech (`texttospeech.googleapis.com`) com voz Neural2.
- `gemini_native`: caminho Gemini nativo (mantido como alternativa).

Perfil padrao (rollback estavel):

```text
TTS_PROVIDER=legacy_google
GOOGLE_TTS_VOICE_NAME=pt-BR-Neural2-B
TTS_LANGUAGE_CODE=pt-BR
GOOGLE_TTS_MAX_CHARS=5000
GOOGLE_TTS_REQUEST_TIMEOUT_MS=45000
```

Observacoes:

- O perfil legado usa `speakingRate=1.2` e `pitch=-4.5` no backend.
- Chave: `GOOGLE_TTS_API_KEY` ou `GEMINI_API_KEY` (fallback).

Opcional (caminho Gemini):

```text
TTS_PROVIDER=gemini_native
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts
GEMINI_TTS_VOICE=charon
GEMINI_TTS_MAX_CHARS=400
GEMINI_TTS_REQUEST_TIMEOUT_MS=120000
GEMINI_TTS_REQUEST_RETRY_ATTEMPTS=1
GEMINI_TTS_MODEL_MAX_ATTEMPTS=2
```

## Gemini API onboarding (antes do primeiro uso)

1. Gere sua chave no Google AI Studio: <https://aistudio.google.com/apikey>.
2. Clique em **Create API key** e copie a chave.
3. No projeto, preencha `GEMINI_API_KEY` no arquivo `.env`.
4. Verifique limites ativos da sua conta em:
   - <https://ai.google.dev/gemini-api/docs/rate-limits>
5. Se precisar aumentar limites, consulte:
   - <https://ai.google.dev/gemini-api/docs/billing>

## Custos de referencia (snapshot 2026-02-24)

Fonte oficial: <https://ai.google.dev/gemini-api/docs/pricing>  
Estes valores podem mudar. Sempre valide na tabela oficial antes de uso intensivo.

| Modelo | Cota gratuita | Preco de entrada (1M tokens) | Preco de saida (1M tokens) |
|---|---|---|---|
| `gemini-3-pro-preview` | Nao | US$ 2.00 (<=200k) / US$ 4.00 (>200k) | US$ 12.00 (<=200k) / US$ 18.00 (>200k) |
| `gemini-2.5-flash` | Sim | US$ 0.30 (<=200k) / US$ 0.60 (>200k) | US$ 2.50 (<=200k) / US$ 3.50 (>200k) |
| `gemini-embedding-001` | Sim | US$ 0.15 | N/A |

Notas:
- Limites RPM/TPM/RPD dependem de modelo e tier da conta.
- No Google AI Studio, a cota gratuita e os limites aparecem no painel de rate limit da propria conta.
- O Ratio usa embeddings e geracao de texto; monitore consumo antes de processar lotes grandes.

## Data package (required)

For real queries, the app needs a prebuilt LanceDB index.

Expected path in project root:

```text
lancedb_store/
  jurisprudencia.lance/
```

Without this folder, `/api/query` cannot return results.

## Acervo (snapshot local)

Reference snapshot measured on **2026-02-24** over `lancedb_store/jurisprudencia` (the same table used by `/api/query`).

This snapshot is expected to evolve while ingestion jobs are running.

### Storage footprint

| Component | Size (GB, decimal) | Size (GiB, binary) |
|---|---:|---:|
| `data/` (SQLite and raw local assets) | 14.905 GB | 13.882 GiB |
| `lancedb_store/` (vector index + table files) | 8.559 GB | 7.971 GiB |
| **Total local footprint** | **23.464 GB** | **21.853 GiB** |

### Corpus size

- Indexed documents: **471,366**
- Non-empty `texto_integral`: **471,303**
- Total `texto_integral` volume: **2,507,247,355 characters**
- Total `texto_busca` volume: **1,738,788,368 characters**

### Physical-paper conversion (deterministic assumptions)

Assumption A (A4 legal print): **2,500 characters per page**
- **1,002,899 pages**
- **3,343 books** (300 pages/book)

Assumption B (denser book layout): **2,100 characters per page**
- **1,193,928 pages**
- **3,980 books** (300 pages/book)

### Distribution by document type (`texto_integral`)

| Type | Documents | Characters | Pages (2,500 chars/page) | Books (300 pages) |
|---|---:|---:|---:|---:|
| `monocratica` | 229,703 | 2,310,119,288 | 924,048 | 3,081 |
| `acordao` | 223,077 | 180,007,985 | 72,004 | 241 |
| `informativo` | 16,300 | 14,894,148 | 5,958 | 20 |
| `sumula` | 736 | 871,622 | 349 | 2 |
| `tema_repetitivo_stj` | 689 | 674,568 | 270 | 1 |
| `sumula_stj` | 641 | 251,481 | 101 | 1 |
| `monocratica_sv` | 112 | 388,580 | 156 | 1 |
| `sumula_vinculante` | 63 | 0 | 0 | 0 |
| `acordao_sv` | 45 | 39,683 | 16 | 1 |

`sumula_vinculante` is represented mainly via `texto_busca` in this snapshot, which is why `texto_integral` appears as zero for this type.

## Reranker download (required)

Default local reranker:

- `BAAI/bge-reranker-v2-m3`

It is downloaded automatically on first query. To pre-download manually:

```bash
py -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3')"
```

## Run the application

### Windows scripts (recommended)

Quick control menu:

```text
controle_jurisai_web.bat
```

Start:

```text
iniciar_jurisai_web.bat
```

Stop:

```text
desligar_jurisai_web.bat
```

Status:

```text
status_jurisai_web.bat
```

### Manual mode

Backend:

```bash
py -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```bash
py -m http.server 5500 --directory frontend
```

Open `http://127.0.0.1:5500`.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Fluxo amigavel (ZIP -> consulta -> desligar)

1. Baixe o ZIP e extraia a pasta.
2. Instale dependencias (`py -m pip install -r requirements.txt`).
3. Inicie com `controle_jurisai_web.bat` (opcao 1) ou `iniciar_jurisai_web.bat`.
4. Na primeira abertura, o modal **Primeiros passos com API Gemini** permite:
   - colar a chave Gemini;
   - validar a chave;
   - salvar automaticamente no `.env`.
5. Ajuste modelos/pesos no painel de configuracoes e clique em **Salvar ajustes**.
6. Faça consultas normalmente.
7. Para encerrar, use `controle_jurisai_web.bat` (opcao 2) ou `desligar_jurisai_web.bat`.

## Erros comuns e significado

| Codigo | Significado | Acao recomendada |
|---|---|---|
| `missing_api_key` | Chave Gemini ausente | Configurar chave no modal inicial ou `.env` |
| `invalid_api_key` | Chave invalida | Gerar nova chave no AI Studio e colar novamente |
| `api_key_not_active` | API/chave sem permissao ativa no projeto | Ativar Gemini API no projeto Google Cloud vinculado |
| `quota_exhausted` | Cota gratuita/paga esgotada | Esperar reset da cota ou ajustar billing/limites |
| `rate_limited` | Excesso de requisicoes por minuto | Reduzir paralelismo/frequencia |
| `model_unavailable` | Modelo escolhido indisponivel para sua conta | Trocar o modelo nas configuracoes |
| `upstream_unavailable` | Instabilidade temporaria do servico Gemini | Repetir tentativa em instantes |

## Tests

```bash
py -m pytest
```

## Open source notes

- Do not commit `.env` or API keys.
- See:
  - `CONTRIBUTING.md`
  - `CODE_OF_CONDUCT.md`
  - `SECURITY.md`
  - `LICENSE`

## Apoio ao projeto

Se o Ratio for util no seu fluxo de pesquisa, considere apoiar o projeto:

- GitHub Sponsors (configure o seu link): `https://github.com/sponsors/<seu-usuario>`
- PIX (adicione sua chave/canal oficial no README e na interface)

## Legal disclaimer

Ratio is a research assistant. It is not a substitute for formal legal advice.
Always verify primary sources before making legal decisions.

# Pacote Git-Ready (Ratio)

Esta pasta foi preparada para uso direto da aplicacao em maquina local.

## Incluidos

- Runtime da aplicacao: `backend/`, `frontend/`, `rag/`
- Dataset/index pronto para consulta: `lancedb_store/`
- Scripts de operacao: `iniciar_jurisai_web.bat`, `desligar_jurisai_web.bat`
- Documentacao e governanca: `README.md`, `ARCHITECTURE.md`, `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `docs/`
- Testes e CI: `tests/`, `.github/workflows/ci.yml`, `pytest.ini`
- Config base: `.env.example`, `.gitignore`, `requirements.txt`

## Excluidos propositalmente

- Scraping e ETL de coleta: `scrapers/`, `processors/`, `analysis/`
- Bases SQLite brutas: `data/`
- Artefatos gerados e logs locais

## Resultado pratico

Com esta pasta, o usuario final precisa apenas:

1. Instalar dependencias
2. Configurar `GEMINI_API_KEY`
3. Rodar `iniciar_jurisai_web.bat`

Sem etapa de scraping/ingestao para uso normal.


# Estrutura do Projeto Súmulas STF

Este documento descreve a organização dos arquivos e diretórios do projeto após a refatoração.

## 📂 Diretórios Principais

### `src/` (Proposto - Arquivos estão na raiz organizada por tipo)

O projeto foi organizado nas seguintes pastas para melhor clareza:

### 1. `scrapers/` (Coleta de Dados)
Scripts responsáveis por baixar dados do STF.
- **`monocraticas_scraper.py`**: Principal scraper para Decisões Monocráticas. Usa paginação recursiva por data.
- **`informativos_scraper.py`**: Scraper para Informativos STF.
- **`acordaos_scraper.py`**: Scraper para Acórdãos (versão atual estável).
- **`test_chrome.py`**: Teste de configuração do ambiente (Selenium/Playwright).

### 2. `processors/` (Processamento e Banco de Dados)
Scripts que transformam, categorizam ou migram dados.
- **`categorize_monocraticas.py`**: Script principal de IA. Lê do banco, classifica usando Gemini e atualiza o banco.
- **`auto_generate.py`**: Monitor que vigia o banco e aciona o gerador automaticamente quando a categorização termina.
- **`migrate_monocraticas_db.py`**: Script utilitário para migrações de esquema do banco de dados.
- **`organize_output.py`**: Move arquivos gerados para pastas por Ramo do Direito.

### 3. `generators/` (Saída e Exportação)
Scripts que leem do banco e geram arquivos finais (Markdown, TXT).
- **`generator_monocraticas.py`**: Gera arquivos Markdown organizados para o NotebookLM.
- **`generator_notebooklm.py`**: Gerador genérico/anterior.
- **`split_for_notebooklm.py`**: Utilitário para dividir arquivos grandes.

### 4. `analysis/` (Análise e Diagnóstico)
Scripts para verificar integridade, contar registros e debugar.
- **`check_*.py`**: Scripts de verificação rápida (ex: `check_db.py`, `check_monocraticas_db.py`).
- **`probe_*.py`**: Scripts de exploração de API e limites (ex: `probe_limit.py`).
- **`inspect_*.py`**: Inspeção profunda de schemas e tags.
- **`analyze_*.py`**: Análise estatística (ex: informativos por ano).
- **`diagnose_db.py`**: Diagnóstico de problemas no banco SQLite.

### 5. `data/` (Armazenamento)
Contém os bancos de dados SQLite.
- **`monocraticas/monocraticas.db`**: Banco principal das decisões monocráticas.
- **`acordaos/acordaos.db`**: Banco de acórdãos.
- **`informativos/informativos.db`**: Banco de informativos.
- **`sumulas/sumulas.db`**: Banco de súmulas.

### 6. `output_notebooklm/` (Saída Final)
Destino dos arquivos gerados para consumo.
- **`Decisoes_Monocraticas/`**: Contém os arquivos TXT/MD divididos por Ramo e Parte.

### 7. `legacy/` (Arquivo Morto)
Scripts antigos ou versões substituídas (`_v2`, `_v3`) mantidos para histórico.

### 8. `docs/` (Documentação)
Documentação do projeto, incluindo logs de tarefas e explicações de schema.

### 9. `logs/` (Logs de Execução)
Arquivos `.log` gerados pelos scripts (ex: `classificacao_monocraticas.log`).

---

## 🚀 Como Executar

Devido à reorganização, **certifique-se de rodar os scripts a partir da pasta raiz** (`d:\dev\sumulas-stf`).

Exemplos:
```bash
# Rodar o Scraper
py scrapers/monocraticas_scraper.py

# Rodar a Categorização (IA)
py processors/categorize_monocraticas.py

# Rodar a Geração de Arquivos
py generators/generator_monocraticas.py
```

Os caminhos internos (`DB_PATH`, `OUTPUT_DIR`) foram atualizados para funcionar com essa estrutura relativa.

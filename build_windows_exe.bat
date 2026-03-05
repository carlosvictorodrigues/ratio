@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo Ratio - Build executavel Windows
echo ============================================================
echo.

where py >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Python launcher "py" nao encontrado no PATH.
  exit /b 1
)

set "PY_CMD=py -3.12"
%PY_CMD% --version >nul 2>&1
if errorlevel 1 set "PY_CMD=py"
for /f "tokens=*" %%V in ('%PY_CMD% --version') do set "PY_VERSION=%%V"
echo [INFO] Python selecionado: %PY_VERSION%

set "DB_SOURCE=%CD%\lancedb_store"
set "DB_SOURCE_TABLE=%DB_SOURCE%\jurisprudencia.lance"
set "DIST_DB=%CD%\dist\Ratio\lancedb_store"
set "DIST_DB_TABLE=%DIST_DB%\jurisprudencia.lance"
set "DB_BACKUP_ROOT=%CD%\build\database_backups"
set "PLAYWRIGHT_BROWSERS_DIR=%CD%\_playwright_browsers"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BUILD_STAMP=%%I"
if "%BUILD_STAMP%"=="" set "BUILD_STAMP=manual"

if not exist "%DB_SOURCE_TABLE%" (
  echo [ERRO] Banco LanceDB nao encontrado em "%DB_SOURCE_TABLE%".
  echo [ERRO] Build interrompido para evitar pacote sem base jurisprudencial.
  exit /b 1
)

if exist "%DIST_DB_TABLE%" (
  set "DB_BACKUP_DIR=%DB_BACKUP_ROOT%\lancedb_store_%BUILD_STAMP%"
  if not exist "%DB_BACKUP_ROOT%" mkdir "%DB_BACKUP_ROOT%"
  echo [INFO] Backup preventivo do banco atual em dist...
  robocopy "%DIST_DB%" "!DB_BACKUP_DIR!" /E /R:1 /W:1 /NFL /NDL /NJH /NJS >nul
  if errorlevel 8 (
    echo [ERRO] Falha ao criar backup do banco em "!DB_BACKUP_DIR!".
    exit /b 1
  )
  echo [OK] Backup salvo em "!DB_BACKUP_DIR!".
)

echo [1/4] Instalando/atualizando dependencias de build...
%PY_CMD% -m pip install --upgrade pyinstaller pymupdf playwright
if errorlevel 1 (
  echo [ERRO] Falha ao instalar dependencias de build: PyInstaller/PyMuPDF/Playwright.
  exit /b 1
)

echo [2/4] Instalando Chromium local do Playwright...
set "PLAYWRIGHT_BROWSERS_PATH=%PLAYWRIGHT_BROWSERS_DIR%"
%PY_CMD% -m playwright install chromium
if errorlevel 1 (
  echo [ERRO] Falha ao instalar Chromium do Playwright em "%PLAYWRIGHT_BROWSERS_DIR%".
  exit /b 1
)

echo [3/4] Limpando artefatos antigos...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist Ratio.spec del /q Ratio.spec

echo [4/4] Gerando dist\Ratio\Ratio.exe ...
%PY_CMD% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --name Ratio ^
  --icon "frontend\favicon.ico" ^
  --add-data "frontend;frontend" ^
  --add-data "_playwright_browsers;_playwright_browsers" ^
  --collect-all "sentence_transformers" ^
  --collect-all "transformers" ^
  --collect-all "tokenizers" ^
  --collect-all "lancedb" ^
  --collect-all "pyarrow" ^
  --collect-all "pymupdf" ^
  --collect-all "playwright" ^
  --hidden-import "fitz" ^
  desktop_launcher.py
if errorlevel 1 (
  echo [ERRO] Falha no build do executavel.
  exit /b 1
)

echo [INFO] Copiando lancedb_store para dist\Ratio...
robocopy "%DB_SOURCE%" "%DIST_DB%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS >nul
if errorlevel 8 (
  echo [ERRO] Falha ao copiar lancedb_store para dist\Ratio.
  exit /b 1
)

if not exist "%DIST_DB_TABLE%" (
  echo [ERRO] Copia do banco concluida sem tabela principal.
  echo [ERRO] Verifique permissao/disco e execute o build novamente.
  exit /b 1
)

echo.
echo Build concluido.
echo Executavel: dist\Ratio\Ratio.exe
echo.
echo Banco de dados incluso: dist\Ratio\lancedb_store\
echo Backup local (quando aplicavel): build\database_backups\
echo.
echo IMPORTANTE:
echo 1) Copie .env para dist\Ratio\ (ou configure pela tela inicial)
echo 2) Execute apenas o arquivo Ratio.exe
echo.
exit /b 0

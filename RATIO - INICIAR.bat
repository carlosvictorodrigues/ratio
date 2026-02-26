@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

cd /d "%~dp0"
title Ratio - Pesquisa Jurisprudencial (Web Inicializador)

set "RUNTIME_DIR=%CD%\logs\runtime"
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

set "BACKEND_PID_FILE=%RUNTIME_DIR%\backend.pid"
set "FRONTEND_PID_FILE=%RUNTIME_DIR%\frontend.pid"
set "BACKEND_OUT=%RUNTIME_DIR%\backend.out.log"
set "BACKEND_ERR=%RUNTIME_DIR%\backend.err.log"
set "FRONTEND_OUT=%RUNTIME_DIR%\frontend.out.log"
set "FRONTEND_ERR=%RUNTIME_DIR%\frontend.err.log"

echo ============================================================
echo Ratio - Pesquisa Jurisprudencial (Web Inicializador)
echo ============================================================
echo.
echo [AVISO] E normal que o Banco de Dados (LanceDB) demore
echo         um pouco para compilar e iniciar na primeira 
echo         execucao do dia. Por favor, aguarde.
echo.

where py >nul 2>&1
if errorlevel 1 goto :NO_PY

set "PY_EXE="
for /f "delims=" %%I in ('where python 2^>nul') do if not defined PY_EXE set "PY_EXE=%%I"
if "%PY_EXE%"=="" set "PY_EXE=py"

set "BACKEND_STARTED_NOW=0"
set "FRONTEND_STARTED_NOW=0"
set "BACKEND_PID="
set "FRONTEND_PID="
set "BACKEND_RUNNING=0"
set "FRONTEND_RUNNING=0"

call :resolve_pid "%BACKEND_PID_FILE%" BACKEND_PID BACKEND_RUNNING
call :resolve_pid "%FRONTEND_PID_FILE%" FRONTEND_PID FRONTEND_RUNNING

if "%BACKEND_RUNNING%"=="1" goto :BACKEND_ALREADY_RUNNING
call :start_backend
if errorlevel 1 goto :BACKEND_FAIL
set "BACKEND_STARTED_NOW=1"
goto :BACKEND_AFTER_START

:BACKEND_ALREADY_RUNNING
echo [INFO] Backend ja em execucao - PID %BACKEND_PID%.

:BACKEND_AFTER_START
set "HEALTH_OK=0"
set /a HEALTH_TRIES=0
:WAIT_BACKEND_HEALTH
set /a HEALTH_TRIES+=1
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 set "HEALTH_OK=1"
if "%HEALTH_OK%"=="1" goto :BACKEND_READY
if %HEALTH_TRIES% GEQ 30 goto :BACKEND_HEALTH_FAIL
timeout /t 1 >nul
goto :WAIT_BACKEND_HEALTH

:BACKEND_READY
call :sync_pid_from_port 8000 "%BACKEND_PID_FILE%" BACKEND_PID
if errorlevel 1 echo [AVISO] Nao foi possivel sincronizar PID real do backend pela porta 8000.

if "%FRONTEND_RUNNING%"=="1" goto :FRONTEND_ALREADY_RUNNING
call :start_frontend
if errorlevel 1 goto :FRONTEND_FAIL
set "FRONTEND_STARTED_NOW=1"
goto :FRONTEND_AFTER_START

:FRONTEND_ALREADY_RUNNING
echo [INFO] Frontend ja em execucao - PID %FRONTEND_PID%.

:FRONTEND_AFTER_START
call :sync_pid_from_port 5500 "%FRONTEND_PID_FILE%" FRONTEND_PID
if errorlevel 1 echo [AVISO] Nao foi possivel sincronizar PID real do frontend pela porta 5500.

echo [3/3] Abrindo aplicacao no navegador...
start "" "http://127.0.0.1:5500"

echo.
echo Aplicacao iniciada.
echo - Frontend: http://127.0.0.1:5500
echo - Backend : http://127.0.0.1:8000
echo.
echo Para desligar: desligar_jurisai_web.bat
exit /b 0

:NO_PY
echo [ERRO] Python launcher "py" nao encontrado no PATH.
echo Instale Python 3.10+ e marque "Add Python to PATH".
pause
exit /b 1

:NO_PY_EXE
echo [ERRO] Falha ao resolver o executavel Python via launcher "py".
echo Verifique a instalacao do Python 3.10+.
pause
exit /b 1

:BACKEND_FAIL
echo [ERRO] Falha ao iniciar backend.
echo Verifique logs em: %BACKEND_ERR%
exit /b 1

:BACKEND_HEALTH_FAIL
echo [ERRO] Backend sem resposta em /health apos 30s.
echo Verifique logs em: %BACKEND_ERR%
if "%BACKEND_STARTED_NOW%"=="1" (
    if not "%BACKEND_PID%"=="" taskkill /PID %BACKEND_PID% /T /F >nul 2>&1
    if exist "%BACKEND_PID_FILE%" del /q "%BACKEND_PID_FILE%" >nul 2>&1
)
exit /b 1

:FRONTEND_FAIL
echo [ERRO] Falha ao iniciar frontend.
echo Verifique logs em: %FRONTEND_ERR%
if "%BACKEND_STARTED_NOW%"=="1" (
    if not "%BACKEND_PID%"=="" taskkill /PID %BACKEND_PID% /T /F >nul 2>&1
    if exist "%BACKEND_PID_FILE%" del /q "%BACKEND_PID_FILE%" >nul 2>&1
)
exit /b 1

:start_backend
echo [1/3] Iniciando backend FastAPI em http://127.0.0.1:8000 ...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $wd=(Resolve-Path '.').Path; $p=Start-Process -FilePath '%PY_EXE%' -ArgumentList @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $wd -RedirectStandardOutput '%BACKEND_OUT%' -RedirectStandardError '%BACKEND_ERR%' -PassThru; Set-Content -Path '%BACKEND_PID_FILE%' -Value $p.Id -NoNewline"
if errorlevel 1 exit /b 1
set "BACKEND_PID="
for /f "usebackq delims=" %%L in ("%BACKEND_PID_FILE%") do if not defined BACKEND_PID set "BACKEND_PID=%%L"
if "%BACKEND_PID%"=="" exit /b 1
echo [OK] Backend iniciado - PID %BACKEND_PID%.
exit /b 0

:start_frontend
echo [2/3] Iniciando frontend estatico em http://127.0.0.1:5500 ...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $wd=(Resolve-Path '.').Path; $p=Start-Process -FilePath '%PY_EXE%' -ArgumentList @('-m','http.server','5500','--directory','frontend') -WorkingDirectory $wd -RedirectStandardOutput '%FRONTEND_OUT%' -RedirectStandardError '%FRONTEND_ERR%' -PassThru; Set-Content -Path '%FRONTEND_PID_FILE%' -Value $p.Id -NoNewline"
if errorlevel 1 exit /b 1
set "FRONTEND_PID="
for /f "usebackq delims=" %%L in ("%FRONTEND_PID_FILE%") do if not defined FRONTEND_PID set "FRONTEND_PID=%%L"
if "%FRONTEND_PID%"=="" exit /b 1
echo [OK] Frontend iniciado - PID %FRONTEND_PID%.
exit /b 0

:resolve_pid
setlocal EnableDelayedExpansion
set "pid_file=%~1"
set "pid="
set "running=0"

if not exist "!pid_file!" (
    endlocal & set "%~2=" & set "%~3=0" & exit /b 0
)

for /f "usebackq delims=" %%L in ("!pid_file!") do if not defined pid set "pid=%%L"
if not defined pid (
    del /q "!pid_file!" >nul 2>&1
    endlocal & set "%~2=" & set "%~3=0" & exit /b 0
)

tasklist /FI "PID eq !pid!" 2>nul | find /I "!pid!" >nul
if errorlevel 1 (
    del /q "!pid_file!" >nul 2>&1
    endlocal & set "%~2=" & set "%~3=0" & exit /b 0
)

set "running=1"
endlocal & set "%~2=%pid%" & set "%~3=%running%" & exit /b 0

:sync_pid_from_port
setlocal EnableDelayedExpansion
set "port=%~1"
set "pid_file=%~2"
set "resolved_pid="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":!port! " ^| findstr "LISTENING"') do (
    if not defined resolved_pid set "resolved_pid=%%P"
)
if not defined resolved_pid (
    endlocal & set "%~3=" & exit /b 1
)
> "!pid_file!" echo(!resolved_pid!
endlocal & set "%~3=%resolved_pid%" & exit /b 0

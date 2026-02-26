@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

cd /d "%~dp0"
title Ratio - Pesquisa Jurisprudencial (Status)

set "RUNTIME_DIR=%CD%\logs\runtime"
set "BACKEND_PID_FILE=%RUNTIME_DIR%\backend.pid"
set "FRONTEND_PID_FILE=%RUNTIME_DIR%\frontend.pid"

echo ============================================================
echo Ratio - Status de Execucao
echo ============================================================
echo.

call :show_status "Backend" "%BACKEND_PID_FILE%" 8000
call :show_status "Frontend" "%FRONTEND_PID_FILE%" 5500

echo.
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2; if($r.StatusCode -eq 200){ Write-Output '[OK] Health endpoint do backend respondeu 200.'; exit 0 } else { Write-Output '[AVISO] Health endpoint respondeu status inesperado.'; exit 1 } } catch { Write-Output '[INFO] Health endpoint indisponivel no momento.'; exit 1 }"

echo.
exit /b 0

:show_status
setlocal EnableDelayedExpansion
set "label=%~1"
set "pid_file=%~2"
set "port=%~3"
set "pid="
set "running=0"

if exist "!pid_file!" (
    set /p pid=<"!pid_file!"
)

if defined pid (
    tasklist /FI "PID eq !pid!" 2>nul | find /I "!pid!" >nul
    if not errorlevel 1 set "running=1"
)

if "!running!"=="1" (
    echo [OK] !label!: em execucao - PID !pid!.
) else (
    echo [INFO] !label!: nao em execucao - PID file !pid_file!.
)

set "port_hit=0"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$pids = Get-NetTCPConnection -State Listen -LocalPort !port! -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($p in $pids) { Write-Output $p }"`) do (
    set "port_hit=1"
    echo [INFO] !label!: porta !port! em LISTENING - PID %%P.
)
if "!port_hit!"=="0" (
    echo [INFO] !label!: porta !port! sem listener.
)

endlocal
exit /b 0

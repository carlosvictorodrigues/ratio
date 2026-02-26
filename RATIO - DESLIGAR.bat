@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

cd /d "%~dp0"
title Ratio - Pesquisa Jurisprudencial (Web Desligamento)

set "RUNTIME_DIR=%CD%\logs\runtime"
set "BACKEND_PID_FILE=%RUNTIME_DIR%\backend.pid"
set "FRONTEND_PID_FILE=%RUNTIME_DIR%\frontend.pid"
set "BACKEND_CMD_REGEX=uvicorn\s+backend\.main:app"
set "FRONTEND_CMD_REGEX=http\.server\s+5500\s+--directory\s+frontend"

echo ============================================================
echo Ratio - Pesquisa Jurisprudencial (Web Desligamento)
echo ============================================================
echo.

call :kill_by_pid_file "%BACKEND_PID_FILE%" "Backend" "%BACKEND_CMD_REGEX%"
call :kill_by_pid_file "%FRONTEND_PID_FILE%" "Frontend" "%FRONTEND_CMD_REGEX%"

rem Fallback por porta com validacao de assinatura de comando.
call :kill_by_port 8000 "Backend" "%BACKEND_CMD_REGEX%"
call :kill_by_port 5500 "Frontend" "%FRONTEND_CMD_REGEX%"

echo.
echo Encerramento concluido.
exit /b 0

:kill_by_pid_file
setlocal EnableDelayedExpansion
set "pid_file=%~1"
set "label=%~2"
set "expected_regex=%~3"

if not exist "!pid_file!" (
    echo [INFO] !label!: PID file nao encontrado.
    endlocal
    exit /b 0
)

set /p pid=<"!pid_file!"
if not defined pid (
    echo [INFO] !label!: PID file vazio.
    del /q "!pid_file!" >nul 2>&1
    endlocal
    exit /b 0
)

call :kill_if_match "!pid!" "!label!" "!expected_regex!" "PID file"
if /I "!KILL_RESULT!"=="killed" (
    echo [OK] !label!: PID !pid! encerrado.
) else if /I "!KILL_RESULT!"=="mismatch" (
    echo [AVISO] !label!: PID !pid! ignorado - assinatura de comando diferente.
) else if /I "!KILL_RESULT!"=="absent" (
    echo [INFO] !label!: processo !pid! ja estava encerrado.
) else (
    echo [AVISO] !label!: falha ao encerrar PID !pid!.
)

del /q "!pid_file!" >nul 2>&1
endlocal
exit /b 0

:kill_by_port
setlocal EnableDelayedExpansion
set "port=%~1"
set "label=%~2"
set "expected_regex=%~3"
set "found=0"
set "killed_any=0"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%port% " ^| findstr "LISTENING"') do (
    set "found=1"
    call :kill_if_match "%%P" "!label!" "!expected_regex!" "porta !port!"
    if /I "!KILL_RESULT!"=="killed" (
        set "killed_any=1"
        echo [OK] !label!: PID %%P encerrado via porta !port!.
    )
)

if "!found!"=="0" (
    echo [INFO] !label!: nenhuma escuta ativa na porta !port!.
) else if "!killed_any!"=="0" (
    echo [INFO] !label!: escuta encontrada na porta !port!, mas nenhum processo com assinatura esperada.
)

endlocal
exit /b 0

:kill_if_match
setlocal EnableDelayedExpansion
set "pid=%~1"
set "label=%~2"
set "expected_regex=%~3"
set "source=%~4"
set "result=failed"

tasklist /FI "PID eq !pid!" 2>nul | find /I "!pid!" >nul
if errorlevel 1 (
    set "result=absent"
    endlocal & set "KILL_RESULT=%result%" & exit /b 0
)

powershell -NoProfile -Command "$proc = Get-CimInstance Win32_Process -Filter \"ProcessId=!pid!\" -ErrorAction SilentlyContinue; if (-not $proc) { exit 3 }; $cmd = [string]$proc.CommandLine; if ($cmd -match '%expected_regex%') { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    set "result=mismatch"
    endlocal & set "KILL_RESULT=%result%" & exit /b 0
)

taskkill /PID !pid! /T /F >nul 2>&1
if errorlevel 1 (
    set "result=failed"
) else (
    set "result=killed"
)
endlocal & set "KILL_RESULT=%result%" & exit /b 0

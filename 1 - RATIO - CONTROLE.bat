@echo off
setlocal EnableExtensions
chcp 65001 >nul

cd /d "%~dp0"
title Ratio - Controle Web

:MENU
cls
echo ============================================================
echo Ratio - Controle Rapido (Web)
echo ============================================================
echo [1] Ligar aplicacao (backend + frontend)
echo [2] Desligar aplicacao
echo [3] Ver status
echo [4] Abrir no navegador
echo [0] Sair
echo.
set /p CHOICE=Escolha uma opcao: 

if "%CHOICE%"=="1" goto START
if "%CHOICE%"=="2" goto STOP
if "%CHOICE%"=="3" goto STATUS
if "%CHOICE%"=="4" goto OPEN
if "%CHOICE%"=="0" goto END

echo.
echo Opcao invalida.
timeout /t 1 >nul
goto MENU

:START
echo [AVISO] E normal que o Banco de Dados (LanceDB) demore
echo         alguns instantes para compilar e iniciar na 
echo         primeira execucao do dia. Por favor, aguarde.
echo.
call RATIO - INICIAR.bat
goto WAIT_AND_BACK

:STOP
call desligar_jurisai_web.bat
goto WAIT_AND_BACK

:STATUS
call status_jurisai_web.bat
goto WAIT_AND_BACK

:OPEN
start "" "http://127.0.0.1:5500"
echo Navegador acionado em http://127.0.0.1:5500
goto WAIT_AND_BACK

:WAIT_AND_BACK
echo.
pause
goto MENU

:END
exit /b 0

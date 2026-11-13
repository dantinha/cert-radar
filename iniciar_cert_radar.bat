@echo off
title CertRadar - Local Server
cd /d "%~dp0"

echo [CertRadar] Inicializando ambiente...

if exist "%~dp0.venv\Scripts\python.exe" (
    echo [CertRadar] Iniciando painel web em http://127.0.0.1:8000 ...
    "%~dp0.venv\Scripts\python.exe" -m cert_radar serve %*
) else (
    echo [CertRadar] Ambiente virtual nao encontrado em %~dp0.venv.
    echo Tentando executar via uv...
    uv run cert-radar serve %*
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERRO] Ocorreu uma falha ao iniciar o CertRadar.
    pause
)

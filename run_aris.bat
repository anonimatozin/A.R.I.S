@echo off
title A.R.I.S. - Assistente de Raciocinio e Integracao de Sistemas
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

echo Iniciando A.R.I.S. ...
echo.

if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe main.py
) else (
    python main.py
)

echo.
pause
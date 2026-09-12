@echo off
chcp 65001 >nul
title A.R.I.S. - Assistente de Raciocínio e Integração de Sistemas
color 0B
cls

echo ============================================================
echo  A.R.I.S. - Assistente de Raciocínio e Integração de Sistemas
echo ============================================================
echo.

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python main.py

pause
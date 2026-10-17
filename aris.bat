@echo off
:: A.R.I.S. CLI — Chamado de qualquer pasta
:: funciona como: aris [comando]
set "ARIS_DIR=%~dp0"
set "PYTHON=%ARIS_DIR%\venv\Scripts\python.exe"

:: Guardar pasta atual do usuario
set "ARIS_CWD=%CD%"

:: Rodar CLI
cd /d "%ARIS_DIR%"
set PYTHONPATH=%ARIS_DIR%
"%PYTHON%" "%ARIS_DIR%\agent\aris_cli.py" %*

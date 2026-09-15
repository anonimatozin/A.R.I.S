@echo off
:: A.R.I.S. Launcher
:: Inicia o A.R.I.S. com o Python do venv
set "ARIS_DIR=C:\Users\Administrator\Documents\Default Project\ARIS"
set "PYTHON=%ARIS_DIR%\venv\Scripts\python.exe"

cd /d "%ARIS_DIR%"
set PYTHONPATH=%ARIS_DIR%
"%PYTHON%" main.py %*

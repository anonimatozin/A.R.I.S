@echo off
title J.A.R.V.I.S.
color 0B
cls

echo ============================================================
echo  J.A.R.V.I.S. - Just A Rather Very Intelligent System
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

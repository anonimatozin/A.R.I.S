@echo off
title A.R.I.S.
color 0B
cls

echo ============================================================
echo  A.R.I.S. - Just A Rather Very Intelligent System
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

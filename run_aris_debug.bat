@echo off
title A.R.I.S. - Diagnostico
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set LOG=aris_boot.log

echo === ARIS diagnostico %DATE% %TIME% === > "%LOG%"
echo --- processos python ativos --- >> "%LOG%"
tasklist /FI "IMAGENAME eq python.exe" >> "%LOG%" 2>&1
echo --- venv --- >> "%LOG%"
if exist venv\Scripts\python.exe (echo VENV-OK >> "%LOG%") else (echo VENV-FALTANDO >> "%LOG%")
echo --- portas 8765/8766/8770/8790 --- >> "%LOG%"
netstat -ano | findstr "8765 8766 8770 8790" >> "%LOG%" 2>&1
echo --- boot (15s) --- >> "%LOG%"

if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe cll1/main.py >> "%LOG%" 2>&1
) else (
    python cll1/main.py >> "%LOG%" 2>&1
)

echo.
echo Saiu com codigo %ERRORLEVEL%. Log em %CD%\%LOG%
echo Cole o conteudo de %LOG% no chat da ARIS.
pause

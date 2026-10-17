@echo off
title A.R.I.S. Gesture Trainer
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

echo Iniciando ARIS Gesture Trainer ...
echo (feche o HUD/navegador usando a camera antes)
echo.

if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe -m gesture_trainer.main %*
) else (
    python -m gesture_trainer.main %*
)

echo.
pause

@echo off
:: ARIS_WDOG.BAT — Inicia o watchdog escondido (sem janela)
:: Chamado pelo Task Scheduler no logon

set "ARIS_DIR=C:\Users\Administrator\Documents\Default Project\ARIS"
set "PYTHON=C:\Program Files\Python312\python.exe"

:: Iniciar watchdog escondido via VBS
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.CurrentDirectory = "%ARIS_DIR%"
echo WshShell.Run """%PYTHON%"" ""%ARIS_DIR%\agent\aris_watchdog.py""", 0, False
) > "%ARIS_DIR%\agent\_watchdog_start.vbs"

start "" wscript.exe "%ARIS_DIR%\agent\_watchdog_start.vbs"

@echo off
:: ARIS_LISTENER.BAT — Inicia o PC Listener escondido
:: Chamado pelo Watchdog

set "ARIS_DIR=C:\Users\Administrator\Documents\Default Project\ARIS"
set "PYTHON=C:\Program Files\Python312\python.exe"

:: Iniciar listener escondido via VBS
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.CurrentDirectory = "%ARIS_DIR%"
echo WshShell.Run """%PYTHON%"" ""%ARIS_DIR%\agent\pc_listener.py""", 0, False
) > "%ARIS_DIR%\agent\_listener_start.vbs"

start "" wscript.exe "%ARIS_DIR%\agent\_listener_start.vbs"

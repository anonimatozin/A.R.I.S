"""aris_watchdog.py — Monitora e mantém o PC Listener rodando.

Roda em loop infinito, verifica a cada 30 segundos se o listener tá vivo.
Se morreu, reinicia. Se o pendrive mudou, sincroniza.

Uso:
    python aris_watchdog.py          # Roda em background
    python aris_watchdog.py --once   # Verifica uma vez e sai
"""

import os
import sys
import time
import json
import urllib.request
import subprocess
import logging
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).parent.parent
LOG_FILE = PROJECT_DIR / "logs" / "watchdog.log"
LISTENER_URL = "http://127.0.0.1:8770"
SYNC_SCRIPT = PROJECT_DIR / "agent" / "aris_sync.py"
LISTENER_SCRIPT = PROJECT_DIR / "agent" / "pc_listener.py"
CHECK_INTERVAL = 30  # segundos
SYNC_INTERVAL = 300  # 5 minutos

# Configurar logging
LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("watchdog")


def is_listener_alive():
    """Verifica se o PC Listener tá respondendo."""
    try:
        req = urllib.request.Request(
            f"{LISTENER_URL}/health",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_listener():
    """Inicia o PC Listener escondido (sem janela)."""
    try:
        bat_file = PROJECT_DIR / "agent" / "start_listener.bat"
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_file)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        log.info("PC Listener iniciado via start_listener.bat")
        return True
    except Exception as e:
        log.error(f"Falha ao iniciar listener: {e}")
        return False


def sync_pendrive():
    """Sincroniza com pendrive se conectado."""
    try:
        python_exe = sys.executable
        result = subprocess.run(
            [python_exe, str(SYNC_SCRIPT), "push"],
            capture_output=True, text=True, timeout=30,
            cwd=str(PROJECT_DIR),
        )
        if result.returncode == 0 and "Pendrive encontrado" in result.stdout:
            log.info("Sync pendrive concluido")
    except Exception as e:
        log.warning(f"Sync pendrive falhou: {e}")


def run_watchdog():
    """Loop principal do watchdog."""
    log.info("=== A.R.I.S. Watchdog iniciado ===")
    log.info(f"Verificando listener a cada {CHECK_INTERVAL}s")
    log.info(f"Sync pendrive a cada {SYNC_INTERVAL}s")
    
    last_sync = 0
    restart_count = 0
    max_restarts = 10  # Max reinicios antes de pausar
    
    while True:
        now = time.time()
        
        # Verificar listener
        if is_listener_alive():
            if restart_count > 0:
                log.info(f"Listener voltou! (reiniciado {restart_count} vezes)")
                restart_count = 0
        else:
            log.warning("Listener offline! Reiniciando...")
            if restart_count < max_restarts:
                if start_listener():
                    restart_count += 1
                    time.sleep(5)  # Esperar iniciar
                else:
                    log.error("Nao conseguiu iniciar o listener")
                    restart_count += 1
            else:
                log.error(f"Muitos reinicios ({restart_count}). Pausando 5 minutos.")
                time.sleep(300)
                restart_count = 0
                continue
        
        # Sync pendrive periodicamente
        if now - last_sync > SYNC_INTERVAL:
            sync_pendrive()
            last_sync = now
        
        time.sleep(CHECK_INTERVAL)


def run_once():
    """Verifica uma vez e mostra status."""
    alive = is_listener_alive()
    print(f"PC Listener: {'ONLINE' if alive else 'OFFLINE'}")
    
    # Verificar pendrive
    for letter in "DEFGHIJ":
        drive = Path(f"{letter}:\\")
        if (drive / "ARIS_MEMORY").exists():
            print(f"Pendrive: {letter}:\\ARIS_MEMORY (conectado)")
            break
    else:
        print("Pendrive: nao detectado")
    
    return alive


if __name__ == "__main__":
    if "--once" in sys.argv:
        sys.exit(0 if run_once() else 1)
    else:
        run_watchdog()

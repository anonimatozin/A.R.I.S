"""cll1_uptime_watchdog.py — Monitora uptime do CLL1 e reinicia serviços se necessário.

Uso:
    python cll1_uptime_watchdog.py              # Roda em loop (a cada 10 min)
    python cll1_uptime_watchdog.py --once       # Verifica uma vez
    python cll1_uptime_watchdog.py --set-max 12 # Define max horas (default: 24)
"""

import subprocess
import sys
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

LOG_FILE = Path.home() / "cll1" / "data" / "uptime_watchdog.log"
MAX_HOURS = 24  # Reiniciar serviços apos 24h ligado
CHECK_INTERVAL = 600  # 10 minutos
COOLDOWN = 300  # 5 min sem reiniciar depois de um restart
_last_restart = 0

def get_uptime_hours():
    """Retorna horas desde o ultimo boot."""
    try:
        with open("/proc/uptime") as f:
            uptime_secs = float(f.read().split()[0])
        return uptime_secs / 3600
    except Exception:
        return 0

def get_memory_info():
    """Retorna info de RAM."""
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        info = {}
        for line in lines:
            parts = line.split()
            if parts[0] in ("MemTotal:", "MemAvailable:", "MemFree:", "SwapTotal:", "SwapFree:"):
                info[parts[0]] = int(parts[1])  # kB
        total = info.get("MemTotal:", 0) / 1024  # MB
        available = info.get("MemAvailable:", 0) / 1024
        swap_total = info.get("SwapTotal:", 0) / 1024
        swap_free = info.get("SwapFree:", 0) / 1024
        return {
            "total_mb": total,
            "available_mb": available,
            "used_mb": total - available,
            "percent_used": ((total - available) / total * 100) if total > 0 else 0,
            "swap_total_mb": swap_total,
            "swap_free_mb": swap_free,
        }
    except Exception:
        return {}

def check_services():
    """Verifica status dos serviços principais."""
    services = {}
    for svc in ["cll1-main", "cll1-gateway"]:
        r = subprocess.run(["sv", "status", svc], capture_output=True, text=True, timeout=5)
        services[svc] = "up" in r.stdout.lower()
    return services

def restart_services():
    """Reinicia serviços do CLL1."""
    log("REINICIANDO SERVIÇOS...")
    subprocess.run(["sv", "restart", "cll1-main"], timeout=10)
    time.sleep(3)
    log("Serviços reiniciados.")

def log(msg):
    """Escreve no log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def check_and_act():
    """Verifica uptime e memória, toma ação se necessário."""
    uptime = get_uptime_hours()
    mem = get_memory_info()
    services = check_services()

    log(f"Uptime: {uptime:.1f}h | RAM: {mem.get('used_mb',0):.0f}/{mem.get('total_mb',0):.0f}MB ({mem.get('percent_used',0):.0f}%) | Services: {services}")

    actions = []

    # 1. Uptime excessivo — reiniciar serviços
    if uptime > MAX_HOURS:
        actions.append(f"uptime {uptime:.1f}h > {MAX_HOURS}h")

    # 2. RAM muito baixa — reiniciar Ollama
    if mem.get("available_mb", 999) < 200:
        actions.append(f"RAM baixa: {mem.get('available_mb',0):.0f}MB livre")
        log("Matando Ollama pra liberar RAM...")
        subprocess.run(["pkill", "-f", "ollama serve"], timeout=5)

    # 3. Swap quase cheia — reiniciar serviços
    if mem.get("swap_free_mb", 999) < 100 and mem.get("swap_total_mb", 0) > 0:
        actions.append(f"Swap baixa: {mem.get('swap_free_mb',0):.0f}MB livre")

    # 4. Serviço morto — reiniciar
    for svc, alive in services.items():
        if not alive:
            actions.append(f"{svc} morto")

    if actions:
        log(f"Ações necessárias: {', '.join(actions)}")
        global _last_restart
        if time.time() - _last_restart < COOLDOWN:
            log("Cooldown ativo, aguardando...")
            return
        restart_services()
        _last_restart = time.time()
    else:
        log("Tudo OK.")

def main():
    if "--set-max" in sys.argv:
        idx = sys.argv.index("--set-max")
        if idx + 1 < len(sys.argv):
            global MAX_HOURS
            MAX_HOURS = float(sys.argv[idx + 1])
            log(f"Max uptime definido para {MAX_HOURS}h")
            return

    if "--once" in sys.argv:
        check_and_act()
        return

    log(f"=== Uptime Watchdog iniciado (max: {MAX_HOURS}h, check: {CHECK_INTERVAL}s) ===")
    while True:
        try:
            check_and_act()
        except Exception as e:
            log(f"Erro: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()

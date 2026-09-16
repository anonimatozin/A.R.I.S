"""setup_persistent.py — Configura CLL1 pra manter A.R.I.S. rodando sempre."""
import subprocess
import os

def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

print("=== A.R.I.S. Persistent Setup ===\n")

# 1. Wake lock
print("[1/4] Ativando wake lock...")
out, rc = run("termux-wake-lock")
print(f"  Resultado: {out or 'ok'}")

# 2. Tornar scripts executaveis
print("[2/4] Configurando permissao dos scripts...")
run("chmod +x ~/keep_alive.sh ~/aris_keep_alive.sh")
print("  OK")

# 3. Verificar se keep_alive ja esta no crontab
print("[3/4] Verificando crontab...")
out, _ = run("crontab -l")
if "keep_alive" not in out:
    # Adicionar ao crontab
    new_cron = out + "\n*/5 * * * * ~/keep_alive.sh\n"
    proc = subprocess.run("crontab -", shell=True, input=new_cron, capture_output=True, text=True)
    print("  keep_alive adicionado ao crontab (a cada 5 min)")
else:
    print("  keep_alive ja esta no crontab")

# 4. Verificar status
print("[4/4] Verificando status...")
out, _ = run("pgrep -f cll1_main")
if out:
    print(f"  Gateway: RODANDO (PID: {out})")
else:
    print("  Gateway: PARADO — reiniciando...")
    run("cd ~/cll1 && nohup python main.py &")

print("\n=== Configuracao manual necessaria no celular ===")
print("1. Configuracoes > Bateria > Termux > Nao restricao")
print("2. Configuracoes > Tela > Tempo de desligamento > Nunca")
print("3. Configuracoes > Bateria > Economia de bateria > Desligar")
print("\nPronto! A.R.I.S. deve continuar rodando mesmo com tela desligada.")

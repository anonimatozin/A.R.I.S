#!/bin/bash
# aris_keep_alive.sh — Monitora e reinicia A.R.I.S. no CLL1
# Rodar com: nohup ~/aris_keep_alive.sh &
# Ou adicionar ao crontab: */3 * * * * ~/aris_keep_alive.sh

LOG=~/aris_keep_alive.log
CLL1_DIR=~/cll1

log_msg() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> "$LOG"
}

# Manter wake lock
termux-wake-lock 2>/dev/null

# Verificar se o gateway esta rodando
if ! pgrep -f "cll1_main" >/dev/null 2>&1; then
    log_msg "Gateway cll1_main parou! Reiniciando..."
    cd "$CLL1_DIR" && nohup python main.py >> "$LOG" 2>&1 &
    sleep 3
    if pgrep -f "cll1_main" >/dev/null 2>&1; then
        log_msg "Gateway reiniciado com sucesso"
    else
        log_msg "ERRO: Falha ao reiniciar gateway"
    fi
fi

# Verificar conexao de rede
if ! ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
    log_msg "Sem conexao de rede! Tentando reconnect..."
    # Tentar reconectar WiFi
    if command -v svc &>/dev/null; then
        svc wifi disable
        sleep 2
        svc wifi enable
        sleep 5
    fi
fi

# Limpar log antigo (manter ultimas 500 linhas)
if [ -f "$LOG" ] && [ $(wc -l < "$LOG") -gt 1000 ]; then
    tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

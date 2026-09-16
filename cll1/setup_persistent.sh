#!/bin/bash
# setup_persistent.sh — Configura CLL1 pra manter A.R.I.S. rodando sempre
# Rodar uma vez no Termux: bash setup_persistent.sh

set -e

echo "=== A.R.I.S. Persistent Setup ==="
echo ""

# 1. Wake lock — impede que o Termux durma
echo "[1/6] Ativando wake lock do Termux..."
termux-wake-lock 2>/dev/null || echo "  (wake lock nao disponivel via termux-api, configurando manualmente)"

# 2. Desabilitar battery optimization pro Termux
echo "[2/6] Desabilitando battery optimization..."
if command -v termux-battery-status &>/dev/null; then
    echo "  termux-api disponivel"
else
    echo "  Instale termux-api: pkg install termux-api"
fi

# 3. Configurar screen timeout pra máximo (nunca desligar)
echo "[3/6] Configurando screen timeout..."
# Desabilitar screen off via settings (requer root ou ADB)
if command -v settings &>/dev/null; then
    settings put system screen_off_timeout 2147483647 2>/dev/null && echo "  Screen timeout: MAX" || echo "  (precisa de permissao)"
else
    echo "  settings nao encontrado — configure manualmente:"
    echo "  Configuracoes > Tela > Tempo de desligamento > Nunca"
fi

# 4. Manter WiFi ligado quando tela desliga
echo "[4/6] Configurando WiFi keep-alive..."
if command -v settings &>/dev/null; then
    settings put global wifi_sleep_policy 2 2>/dev/null && echo "  WiFi: sempre ligado" || echo "  (precisa de permissao)"
fi

# 5. Desabilitar bateria saver
echo "[5/6] Desabilitando bateria saver..."
if command -v settings &>/dev/null; then
    settings put global low_power 0 2>/dev/null && echo "  Bateria saver: desligado" || echo "  (precisa de permissao)"
fi

# 6. Criar script de keep-alive
echo "[6/6] Criando keep-alive script..."
cat > ~/keep_alive.sh << 'KEEPEOF'
#!/bin/bash
# keep_alive.sh — Roda em loop, reinicia serviços se morrerem
# Adicionar ao crontab: crontab -e -> */5 * * * * ~/keep_alive.sh

LOG=~/keep_alive.log

check_and_restart() {
    local name="$1"
    local cmd="$2"
    if ! pgrep -f "$name" >/dev/null 2>&1; then
        echo "$(date): Restarting $name" >> "$LOG"
        nohup $cmd >> "$LOG" 2>&1 &
        sleep 2
    fi
}

# Manter gateway rodando
check_and_restart "cll1_main" "cd ~/cll1 && python main.py"

# Manter wake lock
termux-wake-lock 2>/dev/null
KEEPEOF
chmod +x ~/keep_alive.sh

# 7. Configurar crontab pra keep-alive
echo ""
echo "=== Configuracao adicional necessaria ==="
echo ""
echo "Para manter tudo rodando, faca ESTAS configuracoes MANUAIS no celular:"
echo ""
echo "1. CONFIGURACOES > BATERIA > Termux > Nao restricao"
echo "   (Impede o Android de matar o Termux)"
echo ""
echo "2. CONFIGURACOES > TELA > Tempo de desligamento > NUNCA"
echo "   (Ou 30 min no minimo)"
echo ""
echo "3. CONFIGURACOES > BATERIA > Economia de bateria > DESLIGAR"
echo ""
echo "4. No Termux, rode:"
echo "   pkg install termux-api"
echo "   termux-wake-lock"
echo ""
echo "5. Para manter vivo 24/7, rode:"
echo "   crontab -e"
echo "   Adicione: */5 * * * * ~/keep_alive.sh"
echo ""
echo "=== Setup completo! ==="

#!/data/data/com.termux/files/usr/bin/bash
# ARIS Auto-Start Script
# Executa quando o dispositivo inicia

cd ~/cll1

# Wake lock - manter Termux ativo com tela off
termux-wake-lock

# Esperar rede
sleep 10

# Verificar se ja esta rodando
if pgrep -f "python -m cll1.main" > /dev/null; then
    echo "ARIS ja rodando"
    exit 0
fi

# Iniciar ARIS
echo "Iniciando ARIS..."
nohup python -m cll1.main > /tmp/aris.log 2>&1 &

echo "ARIS iniciado (PID: $!)"

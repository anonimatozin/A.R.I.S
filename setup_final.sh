#!/data/data/com.termux/files/usr/bin/sh
# ============================================================
# A.R.I.S. CLL1 — Setup Final (executar no Termux)
# ============================================================
# Este script completa o deploy da arquitetura CLL1.
# Todos os arquivos já foram enviados do PC.
#
# Uso:
#   chmod +x ~/cll1/setup_final.sh
#   ~/cll1/setup_final.sh
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

CLL1_DIR="$HOME/cll1"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error(){ echo -e "${RED}[ERRO]${NC} $1"; }

echo ""
echo "=========================================="
echo "  A.R.I.S. CLL1 — Setup Final"
echo "=========================================="
echo ""

# ── 1. Matar gateway antigo ────────────────────────────────
log_info "Parando gateway antigo..."
pkill -f "python gateway.py" 2>/dev/null || true
sleep 2
log_ok "Gateway antigo parado"

# ── 2. Instalar dependências Python ────────────────────────
log_info "Instalando dependências Python..."
pip install discord.py openai --quiet 2>/dev/null && log_ok "discord.py e openai instalados" || log_warn "Algumas dependências falharam"

# ── 3. Verificar arquivos deployados ───────────────────────
log_info "Verificando arquivos..."
FILES=(
    "gateway.py"
    "cll1/__init__.py"
    "cll1/main.py"
    "cll1/router.py"
    "edge/__init__.py"
    "edge/edge_config.py"
    "edge/edge_chat.py"
    "edge/edge_sync.py"
    "modules/discord_bot.py"
    "utils/logger.py"
    ".env"
)

ALL_OK=true
for f in "${FILES[@]}"; do
    if [ -f "$CLL1_DIR/$f" ]; then
        echo -e "  ${GREEN}✓${NC} $f"
    else
        echo -e "  ${RED}✗${NC} $f — AUSENTE"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    log_error "Alguns arquivos estão ausentes!"
    log_warn "Execute o deploy do PC novamente."
    exit 1
fi
log_ok "Todos os arquivos presentes"

# ── 4. Verificar .env ──────────────────────────────────────
log_info "Verificando .env..."
if grep -q "CLL1_TOKEN=.\\+" "$CLL1_DIR/.env" 2>/dev/null; then
    log_ok "CLL1_TOKEN configurado"
else
    log_error "CLL1_TOKEN não configurado em $CLL1_DIR/.env"
    exit 1
fi

if grep -q "DISCORD_BOT_TOKEN=.\\+" "$CLL1_DIR/.env" 2>/dev/null; then
    log_ok "DISCORD_BOT_TOKEN configurado"
else
    log_warn "DISCORD_BOT_TOKEN não configurado — Discord desativado"
fi

if grep -q "EDGE_GROQ_API_KEY=.\\+" "$CLL1_DIR/.env" 2>/dev/null; then
    log_ok "EDGE_GROQ_API_KEY configurado"
else
    log_warn "EDGE_GROQ_API_KEY não configurado — Edge desativado"
fi

# ── 5. Verificar IP correto ────────────────────────────────
log_info "Verificando configuração de IP..."
if grep -q "192.168.0.104" "$CLL1_DIR/cll1/router.py" 2>/dev/null; then
    log_warn "IP antigo (192.168.0.104) encontrado em router.py — corrigindo..."
    sed -i 's/192.168.0.104/192.168.0.106/g' "$CLL1_DIR/cll1/router.py"
    log_ok "IP corrigido em router.py"
fi

if grep -q "192.168.0.104" "$CLL1_DIR/edge/edge_config.py" 2>/dev/null; then
    log_warn "IP antigo encontrado em edge_config.py — corrigindo..."
    sed -i 's/192.168.0.104/192.168.0.106/g' "$CLL1_DIR/edge/edge_config.py"
    log_ok "IP corrigido em edge_config.py"
fi

if grep -q "192.168.0.104" "$CLL1_DIR/.env" 2>/dev/null; then
    log_warn "IP antigo encontrado em .env — corrigindo..."
    sed -i 's/192.168.0.104/192.168.0.106/g' "$CLL1_DIR/.env"
    log_ok "IP corrigido em .env"
fi

log_ok "IP 192.168.0.106 configurado"

# ── 6. Criar diretórios necessários ────────────────────────
log_info "Criando diretórios..."
mkdir -p "$CLL1_DIR/logs"
mkdir -p "$CLL1_DIR/data/database"
mkdir -p "$CLL1_DIR/data/memory"
log_ok "Diretórios criados"

# ── 7. Iniciar gateway ─────────────────────────────────────
log_info "Iniciando gateway..."
cd "$CLL1_DIR"
nohup python gateway.py > "$CLL1_DIR/logs/gateway.log" 2>&1 &
GATEWAY_PID=$!
echo $GATEWAY_PID > "$CLL1_DIR/gateway.pid"
sleep 3

if kill -0 $GATEWAY_PID 2>/dev/null; then
    log_ok "Gateway iniciado (PID: $GATEWAY_PID)"
else
    log_error "Falha ao iniciar gateway"
    cat "$CLL1_DIR/logs/gateway.log"
    exit 1
fi

# ── 8. Testar gateway ──────────────────────────────────────
log_info "Testando gateway..."
python -c "
import socket, json, os

token = None
with open('$CLL1_DIR/.env') as f:
    for line in f:
        if line.startswith('CLL1_TOKEN='):
            token = line.split('=', 1)[1].strip()
            break

if not token:
    print('ERRO: token não encontrado')
    exit(1)

data = json.dumps({'type': 'admin_ping', 'token': token}).encode()
with socket.create_connection(('127.0.0.1', 8765), timeout=5) as s:
    s.sendall(len(data).to_bytes(8, 'big'))
    s.sendall(data)
    size = int.from_bytes(s.recv(8), 'big')
    resp = b''
    while len(resp) < size:
        resp += s.recv(min(65536, size - len(resp)))
    result = json.loads(resp)
    if result.get('ok'):
        print('GATEWAY OK')
    else:
        print('GATEWAY FALHOU:', result)
        exit(1)
" && log_ok "Gateway respondendo" || log_error "Gateway não responde"

# ── 9. Configurar serviço cll1-main ────────────────────────
log_info "Configurando serviço cll1-main..."
if command -v sv &> /dev/null; then
    SERVICE_DIR="$PREFIX/var/service/cll1-main"
    mkdir -p "$SERVICE_DIR"
    
    cat > "$SERVICE_DIR/run" << 'RUNEOF'
#!/data/data/com.termux/files/usr/bin/sh
cd "$HOME/cll1" || exit 1
export PYTHONPATH="$HOME/cll1"
exec python -m cll1.main
RUNEOF
    chmod 700 "$SERVICE_DIR/run"
    log_ok "Serviço cll1-main configurado"
    
    # Habilitar serviço
    if command -v sv-enable &> /dev/null; then
        sv-enable cll1-main 2>/dev/null && log_ok "Serviço habilitado para auto-start" || log_warn "Falha ao habilitar serviço"
    fi
else
    log_warn "termux-services não encontrado — serviço configurado manualmente"
    log_warn "Para auto-start, instale: pkg install termux-services"
fi

# ── 10. Verificar status final ─────────────────────────────
echo ""
echo "=========================================="
echo "  A.R.I.S. CLL1 — Status Final"
echo "=========================================="
echo ""

# Gateway
echo -n "Gateway: "
if kill -0 $GATEWAY_PID 2>/dev/null; then
    echo -e "${GREEN}ONLINE${NC} (PID: $GATEWAY_PID)"
else
    echo -e "${RED}OFFLINE${NC}"
fi

# .env
echo -n "ENV:     "
if [ -f "$CLL1_DIR/.env" ]; then
    echo -e "${GREEN}configurado${NC}"
else
    echo -e "${RED}AUSENTE${NC}"
fi

# Banco
echo -n "Banco:   "
if [ -f "$CLL1_DIR/data/database/aris_memory.db" ] || [ -f "$CLL1_DIR/data/aris.db" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${YELLOW}não inicializado${NC}"
fi

# Serviço
echo -n "Serviço: "
if command -v sv &> /dev/null; then
    STATUS=$(sv status cll1-main 2>/dev/null || echo "parado")
    echo "$STATUS"
else
    echo -e "${YELLOW}termux-services indisponível${NC}"
fi

# Discord
echo -n "Discord: "
if grep -q "DISCORD_BOT_TOKEN=.\\+" "$CLL1_DIR/.env" 2>/dev/null; then
    echo -e "${GREEN}configurado${NC}"
else
    echo -e "${YELLOW}não configurado${NC}"
fi

# Arquitetura
echo ""
echo "Arquivos deployados:"
echo "  cll1/__init__.py    cll1/main.py    cll1/router.py"
echo "  edge/__init__.py    edge/edge_config.py    edge/edge_chat.py"
echo "  modules/discord_bot.py    utils/logger.py"
echo "  gateway.py"
echo ""
echo "IP: 192.168.0.106 (porta 8765)"
echo ""

echo "=========================================="
log_ok "Setup concluído!"
echo "=========================================="
echo ""
echo "Comandos úteis:"
echo "  ./cll1_service.sh status    — Ver status"
echo "  ./cll1_service.sh health    — Verificar saúde"
echo "  ./cll1_service.sh logs      — Ver logs"
echo "  ./cll1_service.sh restart   — Reiniciar"
echo ""

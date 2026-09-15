#!/data/data/com.termux/files/usr/bin/sh
# ============================================================
# A.R.I.S. CLL1 — Setup automatico para Termux
# ============================================================
# Instala e configura o CLL1 (instancia edge) no Termux.
# Execucao idempotente — pode ser executado varias vezes.
#
# Uso:
#   chmod +x setup_cll1.sh
#   ./setup_cll1.sh
# ============================================================

set -e

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Diretorios
CLL1_DIR="$HOME/cll1"
ARIS_DIR="$HOME/aris"
DATA_DIR="$CLL1_DIR/data"
LOGS_DIR="$CLL1_DIR/logs"
DB_DIR="$DATA_DIR/database"
SERVICES_DIR="$PREFIX/var/service"

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_ok() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERRO]${NC} $1"
}

# ============================================================
# 1. Verificar pre-requisitos
# ============================================================
check_prereqs() {
    log_info "Verificando pre-requisitos..."

    # Python
    if ! command -v python &> /dev/null; then
        log_error "Python nao encontrado. Instalando..."
        pkg update -y
        pkg install -y python
    fi
    log_ok "Python: $(python --version 2>&1)"

    # Git
    if ! command -v git &> /dev/null; then
        log_error "Git nao encontrado. Instalando..."
        pkg update -y
        pkg install -y git
    fi
    log_ok "Git: $(git --version)"

    # pip
    if ! command -v pip &> /dev/null; then
        log_error "pip nao encontrado. Instalando..."
        python -m ensurepip --upgrade
    fi
    log_ok "pip disponivel"

    # termux-services
    if ! command -v sv &> /dev/null; then
        log_warn "termux-services nao encontrado. Instalando..."
        pkg update -y
        pkg install -y termux-services
        log_warn "Reinicie o Termux apos a instalacao e execute novamente."
        exit 0
    fi
    log_ok "termux-services disponivel"
}

# ============================================================
# 2. Criar estrutura de diretorios
# ============================================================
create_dirs() {
    log_info "Criando estrutura de diretorios..."

    mkdir -p "$CLL1_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$DB_DIR"
    mkdir -p "$LOGS_DIR"
    mkdir -p "$DATA_DIR/memory"
    mkdir -p "$DATA_DIR/backups"

    log_ok "Diretorios criados em $CLL1_DIR"
}

# ============================================================
# 3. Clonar ou atualizar repositorio
# ============================================================
setup_repo() {
    log_info "Configurando repositorio..."

    if [ -d "$ARIS_DIR/.git" ]; then
        log_info "Repositorio existente — atualizando..."
        cd "$ARIS_DIR"
        git pull --quiet 2>/dev/null || log_warn "Falha ao atualizar (usando versao local)"
    else
        log_info "Clonando repositorio..."
        git clone https://github.com/seu-usuario/aris.git "$ARIS_DIR" 2>/dev/null || {
            log_warn "Falha ao clonar — copie o codigo manualmente para $ARIS_DIR"
            mkdir -p "$ARIS_DIR"
        }
    fi

    log_ok "Repositorio configurado em $ARIS_DIR"
}

# ============================================================
# 4. Instalar dependencias Python
# ============================================================
install_deps() {
    log_info "Instalando dependencias Python..."

    if [ -f "$ARIS_DIR/requirements.txt" ]; then
        pip install -r "$ARIS_DIR/requirements.txt" --quiet 2>/dev/null || {
            log_warn "Algas dependencias falharam — continuando..."
        }
    fi

    # Dependencias especificas do CLL1
    pip install discord.py openai --quiet 2>/dev/null || {
        log_warn "Falha ao instalar dependencias do CLL1"
    }

    log_ok "Dependencias instaladas"
}

# ============================================================
# 5. Configurar .env
# ============================================================
setup_env() {
    log_info "Configurando variaveis de ambiente..."

    ENV_FILE="$CLL1_DIR/.env"

    if [ -f "$ENV_FILE" ]; then
        log_warn ".env existente — mantendo configuracao"
        log_warn "Edite manualmente: $ENV_FILE"
        return
    fi

    cat > "$ENV_FILE" << 'EOF'
# ============================================================
# A.R.I.S. CLL1 — Variaveis de Ambiente
# ============================================================
# Copie este arquivo para .env e preencha os valores.

# ── Token de autenticacao CLL1 ──────────────────────────────
# Gerado aleatoriamente — mesmo valor no PC e no CLL1
CLL1_TOKEN=

# ── Endereco do PC principal ────────────────────────────────
CLL1_HOST=192.168.0.104
CLL1_PORT=8765

# ── Groq Edge (LLM local quando PC offline) ─────────────────
EDGE_GROQ_API_KEY=
EDGE_MODEL=openai/gpt-oss-120b
EDGE_RATE_LIMIT=100

# ── Discord Bot (DM) ────────────────────────────────────────
DISCORD_BOT_TOKEN=
DISCORD_ALLOWED_USERS=

# ── Configuracoes gerais ────────────────────────────────────
ARIS_LOG_LEVEL=INFO
EDGE_SYNC_ENABLED=true
EOF

    chmod 600 "$ENV_FILE"

    log_ok "Arquivo .env criado em $ENV_FILE"
    log_warn "IMPORTANTE: Edite o .env com seus tokens!"
}

# ============================================================
# 6. Inicializar banco de dados
# ============================================================
init_db() {
    log_info "Inicializando banco de dados..."

    python -c "
import sqlite3, os
db_path = os.path.expanduser('~/cll1/data/database/aris_memory.db')
os.makedirs(os.path.dirname(db_path), exist_ok=True)
conn = sqlite3.connect(db_path)
conn.execute('''CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, content TEXT NOT NULL, category TEXT DEFAULT 'general',
    importance INTEGER DEFAULT 5, created_at TEXT NOT NULL, synced_to_pc INTEGER DEFAULT 0
)''')
conn.execute('''CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, table_name TEXT NOT NULL,
    row_id TEXT NOT NULL, operation TEXT NOT NULL, data TEXT,
    created_at TEXT NOT NULL, synced_to_pc INTEGER DEFAULT 0, synced_at TEXT
)''')
conn.commit()
conn.close()
print('Banco inicializado:', db_path)
" 2>/dev/null && log_ok "Banco de dados inicializado" || log_warn "Falha ao inicializar banco"
}

# ============================================================
# 7. Configurar servicos Termux
# ============================================================
setup_services() {
    log_info "Configurando servicos Termux..."

    # Servico: cll1-main (orquestrador completo)
    SERVICE_DIR="$SERVICES_DIR/cll1-main"
    mkdir -p "$SERVICE_DIR"

    cat > "$SERVICE_DIR/run" << RUNEOF
#!/data/data/com.termux/files/bin/sh
cd "$ARIS_DIR" || exit 1
export PYTHONPATH="$ARIS_DIR"
exec python -m cll1.main
RUNEOF
    chmod 700 "$SERVICE_DIR/run"

    # Symlink para log
    mkdir -p "$SERVICE_DIR/log"
    ln -sf "$LOGS_DIR/cll1-main.log" "$SERVICE_DIR/log/stdout" 2>/dev/null || true

    log_ok "Servico cll1-main configurado"
}

# ============================================================
# 8. Configurar .gitignore
# ============================================================
setup_gitignore() {
    log_info "Configurando .gitignore..."

    GITIGNORE="$ARIS_DIR/.gitignore"

    if [ -f "$GITIGNORE" ]; then
        # Adicionar entradas do CLL1 se nao existirem
        grep -q "cll1/.env" "$GITIGNORE" 2>/dev/null || {
            echo "" >> "$GITIGNORE"
            echo "# CLL1 local state" >> "$GITIGNORE"
            echo "cll1/.env" >> "$GITIGNORE"
            echo "cll1/data/" >> "$GITIGNORE"
            echo "cll1/logs/" >> "$GITIGNORE"
        }
    fi

    log_ok ".gitignore configurado"
}

# ============================================================
# 9. Habilitar servicos
# ============================================================
enable_services() {
    log_info "Habilitando servicos..."

    if command -v sv-enable &> /dev/null; then
        sv-enable cll1-main 2>/dev/null && log_ok "Servico cll1-main habilitado" || log_warn "Falha ao habilitar cll1-main"
    else
        log_warn "sv-enable nao encontrado — servico configurado mas nao habilitado"
        log_warn "Execute manualmente: sv-enable cll1-main"
    fi
}

# ============================================================
# 10. Verificar status
# ============================================================
check_status() {
    log_info "Verificando status..."

    echo ""
    echo "=========================================="
    echo "  A.R.I.S. CLL1 — Status"
    echo "=========================================="
    echo ""

    # Diretorios
    echo "Diretorios:"
    echo "  CLL1:     $CLL1_DIR"
    echo "  ARIS:     $ARIS_DIR"
    echo "  Dados:    $DATA_DIR"
    echo "  Logs:     $LOGS_DIR"
    echo ""

    # .env
    if [ -f "$CLL1_DIR/.env" ]; then
        echo "ENV:       Configurado"
    else
        echo "ENV:       NAO CONFIGURADO"
    fi

    # Banco
    if [ -f "$DB_DIR/aris_memory.db" ]; then
        echo "Banco:     OK"
    else
        echo "Banco:     NAO INICIALIZADO"
    fi

    # Servico
    if command -v sv &> /dev/null; then
        STATUS=$(sv status cll1-main 2>/dev/null || echo "parado")
        echo "Servico:   $STATUS"
    else
        echo "Servico:   termux-services indisponivel"
    fi

    echo ""
    echo "=========================================="
    echo ""
}

# ============================================================
# Funcao principal
# ============================================================
main() {
    echo ""
    echo "=========================================="
    echo "  A.R.I.S. CLL1 — Setup"
    echo "=========================================="
    echo ""

    check_prereqs
    create_dirs
    setup_repo
    install_deps
    setup_env
    init_db
    setup_services
    setup_gitignore
    enable_services
    check_status

    echo ""
    log_ok "Setup concluido!"
    echo ""
    log_warn "Proximos passos:"
    log_warn "  1. Edite $CLL1_DIR/.env com seus tokens"
    log_warn "  2. Reinicie o Termux"
    log_warn "  3. Verifique: sv status cll1-main"
    echo ""
}

main "$@"

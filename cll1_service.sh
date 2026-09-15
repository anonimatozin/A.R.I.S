#!/data/data/com.termux/files/usr/bin/sh
# ============================================================
# A.R.I.S. CLL1 — Gerenciador de Servicos
# ============================================================
# Comandos para gerenciar os servicos do CLL1.
#
# Uso:
#   ./cll1_service.sh status
#   ./cll1_service.sh start
#   ./cll1_service.sh stop
#   ./cll1_service.sh restart
#   ./cll1_service.sh logs
#   ./cll1_service.sh health
# ============================================================

SERVICE_NAME="cll1-main"
ARIS_DIR="${ARIS_DIR:-$HOME/aris}"
CLL1_DIR="${CLL1_DIR:-$HOME/cll1}"
LOGS_DIR="$CLL1_DIR/logs"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

case "$1" in
    start)
        echo -e "${BLUE}Iniciando $SERVICE_NAME...${NC}"
        sv start "$SERVICE_NAME" 2>/dev/null || {
            echo -e "${YELLOW}Tentando sv-start...${NC}"
            sv-start "$SERVICE_NAME" 2>/dev/null || {
                echo -e "${YELLOW}Iniciando manualmente...${NC}"
                cd "$ARIS_DIR" || exit 1
                export PYTHONPATH="$ARIS_DIR"
                nohup python -m cll1.main > "$LOGS_DIR/cll1-main.log" 2>&1 &
                echo $! > "$CLL1_DIR/cll1-main.pid"
                echo -e "${GREEN}CLL1 iniciado em background (PID: $!)${NC}"
            }
        }
        echo -e "${GREEN}Servico iniciado${NC}"
        ;;

    stop)
        echo -e "${BLUE}Parando $SERVICE_NAME...${NC}"
        sv stop "$SERVICE_NAME" 2>/dev/null || {
            if [ -f "$CLL1_DIR/cll1-main.pid" ]; then
                PID=$(cat "$CLL1_DIR/cll1-main.pid")
                kill "$PID" 2>/dev/null
                rm -f "$CLL1_DIR/cll1-main.pid"
                echo -e "${GREEN}Processo $PID encerrado${NC}"
            else
                pkill -f "cll1.main" 2>/dev/null && echo -e "${GREEN}Processos encerrados${NC}" || echo -e "${YELLOW}Nenhum processo encontrado${NC}"
            fi
        }
        ;;

    restart)
        echo -e "${BLUE}Reiniciando $SERVICE_NAME...${NC}"
        "$0" stop
        sleep 2
        "$0" start
        ;;

    status)
        echo ""
        echo -e "${BLUE}=========================================="
        echo "  A.R.I.S. CLL1 — Status"
        echo -e "==========================================${NC}"
        echo ""

        # Status do servico
        if command -v sv &> /dev/null; then
            STATUS=$(sv status "$SERVICE_NAME" 2>/dev/null || echo "parado")
            echo -e "Servico:  $STATUS"
        else
            # Verificar processo
            if [ -f "$CLL1_DIR/cll1-main.pid" ]; then
                PID=$(cat "$CLL1_DIR/cll1-main.pid")
                if kill -0 "$PID" 2>/dev/null; then
                    echo -e "Servico:  ${GREEN}rodando${NC} (PID: $PID)"
                else
                    echo -e "Servico:  ${RED}parado${NC}"
                fi
            else
                echo -e "Servico:  ${YELLOW}desconhecido${NC}"
            fi
        fi

        # Verificar .env
        if [ -f "$CLL1_DIR/.env" ]; then
            echo -e "ENV:      ${GREEN}configurado${NC}"
        else
            echo -e "ENV:      ${RED}NAO CONFIGURADO${NC}"
        fi

        # Verificar banco
        if [ -f "$CLL1_DIR/data/database/aris_memory.db" ]; then
            echo -e "Banco:    ${GREEN}OK${NC}"
        else
            echo -e "Banco:    ${RED}NAO INICIALIZADO${NC}"
        fi

        # Verificar logs
        LOG_FILE="$LOGS_DIR/cll1-main.log"
        if [ -f "$LOG_FILE" ]; then
            LINES=$(wc -l < "$LOG_FILE")
            echo -e "Logs:     ${GREEN}$LINES linhas${NC}"
        else
            echo -e "Logs:     ${YELLOW}nenhum${NC}"
        fi

        echo ""
        ;;

    logs)
        LOG_FILE="$LOGS_DIR/cll1-main.log"
        if [ -f "$LOG_FILE" ]; then
            echo -e "${BLUE}Ultimas 50 linhas de log:${NC}"
            tail -50 "$LOG_FILE"
        else
            echo -e "${YELLOW}Nenhum log encontrado${NC}"
        fi
        ;;

    health)
        echo -e "${BLUE}Verificando saude do CLL1...${NC}"
        echo ""

        # Testar gateway
        echo -n "Gateway (porta 8765): "
        if command -v nc &> /dev/null; then
            echo "quit" | nc -w 2 localhost 8765 > /dev/null 2>&1 && echo -e "${GREEN}OK${NC}" || echo -e "${RED}INDISPONIVEL${NC}"
        else
            echo -e "${YELLOW}nc nao disponivel${NC}"
        fi

        # Testar conexao com PC
        if [ -f "$CLL1_DIR/.env" ]; then
            PC_HOST=$(grep "CLL1_HOST" "$CLL1_DIR/.env" | cut -d= -f2)
            PC_PORT=$(grep "CLL1_PORT" "$CLL1_DIR/.env" | cut -d= -f2)
            if [ -n "$PC_HOST" ] && [ -n "$PC_PORT" ]; then
                echo -n "PC ($PC_HOST:$PC_PORT): "
                echo "quit" | nc -w 2 "$PC_HOST" "$PC_PORT" > /dev/null 2>&1 && echo -e "${GREEN}ONLINE${NC}" || echo -e "${RED}OFFLINE${NC}"
            fi
        fi

        # Verificar Discord
        echo -n "Discord Bot: "
        if grep -q "DISCORD_BOT_TOKEN=.\\+" "$CLL1_DIR/.env" 2>/dev/null; then
            echo -e "${GREEN}configurado${NC}"
        else
            echo -e "${YELLOW}nao configurado${NC}"
        fi

        echo ""
        ;;

    *)
        echo "Uso: $0 {start|stop|restart|status|logs|health}"
        echo ""
        echo "Comandos:"
        echo "  start    Inicia o servico CLL1"
        echo "  stop     Para o servico CLL1"
        echo "  restart  Reinicia o servico CLL1"
        echo "  status   Mostra status detalhado"
        echo "  logs     Mostra ultimas linhas de log"
        echo "  health   Verifica saude dos componentes"
        exit 1
        ;;
esac

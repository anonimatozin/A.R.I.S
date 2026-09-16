# A.R.I.S. CLL1 — Setup e Configuracao

Guia completo para configurar o CLL1 (instancia edge) no Termux/Android.

## Arquitetura

```
                INTERNET
                   |
                Discord
                   |
             +-----------+
             |    CLL1   |
             |           |
             | Discord   |
             | Edge      |
             | Memory    |
             | Gateway   |
             +-----+-----+
                   |
          +--------+--------+
          |                 |
      PC online         PC offline
          |                 |
    A.R.I.S. Main      A.R.I.S. Edge
          |                 |
         Groq              Groq
```

## Pre-requisitos

- Android com Termux instalado
- Acesso a internet
- Token de autenticacao (mesmo no PC e no CLL1)
- Chave Groq API (para modo edge)
- Token Discord Bot (para conversa via DM)

## Instalacao Automatica

```bash
# Baixar o script
curl -O https://raw.githubusercontent.com/seu-usuario/aris/main/setup_cll1.sh

# Dar permissao e executar
chmod +x setup_cll1.sh
./setup_cll1.sh
```

## Instalacao Manual

### 1. Instalar Termux

Baixe o Termux no F-Droid (NAO use o Play Store — esta desatualizado).

### 2. Instalar pacotes

```bash
pkg update -y
pkg install -y python git termux-services
```

### 3. Clonar repositorio

```bash
git clone https://github.com/seu-usuario/aris.git ~/aris
cd ~/aris
pip install -r requirements.txt
pip install discord.py openai
```

### 4. Criar diretorios

```bash
mkdir -p ~/cll1/data/database
mkdir -p ~/cll1/data/memory
mkdir -p ~/cll1/logs
```

### 5. Configurar .env

```bash
cp ~/aris/.env.example ~/cll1/.env
chmod 600 ~/cll1/.env
nano ~/cll1/.env
```

Preencha:

```env
# Token de autenticacao (gere um aleatorio)
CLL1_TOKEN=seu_token_aqui

# Endereco do PC
CLL1_HOST=192.168.0.106
CLL1_PORT=8765

# Groq Edge
EDGE_GROQ_API_KEY=sua_chave_groq
EDGE_MODEL=openai/gpt-oss-120b
EDGE_RATE_LIMIT=100

# Discord
DISCORD_BOT_TOKEN=token_do_bot
DISCORD_ALLOWED_USERS=seu_user_id
```

### 6. Configurar servico

```bash
mkdir -p $PREFIX/var/service/cll1-main

cat > $PREFIX/var/service/cll1-main/run << 'EOF'
#!/data/data/com.termux/files/usr/bin/sh
cd "$HOME/aris" || exit 1
export PYTHONPATH="$HOME/aris"
exec python -m cll1.main
EOF

chmod 700 $PREFIX/var/service/cll1-main/run
```

### 7. Habilitar servico

```bash
sv-enable cll1-main
```

### 8. Reiniciar Termux

Feche e abra o Termux novamente.

### 9. Verificar

```bash
sv status cll1-main
```

## Comandos de Administracao

### Gerenciador de servicos

```bash
# Copiar o gerenciador
cp ~/aris/cll1_service.sh ~/
chmod +x ~/cll1_service.sh

# Usar
./cll1_service.sh start     # Iniciar
./cll1_service.sh stop      # Parar
./cll1_service.sh restart   # Reiniciar
./cll1_service.sh status    # Ver status
./cll1_service.sh logs      # Ver logs
./cll1_service.sh health    # Verificar saude
```

### Comandos diretos

```bash
# Status do servico
sv status cll1-main

# Iniciar
sv start cll1-main

# Parar
sv stop cll1-main

# Reiniciar
sv restart cll1-main

# Ver logs
tail -f ~/cll1/logs/cll1-main.log
```

## Variaveis de Ambiente

| Variavel | Obrigatorio | Descricao |
|----------|-------------|-----------|
| `CLL1_TOKEN` | Sim | Token de autenticacao (mesmo no PC) |
| `CLL1_HOST` | Sim | IP do PC na rede local |
| `CLL1_PORT` | Sim | Porta do gateway (padrao: 8765) |
| `EDGE_GROQ_API_KEY` | Sim | Chave Groq para modo edge |
| `EDGE_MODEL` | Nao | Modelo Groq (padrao: openai/gpt-oss-120b) |
| `EDGE_RATE_LIMIT` | Nao | Limite de requisicoes/min (padrao: 100) |
| `DISCORD_BOT_TOKEN` | Sim | Token do bot Discord |
| `DISCORD_ALLOWED_USERS` | Sim | User IDs autorizados (separados por virgula) |
| `ARIS_LOG_LEVEL` | Nao | Nivel de log (padrao: INFO) |
| `EDGE_SYNC_ENABLED` | Nao | Sincronizacao habilitada (padrao: true) |

## Configuracao do Discord

### 1. Criar bot

1. Acesse https://discord.com/developers/applications
2. Clique em "New Application"
3. De um nome (ex: "A.R.I.S.")
4. Va em "Bot" -> "Add Bot"
5. Copie o token

### 2. Configurar intents

1. Em "Bot", habilite:
   - MESSAGE CONTENT INTENT
   - DM_MESSAGES

### 3. Convidar bot

1. Va em "OAuth2" -> "URL Generator"
2. Selecione scopes: `bot`
3. Selecione permissions: `Send Messages`, `Read Messages`
4. Use a URL gerada para convidar

### 4. Pegar seu User ID

1. No Discord, va em Configuracoes -> Avancado
2. Habilite "Modo Desenvolvedor"
3. Clique com botao direito no seu nome
4. "Copiar ID do Usuario"

### 5. Configurar .env

```env
DISCORD_BOT_TOKEN=seu_token_aqui
DISCORD_ALLOWED_USERS=seu_user_id_aqui
```

## Como Testar

### PC ligado

1. Abra Discord
2. Va no PV do bot
3. Envie: "oi aris"
4. Resposta deve vir do PC (A.R.I.S. principal)

### PC desligado

1. Desligue o PC
2. Abra Discord
3. Va no PV do bot
4. Envie: "oi aris"
5. Resposta deve vir do CLL1 (A.R.I.S. edge)

### Verificar instancia

Pergunte ao bot: "de qual instancia voce esta respondendo?"
- PC: "Instancia principal (PC)"
- CLL1: "Instancia edge (CLL1)"

## Diagnostico

### Ver logs

```bash
tail -100 ~/cll1/logs/cll1-main.log
```

### Verificar gateway

```bash
# Testar conexao local
echo "quit" | nc localhost 8765

# Verificar se esta ouvindo
ss -tlnp | grep 8765
```

### Verificar Discord

```bash
# Verificar se o bot esta conectado
grep "Discord bot conectado" ~/cll1/logs/cll1-main.log
```

### Verificar roteador

```bash
# Ver status do PC
grep "Roteador" ~/cll1/logs/cll1-main.log
```

## Recuperacao

### Servico nao inicia

```bash
# Ver erro
sv status cll1-main

# Tentar iniciar manualmente
cd ~/aris
export PYTHONPATH="$HOME/aris"
python -m cll1.main
```

### Token invalido

1. Verifique o .env
2. Gere novo token: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
3. Atualize no PC e no CLL1
4. Reinicie: `sv restart cll1-main`

### Sem conexao com PC

1. Verifique se o PC esta ligado
2. Verifique o IP: `ping 192.168.0.106`
3. Verifique a porta: `nc -zv 192.168.0.106 8765`
4. Verifique o firewall do PC

### Bot Discord nao responde

1. Verifique o token
2. Verifique os intents no Developer Portal
3. Verifique os user IDs autorizados
4. Veja os logs: `tail -f ~/cll1/logs/cll1-main.log`

## Backup

### Banco de dados

```bash
cp ~/cll1/data/database/aris_memory.db ~/cll1/data/backups/aris_memory_$(date +%Y%m%d).db
```

### Configuracao

```bash
tar -czf ~/cll1_backup_$(date +%Y%m%d).tar.gz ~/cll1/.env ~/cll1/data/
```

## Atualizacao

```bash
cd ~/aris
git pull
pip install -r requirements.txt
sv restart cll1-main
```

## Seguranca

- `.env` deve ter permissao `600`
- Nunca commite tokens no Git
- Use tokens diferentes para PC e edge (se possivel)
- O gateway so aceita conexoes autenticadas
- Operacoes de arquivo estao sandboxed em `~/cll1/`
- Logs nao contem tokens

## Limitacoes do Modo Edge

Quando o PC esta offline, o CLL1 **nao** pode:

- Automacao de desktop
- Visao computacional
- Hardware (ESP32)
- Ferramentas pesadas
- Gmail
- Navegador

O CLL1 **pode**:

- Conversar (via Groq)
- Memoria local
- Sincronizar quando PC voltar

## Suporte

Se encontrar problemas:

1. Verifique os logs
2. Execute `./cll1_service.sh health`
3. Verifique se todas as variaveis estao configuradas
4. Reinicie o servico
5. Se persistir, abra uma issue no GitHub

# Discord Bot + Edge — Setup Completo

> **Guia passo a passo** para configurar o bot Discord, a conexao edge (Groq),
> e como acessar o CLL1 fora da rede local.

---

## 1. Variaveis de Ambiente — Lista Completa

### CLL1 (Termux/Android) — `~/cll1/.env`

```env
# === AUTENTICACAO ===
# Token compartilhado PC <-> CLL1 (gere com: python -c "import secrets; print(secrets.token_urlsafe(32))")
CLL1_TOKEN=HAaAjq199iDMQSeAB_4qcvnhwFv-nRkZ4_KZcgNd1wI

# === DISCORD ===
# Token do bot Discord (copiar do Developer Portal)
DISCORD_BOT_TOKEN=MTI3NjA5... seu_token_aqui

# User IDs autorizados a conversar (separados por virgula)
# Para pegar: Discord > Configuracoes > Avancado > Modo Desenvolvedor > Clique direito > Copiar ID
DISCORD_ALLOWED_USERS=123456789012345678

# === GROQ (MODO EDGE) ===
# Chave API Groq separada (NUNCA use a chave master do PC aqui)
# Criar em: https://console.groq.com/keys
EDGE_GROQ_API_KEY=gsk_seu_token_aqui

# Modelo Groq (default: openai/gpt-oss-120b)
EDGE_MODEL=openai/gpt-oss-120b

# Rate limit de requisicoes por minuto (default: 100)
EDGE_RATE_LIMIT=100

# === OPCIONAIS ===
# Nivel de log (default: INFO)
#ARIS_LOG_LEVEL=INFO

# Sincronizacao habilitada (default: true)
#EDGE_SYNC_ENABLED=true
```

### PC (Windows) — `D:\ARIS\.env`

```env
# === AUTENTICACAO ===
# Mesmo token do CLL1
CLL1_TOKEN=HAaAjq199iDMQSeAB_4qcvnhwFv-nRkZ4_KZcgNd1wI

# === DISCORD ===
# Mesmo token do bot (ou bot separado para PC)
DISCORD_BOT_TOKEN=MTI3NjA5... seu_token_aqui

# Mesmos user IDs autorizados
DISCORD_ALLOWED_USERS=123456789012345678

# === GROQ (INSTANCIA PRINCIPAL) ===
# Chave Groq master (pode ser diferente da edge)
GROQ_API_KEY=gsk_chave_master_aqui
```

**Regra de ouro:** O `CLL1_TOKEN` deve ser IDENTICO em ambos os dispositivos.

---

## 2. Criar Bot no Discord — Passo a Passo

### 2.1 Criar Aplicacao

1. Acesse https://discord.com/developers/applications
2. Clique em **"New Application"** (canto superior direito)
3. De um nome: **"A.R.I.S."** (ou o que preferir)
4. Clique em **"Create"**

### 2.2 Configurar Bot

1. No menu lateral, clique em **"Bot"**
2. Clique em **"Add Bot"** > **"Yes, do it!"**
3. Em **"Token"**, clique **"Copy"** — este e o `DISCORD_BOT_TOKEN`

### 2.3 Configurar Intents (OBRIGATORIO)

Na pagina do Bot, em **"Privileged Gateway Intents"**:

| Intent | Status | Obrigatorio? |
|--------|--------|-------------|
| PRESENCE INTENT | Desligado | Nao |
| SERVER MEMBERS INTENT | Desligado | Nao |
| MESSAGE CONTENT INTENT | **LIGADO** | Sim |

Em seguida, role para baixo e clique em **"Save Changes"**.

> **SEM o MESSAGE CONTENT INTENT, o bot NAO recebe o texto das mensagens.**

### 2.4 Configurar Intents no Codigo

No `modules/discord_bot.py`, os intents estao configurados assim:

```python
intents = discord.Intents.default()
intents.message_content = True  # OBRIGATORIO
intents.dm_messages = True      # Para receber DMs
```

### 2.5 Convidar o Bot

1. No menu lateral, clique em **"OAuth2"**
2. Va em **"URL Generator"**
3. Em **"Scopes"**, marque: `bot`
4. Em **"Bot Permissions"**, marque:
   - `Send Messages`
   - `Read Message History`
   - `Read Messages/View Channels`
5. Copie a URL gerada em **"Generated URL"**
6. Cole no navegador e selecione seu servidor

### 2.6 Pegar Seu User ID

1. Abra o Discord
2. Va em **Configuracoes** (engrenagem, canto inferior esquerdo)
3. Va em **Avancado**
4. Habilite **"Modo Desenvolvedor"**
5. Volte ao Discord
6. Clique com o botao direito no **seu nome** (ou em qualquer mensagem sua)
7. Clique em **"Copiar ID do Usuario"**
8. Use este ID em `DISCORD_ALLOWED_USERS`

### 2.7 Testar o Bot

1. Abra o Discord
2. Va no **PV (DM) do bot** (clique no avatar do bot > "Enviar Mensagem")
3. Envie qualquer mensagem
4. Se tudo estiver configurado, o bot deve responder

---

## 3. Configurar Groq (Edge)

### 3.1 Criar Conta no Groq

1. Acesse https://console.groq.com
2. Faca login (Google/GitHub)
3. Va em **"API Keys"**
4. Clique em **"Create API Key"**
5. De um nome: `ARIS-EDGE`
6. Copie a chave (so aparece uma vez!)

### 3.2 Configurar Billing

1. No Groq Console, va em **"Billing"**
2. Adicione um metodo de pagamento
3. Configure **billing alert** (recomendado: $5/mes)

### 3.3 Configurar Rate Limit

No `.env` do CLL1:

```env
EDGE_GROQ_API_KEY=gsk_sua_chave_aqui
EDGE_MODEL=openai/gpt-oss-120b
EDGE_RATE_LIMIT=100
```

### 3.4 Testar a Conexao

```bash
# No Termux
cd ~/cll1
python -c "
from edge.edge_chat import EdgeChat
from edge.edge_config import EdgeConfig
config = EdgeConfig.from_env()
chat = EdgeChat(config)
print('Disponivel:', chat.available)
print('Resposta:', chat.respond('Oi, tudo bem?'))
"
```

---

## 4. Como Funciona o Roteamento Discord

```
┌─────────────────────────────────────────────────────────┐
│                   MENSAGEM DO USUARIO                    │
│                        Discord DM                        │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│               modules/discord_bot.py                     │
│  - Recebe DM (nao responde canais)                       │
│  - Verifica DISCORD_ALLOWED_USERS                        │
│  - Envia para callback _on_message                       │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│               cll1/main.py (roteador)                    │
│  - Tenta conectar ao PC via TCP :8765                    │
│  - PC online? -> Envia para PC                           │
│  - PC offline? -> USA EDGE (edge_chat.py)                │
└──────────┬──────────────────────┬───────────────────────┘
           │                      │
     PC ONLINE               PC OFFLINE
           │                      │
           ▼                      ▼
┌──────────────────┐  ┌──────────────────────────────┐
│  A.R.I.S. Main   │  │     edge_chat.py (Groq)      │
│  (NeuralCore)    │  │  - Chave separada             │
│  - Completo      │  │  - Personalidade sincronizada │
│  - Visao, etc    │  │  - Memoria local              │
└──────────────────┘  └──────────────────────────────┘
```

---

## 5. Acessar CLL1 Fora da Rede Local

### 5.1 O que Precisa

Para acessar o CLL1 de fora da rede local (4G, outro WiFi, etc), voce precisa de uma das opcoes:

### Opcao A: TUNNEL via SSH (Recomendado)

Se voce tem um servidor VPS/Cloud:

```bash
# No PC (onde esta o A.R.I.S.):
# Criar tunnel reverso para o VPS
ssh -R 8765:localhost:8765 -R 8766:localhost:8766 usuario@seu-vps.com

# Agora, de qualquer lugar:
ssh -L 8765:localhost:8765 -L 8766:localhost:8766 usuario@seu-vps.com
# Acesse http://localhost:8766
```

### Opcao B: NGROK (mais simples)

```bash
# Instalar ngrok
# Windows: choco install ngrok
# Linux: snap install ngrok

# Expor porta 8766
ngrok http 8766

# Ngrok vai gerar uma URL como:
# https://abc123.ngrok-free.app
# Acesse de qualquer lugar
```

### Opcao C: FRP (Free Reverse Proxy)

```bash
# No servidor:
# frps.ini
[common]
bind_port = 7000

# No PC/CLL1:
# frpc.ini
[common]
server_addr = seu-vps.com
server_port = 7000

[aris-http]
type = http
local_port = 8766
custom_domains = aris.seu-vps.com
```

### Opcao D: Tailscale (VPN mesh)

```bash
# Instalar Tailscale no PC e no CLL1
# Ambos ficam na mesma rede virtual
# Acesse pelo IP do Tailscale do CLL1
```

### 5.2 Seguranca ao Acessar de Fora

| Criterio | Status | Descricao |
|----------|--------|-----------|
| HTTPS | Configurar | Usar nginx/caddy com certificado Let's Encrypt |
| Token | Obrigatorio | Nao desabilite a autenticacao |
| Firewall | Configurar | So liberar portas 8765/8766 para IPs conhecidos |
| Rate Limit | Configurar | nginx: `limit_req_zone` |
| GeoIP | Opcional | Bloquear paises nao autorizados |

### 5.3 Configurar nginx (exemplo)

```nginx
server {
    listen 443 ssl;
    server_name aris.seu-dominio.com;

    ssl_certificate /etc/letsencrypt/live/aris.seu-dominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/aris.seu-dominio.com/privkey.pem;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=aris:10m rate=10r/s;

    location / {
        limit_req zone=aris burst=20 nodelay;
        proxy_pass http://127.0.0.1:8766;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 6. Testar Tudo (Checklist)

### 6.1 CLL1 Local

```bash
# Verificar servico
sv status cll1-main

# Testar ping TCP
python cll1_control.py ping

# Testar HTTP
curl http://192.168.0.106:8766/api/ping

# Testar health
curl -H "Authorization: Bearer $CLL1_TOKEN" http://192.168.0.106:8766/api/health

# Ver logs
tail -f ~/cll1/logs/cll1-main.log
```

### 6.2 Discord

```bash
# No Termux, verificar conexao Discord
grep "Discord bot conectado" ~/cll1/logs/cll1-main.log
```

1. Abra Discord
2. Va no PV do bot
3. Envie: "oi aris"
4. Resposta deve vir (PC ou edge, dependendo do estado)

### 6.3 Modo Edge

1. Desligue o PC
2. Abra Discord
3. Va no PV do bot
4. Envie: "oi aris"
5. Resposta deve vir do CLL1 (via Groq)
6. Envie: "de qual instancia voce esta respondendo?"
7. Resposta deve indicar "edge" ou "CLL1"

### 6.4 Fora da Rede Local

1. Configure uma das opcoes de tunnel (5.1)
2. Acesse `https://aris.seu-dominio.com/` de fora
3. Teste o dashboard
4. Teste via Discord (de qualquer lugar)

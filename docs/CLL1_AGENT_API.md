# CLL1 Gateway — Agent API Reference

> **Versao:** 2.0 (Fase 9)
>
> **Endpoints:** HTTP `http://<cll1_ip>:8766` + TCP `:8765`
>
> **Autenticacao:** Bearer token via header `Authorization: Bearer <CLL1_TOKEN>`

---

## 1. Autenticacao

Todos os endpoints (exceto `/api/ping` e `/api/health`) exigem header de autenticacao:

```
Authorization: Bearer HAaAjq199iDMQSeAB_4qcvnhwFv-nRkZ4_KZcgNd1wI
```

Responses sem token ou com token invalido retornam `401`:

```json
{"ok": false, "error": "Unauthorized"}
```

---

## 2. Endpoints GET

### `GET /api/ping`

Health check basico (sem auth).

**Response:**
```json
{"ok": true, "node": "cll-1", "status": "online"}
```

---

### `GET /api/health`

Health checks completos (8 checks).

**Response:**
```json
{
  "timestamp": 1726400000.0,
  "overall": "healthy",
  "checks": {
    "service": {"ok": true, "detail": "run: cll1-main: (pid 12345) 300s"},
    "tcp_port": {"ok": true, "detail": "Port 8765 listening"},
    "http_port": {"ok": true, "detail": "Port 8766 listening"},
    "disk": {"ok": true, "detail": "45.2% used (589MB/1303MB)"},
    "memory": {"ok": true, "detail": "60.1% used (2240MB/3725MB)"},
    "python": {"ok": true, "detail": "Python 3.13.13"},
    "env_file": {"ok": true, "detail": "Found"},
    "log_dir": {"ok": true, "detail": "Found"}
  },
  "failed": []
}
```

**Valores de `overall`:** `healthy` (0 falhas), `degraded` (1-2 falhas), `unhealthy` (3+ falhas).

---

### `GET /api/status`

Status do servico sv.

**Response:**
```json
{"ok": true, "service": "cll1-main", "output": "run: cll1-main: (pid 12345) 300s"}
```

---

### `GET /api/metrics`

Metricas do sistema (CPU, memoria, disco, uptime, processos).

**Response:**
```json
{
  "ok": true,
  "metrics": {
    "timestamp": 1726400000.0,
    "uptime": "4h 30m",
    "cpu": {"idle": 50000, "total": 100000, "percent": 50.0},
    "memory": {"total_mb": 3725, "used_mb": 2240, "percent": 60.1},
    "disk": {"total_mb": 1303, "used_mb": 1303, "percent": 100.0},
    "processes": 150
  }
}
```

---

### `GET /api/agents`

Lista agents registrados.

**Response:**
```json
{
  "ok": true,
  "agents": [
    {"id": "default", "name": "Default Agent", "type": "local", "status": "active"}
  ]
}
```

---

### `GET /api/files?path=<rel>`

Lista arquivos em um diretorio (relativo ao base_dir).

**Parameters:**
- `path` (query, opcional): Caminho relativo. Default: `.`

**Response:**
```json
{
  "ok": true,
  "path": ".",
  "files": [
    {"name": "cll1", "path": "cll1", "is_dir": true, "size": 0},
    {"name": "edge", "path": "edge", "is_dir": true, "size": 0},
    {"name": ".env", "path": ".env", "is_dir": false, "size": 256}
  ]
}
```

---

### `GET /api/logs?file=<name>&lines=<n>`

Le linhas de um arquivo de log.

**Parameters:**
- `file` (query, opcional): Nome do arquivo. Default: `cll1.log`
- `lines` (query, opcional): Numero de linhas. Default: `50`

**Response:**
```json
{
  "ok": true,
  "path": "/home/user/cll1/logs/cll1.log",
  "lines": ["2026-09-15 10:00:00 [INFO] ...", "..."],
  "total_lines": 167
}
```

---

### `GET /api/audit`

Retorna as ultimas 100 entradas do audit log.

**Response:**
```json
{
  "ok": true,
  "entries": [
    {
      "ts": 1726400000.0,
      "op": "exec",
      "user": "system",
      "target": "ls -la",
      "result": "ok",
      "detail": "...",
      "ms": 15.2
    }
  ]
}
```

---

### `GET /api/backups`

Lista backups disponiveis.

**Response:**
```json
{
  "ok": true,
  "backups": [
    {"name": "backup_1726400000", "path": "...", "size": 90630, "created": 1726400000.0}
  ]
}
```

---

## 3. Endpoints POST

### `POST /api/exec`

Executa comando shell.

**Body:**
```json
{"command": "ls -la", "timeout": 30}
```

**Response:**
```json
{
  "ok": true,
  "stdout": "total 48\ndrwxr-xr-x ...",
  "stderr": "",
  "exit_code": 0,
  "duration_ms": 14.4
}
```

---

### `POST /api/file`

Operacoes CRUD em arquivos.

**Body:**
```json
{"action": "read", "path": "cll1/main.py"}
```

**Actions disponiveis:**

| Action | Campos obrigatorios | Descricao |
|--------|---------------------|-----------|
| `read` | `path` | Le conteudo do arquivo |
| `write` | `path`, `content` | Escreve conteudo |
| `delete` | `path` | Deleta arquivo |
| `move` | `path`, `destination` | Move/renomeia |
| `copy` | `path`, `destination` | Copia |
| `mkdir` | `path` | Cria diretorio |
| `info` | `path` | Metadados (tamanho, datas) |

---

### `POST /api/service`

Controle do servico sv.

**Body:**
```json
{"action": "restart", "service": "cll1-main"}
```

**Actions:** `status`, `restart`, `stop`, `enable`

---

### `POST /api/agent/chat`

Envia mensagem para agent (message routing).

**Body:**
```json
{"message": "status", "agent_id": null}
```

**Message routing:**
- `exec:<command>` — Executa comando
- `read:<path>` — Le arquivo
- `ls:<path>` ou `list:<path>` — Lista diretorio
- `status` ou `health` — Status do servico
- Qualquer outro texto — Retorna `"Received: <texto>"`

**Response:**
```json
{
  "ok": true,
  "type": "exec",
  "result": {"ok": true, "stdout": "HELLO", "exit_code": 0}
}
```

---

### `POST /api/agent/create`

Cria novo agent.

**Body:**
```json
{"name": "Meu Agent", "type": "local", "config": {}}
```

**Response:**
```json
{
  "ok": true,
  "agent": {
    "id": "a1b2c3d4",
    "name": "Meu Agent",
    "type": "local",
    "status": "active",
    "created_at": 1726400000.0
  }
}
```

---

### `POST /api/backup`

Operacoes de backup.

**Body:**
```json
{"action": "create", "name": "meu_backup"}
```

**Actions:**
- `create` — Cria backup (tar.gz de cll1/, edge/, modules/, utils/, gateway/, .env)
- `restore` — Restaura do backup
- `delete` — Deleta backup

---

## 4. Web UI Dashboard

Acessivel em `http://<cll1_ip>:8766/` no navegador.

Funcionalidades:
- Token authentication overlay
- Status cards (Status, PID, Uptime, Audit Count)
- Terminal interativo (executar comandos)
- Controles de servico (restart, stop, enable)
- File browser (navegar diretorios)
- Audit log viewer (ultimas 100 entradas)
- Auto-refresh a cada 10 segundos

---

## 5. TCP Protocol (:8765)

Para comunicacao de baixo nivel (usado pelo `cll1_control.py`):

```
[8 bytes: tamanho do payload][payload JSON]
```

**Request:**
```json
{
  "type": "exec_python",
  "path": "test_exec.py",
  "token": "HAaAjq199iDMQSeAB_4qcvnhwFv-nRkZ4_KZcgNd1wI"
}
```

**Types suportados:** `ping`, `exec_python`, `full_status`, `get_file`, `put_file`

---

## 6. Deploy de Arquivos

Usar `cll1_control.py` do PC:

```bash
# Copiar arquivo para CLL1
python cll1_control.py put <local_path> <remote_path>

# Exemplo
python cll1_control.py put gateway/web.py gateway/web.py

# Status completo
python cll1_control.py fullstatus

# Ping
python cll1_control.py ping
```

---

## 7. Variaveis de Ambiente

| Variavel | Obrigatorio | Descricao |
|----------|-------------|-----------|
| `CLL1_TOKEN` | Sim | Token de autenticacao |
| `DISCORD_BOT_TOKEN` | Sim | Token do bot Discord |
| `DISCORD_ALLOWED_USERS` | Sim | User IDs autorizados (virgula) |
| `EDGE_GROQ_API_KEY` | Sim | Chave Groq para modo edge |
| `EDGE_MODEL` | Nao | Modelo Groq (default: `openai/gpt-oss-120b`) |
| `EDGE_RATE_LIMIT` | Nao | Rate limit req/min (default: `100`) |

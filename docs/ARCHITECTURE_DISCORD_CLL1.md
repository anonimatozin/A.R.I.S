# ARQUITETURA DISTRIBUIDA — A.R.I.S. (PC = Principal, CLL1 = Edge)

> **Status:** Design / Planejamento — Nao implementar ate aprovacao.
>
> **Data:** 2026-09-14 (revisao — substitui design anterior de relay puro)
>
> **Pre-requisito confirmado:** 552 testes coletados, 551 passed, 1 skipped, 0 collection errors.
>
> **Diretriz:** Quando o PC esta desligado, o CLL1 hospeda uma instancia **edge** da A.R.I.S., capaz de conversar de verdade, com identidade e memoria compartilhadas com a instancia principal. Nao e uma segunda IA independente, nem uma simulacao que finge responder.

---

## 1. Modelo Conceitual

```
A.R.I.S. (identidade unica, distribuida)
│
├── Core / identidade compartilhada
│   ├── Personalidade (config/personality.py — sincronizada)
│   ├── Regras de seguranca (SecurityGate — idêntica nas duas)
│   └── Tokens / credenciais (nunca no git)
│
├── Memoria compartilhavel / sincronizavel
│   ├── PC: D:\ARIS_MEMORY\aris_memory.db (fonte primaria)
│   └── CLL1: ~/cll1/data/aris_memory.db (copia edge, sincronizavel)
│
├── Estado distribuido
│   ├── "Quem esta no comando" —PC=principal, CLL1=edge
│   └── Ultima sincronizacao conhecida
│
├── Instancia PRINCIPAL — PC
│   ├── NeuralCore completo (Attention, Workspace, World Model, Planner)
│   ├── Groq principal (chave master)
│   ├── Visao, automacao completa, ferramentas pesadas, sensores
│   └── Qualquer acao que dependa fisicamente do PC
│
└── Instancia EDGE — CLL1 (Termux / Android)
    ├── Conversa basica (LLM proprio, com personalidade compartilhada)
    ├── Memoria remota (leitura/escrita local, sincronizavel com PC)
    ├── Contexto essencial (ultimas interacoes, sabe que esta em modo edge)
    ├── Estado do sistema (sabe dizer se PC esta online/offline)
    ├── Discord (bot)
    ├── Heartbeat
    ├── Acoes seguras limitadas (ver divisao abaixo)
    └── Wake-on-LAN (futuro, com confirmacao explicita)
```

### Tres estados do sistema

```
┌─────────────────────────────────────────────────────────────────────┐
│ ESTADO 1: PC ONLINE (normal)                                       │
│                                                                     │
│   Discord/terminal/voz ──► PC (NeuralCore) ──► resposta             │
│                           CLL1: heartbeats + relay se Discord       │
│                           CLL1: NAO processa IA (PC manda)         │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ ESTADO 2: PC OFFLINE (edge ativo)                                  │
│                                                                     │
│   Discord/terminal/voz ──► CLL1 (edge LLM) ──► resposta            │
│                           CLL1: conversa com personalidade         │
│                           CLL1: le/escrive memoria local            │
│                           CLL1: acoes seguras limitadas             │
│                           CLL1: "nao consigo fazer isso agora,     │
│                                  preciso que o PC esteja ligado"    │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ ESTADO 3: TRANSICAO (PC voltando online)                           │
│                                                                     │
│   CLL1 detecta PC online via heartbeat/ handshake                   │
│   CLL1 envia fila de pendencias ao PC (memorias novas, conversas)  │
│   PC importa, merge por timestamp (sem duplicatas)                  │
│   CLL1 notifica usuario: "O PC ligou, ja posso continuar           │
│                          com a versao completa"                     │
│   Proxima mensagem: PC assume atendimento                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Divisao de Capacidades — PC vs. CLL1

### CLL1 (edge) — o que PODE fazer

| Capacidade | Como | Justificativa |
|---|---|---|
| Conversa basica | LLM proprio (chave separada, ve Secao 3) + personalidade compartilhada | O usuario espera respostas mesmo com PC desligado |
| Memoria: leitura | `MemoryService.retrieve()` no SQLite local | Responder com contexto ("voce disse que ia fazer X ontem") |
| Memoria: escrita | `MemoryService.remember()` no SQLite local | Salvar o que o usuario disse durante a ausencia do PC |
| Contexto essencial | Ultimas 5 interacoes + modo edge + ultima sync | O bastante para conversa coerente |
| Estado do sistema | "PC offline desde HH:MM, ultima sync: HH:MM" | Transparencia para o usuario |
| Discord (bot) | Mesmo bot, mensagens roteadas via CLL1 | Continuidade do canal de comunicacao |
| Heartbeat | `cll1_heartbeat.py` (ja implementado) | Saude do CLL1 visivel ao PC quando voltar |
| Acoes seguras limitadas | Ver tabela abaixo | Coisas que nao dependem do PC fisicamente |
| Wake-on-LAN | Com confirmacao explicita (Secao 6) | Ligar o PC remotamente |

### CLL1 (edge) — o que NAO pode fazer (e deve informar)

| Capacidade | Razao | Resposta padrao |
|---|---|---|
| Visao / OCR / VLM | Requer GPU ou PC com tela | "Preciso do PC para analise de imagem" |
| Automacao de desktop | Requer acesso fisico ao PC | "So consigo fazer isso com o PC ligado" |
| Sensores / hardware | Requer ESP32 + PC | "O hardware so esta disponivel no PC" |
| Ferramentas pesadas | Requer CPU/RAM do PC | "Isso precisa do PC ligado" |
| NeuralCore completo | Requer Attention, Workspace, WorldModel | "No modo edge tenho funcionalidade basica" |
| Scheduler/lembretes | Depende do PC estar ligado para executar | "Posso anotar, mas so executa quando o PC voltar" |

### Acoes seguras permitidas no edge

| Acao | Risk | Justificativa |
|---|---|---|
| `websearch` (pesquisa basica) | 1 (LOW) | Nao depende do PC, resultado informativo |
| `remember` (salvar na memoria) | 1 (LOW) | Escrita local, sincronizavel |
| `sys` (status basico) | 1 (LOW) | CLL1 pode reportar seu proprio estado |
| `notify` (notificacao no celular) | 1 (LOW) | Notificacao local no Android |
| `entertainment` (piadas, curiosidades) | 2 (CAUTION) | Contenido gerado pelo LLM, sem efeito colateral |
| `context` (contexto basico) | 1 (LOW) | Detectar atividade atual no CLL1 |
| `wake_on_lan` (futuro) | 4 (CRITICAL) | Sempre pede confirmacao — unica acao de risco alto no edge |

### Por que essa divisao?

A decisao central e: **o que e razoavel o celular fazer sozinho?**

- Conversa e memoria: sim, e o essencial — o usuario nao quer uma IA muda so porque o PC desligou.
- Automacao/visao: nao, depende de hardware que so o PC tem.
- Acoes de risco alto: minimas, e sempre com confirmacao. O edge e mais restrito que o principal.

---

## 3. Provedor de IA do Modo Edge — Credencial Separada

### Decisao: Groq com chave separada e escopo restrito

| Aspecto | Decisao | Justificativa |
|---|---|---|
| Provedor | Groq (mesmo provedor do PC) | Consistencia de modelo; Groq e rapido e barato |
| Chave | Chave separada (`EDGE_GROQ_API_KEY`) | Nunca usar a chave master do PC no celular |
| Modelo | `openai/gpt-oss-120b` (mesmo do PC) | Manter consistencia de respostas |
| Rate limit | Max 100 requests/dia, 10K tokens/request | Conter impacto se celular for comprometido |
| Escopo | Somente chat completion | Sem acesso a keys de outros servicos |

### Onde a chave fica armazenada no Termux

```
~/cll1/.env
├── CLL1_TOKEN=...          (token de autenticacao PC ↔ CLL1)
├── EDGE_GROQ_API_KEY=...   (chave Groq para modo edge)
├── DISCORD_BOT_TOKEN=...   (token do bot Discord)
└── DISCORD_CHANNEL_ID=...  (canal autorizado)
```

- **Nunca hardcoded** — sempre variavel de ambiente ou arquivo `.env`
- **Nunca no git** — `.gitignore` inclui `*.env`
- **Permissao 600** no Termux: `chmod 600 ~/cll1/.env`
- **Diferente do `.env` do PC** — sao dois arquivos distintos em dois dispositivos

### Como o edge usa a chave

```python
# No CLL1 (edge_chat.py — conceitual)
import os
from openai import OpenAI

EDGE_API_KEY = os.getenv("EDGE_GROQ_API_KEY", "")
client = OpenAI(
    api_key=EDGE_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

def edge_respond(user_message: str, personality: str, memories: list[dict]) -> str:
    messages = [
        {"role": "system", "content": personality},
        # ... memorias relevantes injetadas aqui ...
        {"role": "user", "content": user_message},
    ]
    reply = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=messages,
        temperature=0.7,
        max_tokens=2048,
    )
    return reply.choices[0].message.content
```

### Seguranca da credencial no celular

| Vetor | Risco | Mitigacao |
|---|---|---|
| Celular roubado/perdido | Atacante usa a chave Groq | Rate limit (100 req/dia); chave pode ser revogada remotamente via Groq dashboard |
| Chave vaza do `.env` | Atacante gera custos no Groq | Chave separada com escopo restrito; billing alert configurado no Groq |
| Malware no Android le o `.env` | Atacante obtém chave | Mesmo com chave, so consegue chat completion (sem automacao, sem dados do PC) |
| Replay de chamadas | Atacante reenvia requests | Groq valida por HTTPS; timestamp na requisicao |

**Trade-off aceito:** O risco de a chave Groq do edge vazar e baixo (chat completion de um provedor barato, sem acesso a dados sensiveis). O custo de mitigacao (HSM, key vault no celular) e desproporcional ao risco.

---

## 4. Identidade e Tom Consistentes — Personalidade Compartilhada

### O problema

A "voz" da A.R.I.S. nao pode mudar perceptivelmente dependendo de qual instancia responde. O usuario nao deveria perceber (exceto pela diferenca de capacidade: "nao consigo fazer isso agora").

### Solucao: personalidade como arquivo sincronizavel

O `config/personality.py` atual e um modulo Python com uma string `ARIS_PERSONALITY`. Para o edge, precisamos de uma versao que:

1. Pode ser lida pelo PC (que ja usa `from config.personality import ARIS_PERSONALITY`)
2. Pode ser lida pelo CLL1 (que precisa de uma copia local)
3. E sincronizada automaticamente quando o PC volta online

### Protocolo de sincronizacao da personalidade

```
┌─────────────────────────────────────────────────────────────┐
│ 1. PC e a fonte da verdade (single source of truth)         │
│    config/personality.py no PC e o arquivo original          │
│                                                              │
│ 2. Quando CLL1 conecta ao PC (handshake):                   │
│    PC envia: {"type":"sync","personality_hash":"abc123",...} │
│    CLL1 compara com seu hash local                           │
│    Se diferente: CLL1 requisita: {"type":"sync_request",    │
│      "what":"personality"}                                   │
│    PC envia o conteudo completo de ARIS_PERSONALITY          │
│    CLL1 salva em ~/cll1/data/personality_sync.md             │
│                                                              │
│ 3. Edge carrega personalidade:                               │
│    Se existir personality_sync.md: usa ela                   │
│    Senao: usa fallback embutido (versao basica, ve abaixo)   │
│                                                              │
│ 4. Fallback embutido no edge (para primeiro boot sem PC):    │
│    "Voce e o A.R.I.S. — um assistente pessoal.              │
│     Responda em portugues, seja direto e util.               │
│     Nao comecce com 'Claro!' ou 'Certamente!'."             │
│    Esta versao e intencionalmente basica —                    │
│    a personalidade real so vem do PC.                        │
└─────────────────────────────────────────────────────────────┘
```

### O que o LLM do edge recebe

```python
# edge_chat.py — conceitual
def build_edge_prompt(personality_sync: str, memories: list, mode: str) -> str:
    base = personality_sync or FALLBACK_PERSONALITY
    return f"""{base}

## Modo atual: EDGE (PC offline)
Voce e a instancia remota da A.R.I.S. (CLL1).
Capacidades disponiveis: conversa, memoria, pesquisa basica.
Capacidades indisponiveis (requerem PC): automacao, visao, hardware.

Se o usuario pedir algo que voce nao consegue fazer no modo edge,
explique naturalmente e sugira ligar o PC.

## Memorias relevantes:
{_format_memories(memories)}
"""
```

### Garantia de consistencia

- **Mesmo modelo** (`openai/gpt-oss-120b`) — mesmo comportamento base
- **Mesmo prompt de personalidade** — sincronizado do PC
- **Memoria compartilhavel** — o edge le as memorias do PC (via sync) e as suas proprias
- **Diferenca aceitavel:** O edge pode dizer "preciso do PC para isso" — isso e funcional, nao e quebra de identidade

---

## 5. Sincronizacao de Memoria e Estado

### O que existe hoje

- PC: `D:\ARIS_MEMORY\aris_memory.db` (SQLite, WAL mode, 4 tabelas: memories, associations, working_memory, conversations)
- CLL1: `~/cll1/data/aris_memory.db` (copia local, criada pelo gateway)
- Ja existe mecanismo de fallback unidirecional (`_sync_if_primary_back` no `MemoryService`) — copia fallback→primario quando disco reaparece

### Protocolo de sincronizacao (bidirecional, por timestamp)

```
┌─────────────────────────────────────────────────────────────┐
│ SINCRONIZACAO: CLL1 → PC (o que o CLL1 escreveu sozinho)   │
│                                                              │
│ 1. CLL1 mantem um "sync log" no SQLite:                     │
│    Tabela: sync_log (id, table_name, row_id, operation,     │
│            timestamp, synced_to_pc)                          │
│    Cada INSERT/UPDATE/UPDATE no edge gera uma entrada aqui  │
│                                                              │
│ 2. Quando PC volta online (detectado via handshake):         │
│    CLL1 envia: {"type":"sync_push",                         │
│      "since": "2026-09-14T10:00:00",  # ultima sync          │
│      "pending": [                                            │
│        {"table":"memories","op":"insert","data":{...}},      │
│        {"table":"conversations","op":"insert","data":{...}}, │
│        ...                                                   │
│      ]}                                                      │
│                                                              │
│ 3. PC recebe e importa:                                      │
│    Para cada registro:                                       │
│    - Se ja existe (id duplicado): ignora (ja sincronizado)  │
│    - Se e novo: INSERT com timestamp preservado              │
│    - Se timestamp do edge > timestamp do PC: UPDATE          │
│    - Se timestamp do PC > timestamp do edge: mantem PC       │
│    (regra: timestamp mais recente vence — last-write-wins)   │
│                                                              │
│ 4. PC confirma: {"type":"sync_ack", "synced": 42}           │
│    CLL1 marca registros como synced_to_pc=1                  │
│                                                              │
│ 5. CLL1 pode limpar registros antigos synced ( > 30 dias)   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ SINCRONIZACAO: PC → CLL1 (atualizacoes do PC)               │
│                                                              │
│ 1. Quando PC detecta que CLL1 reconectou:                    │
│    PC envia: {"type":"sync_push",                            │
│      "since": CLL1.last_sync_timestamp,                      │
│      "personalidade_hash": "...",                            │
│      "pending": [...registros novos desde a ultima sync...]} │
│                                                              │
│ 2. CLL1 importa (mesma logica: last-write-wins)              │
│ 3. CLL1 confirma                                            │
└─────────────────────────────────────────────────────────────┘
```

### Regra de conflito: last-write-wins

| Cenario | Resolucao |
|---|---|
| Mesma memoria editada nos dois lados | Timestamp mais recente vence |
| CLL1 criou memoria que PC ja tem (id duplicado) | Ignora (ja existe) |
| PC deletou memoria que CLL1 ainda tem | PC vence (deletion persiste) |
| working_memory conflitante | PC vence (state mais completo) |
| conversations conflitantes | Nunca conflita (sao append-only) |

### Quem manda durante a transicao

```
Timeline:
  T0: PC offline, CLL1 respondendo
  T1: PC liga, handshake com CLL1
  T2: Sync bidirecional (pode levar alguns segundos)
  T3: Sync completo, PLL1 notifica usuario

Durante T1-T2 (antes do sync completar):
  - Mensagens que chegam ao CLL1: CLL1 responde normalmente (edge mode)
  - Mensagens que chegam ao PC: PC responde normalmente (principal)
  - Nao ha conflito: cada um atende seu canal
  - A sync roda em background, nao bloqueia nenhum dos dois

Durante T2-T3 (sync em andamento):
  - CLL1 pode ter memorias "stale" (ainda nao sincronizadas)
  - Isso e aceitavel — proxima mensagem pode usar memorias desatualizadas
  - Resolucao: sync completa rapida (< 1s para poucos registros)

Apos T3:
  - CLL1 notifica: "O PC ligou, ja posso continuar com a versao completa"
  - Proxima mensagem do usuario: CLL1 redireciona ao PC
  - CLL1 entra em modo "standby" (so heartbeats + relay se Discord)
```

---

## 6. Wake-on-LAN — Fluxo com Confirmacao Explicita

### Regra absoluta

**Nunca ligar o PC automaticamente** baseada em rotina, aprendizado, horario ou previsao. Nao e uma feature, e uma prohibicao.

### Fluxo detalhado

```
┌─────────────────────────────────────────────────────────────┐
│ CASO 1: "Aris, liga o PC" (pedido de acao)                  │
│                                                              │
│ 1. LLM interpreta como intent wake_on_lan                   │
│ 2. Edge pergunta: "Quer que eu ligue o PC? Confirma?"       │
│    (edge SEMPRE pede confirmacao — acao CRITICAL)           │
│ 3. Usuario: "Sim" / "Confirma" / "pode ligar"               │
│ 4. Edge executa WoL (envia magic packet na rede local)      │
│ 5. Edge: "PC ligando... vou notificar quando estiver pronto"│
│ 6. PC inicia, handshakes com CLL1, sync roda                │
│ 7. CLL1 notifica: "PC ligou e pronto!"                      │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│ CASO 2: "Aris, voce acha que eu vou usar o PC agora?"       │
│            (pergunta sobre o PC)                              │
│                                                              │
│ 1. LLM interpreta como pergunta (nao gera intent)           │
│ 2. Edge responde normalmente: "Voce quem sabe! Mas posso    │
│    te ajudar a organizar seu dia."                           │
│ 3. Nenhuma acao WoL e executada                              │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│ CASO 3: "Aris, amanha eu preciso do PC as 9h"               │
│            (compromisso futuro)                               │
│                                                              │
│ 1. World Model classifica: commitment + deadline             │
│ 2. Edge salva como lembrete, NAO executa WoL                │
│ 3. Edge: "Anotado! Te aviso amanha as 9h."                   │
│ 4. (WoL so seria executado se o lembrete for acionado       │
│    E o usuario confirmar explicitamente na hora)             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Distincao no codigo (reaproveitando World Model)

```
_classify_commitment(text) → (is_commitment, is_reminder, has_recurrence)

"Aris, liga o PC"
  → is_commitment=True (verbo "liga" = acao)
  → LLM gera intent: module="wake_on_lan", action="execute"
  → SecurityGate: risk=4 (CRITICAL) → REQUIRES_CONFIRMATION
  → Edge pede confirmacao → usuario confirma → executa

"Aris, voce acha que eu vou usar o PC?"
  → is_commitment=False (pergunta, nao acao)
  → LLM NAO gera intent (só resposta natural)
  → Nenhuma acao executada

"Aris, amanha preciso do PC as 9h"
  → is_commitment=True, is_reminder=True
  → LLM gera intent: module="scheduler", action="add_reminder"
  → SecurityGate: risk=2 (CAUTION) → APPROVED
  → Salva lembrete (nao executa WoL)
```

### Transicao edge → principal apos WoL

```
1. CLL1 envia magic packet (WoL)
2. PC liga, inicia A.R.I.S.
3. PC manda handshake ao CLL1: {"type":"handshake","role":"principal",...}
4. CLL1 responde: {"type":"handshake_ack","pending_sync":42,...}
5. Sync bidirecional roda (Secao 5)
6. CLL1 notifica usuario no Discord:
   "O PC ligou e estou operando na versao completa. Pode mandar!"
7. Proxima mensagem do usuario: CLL1 redireciona ao PC
8. CLL1 entra em standby (so heartbeats)
```

---

## 7. Diagrama de Fluxo Atualizado

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ESTADO 1: PC ONLINE                              │
│                                                                     │
│  Discord User ──► Discord Bot ──► CLL1 ──► PC ──► NeuralCore       │
│                                                  │                  │
│                                                  ▼                  │
│                                             SecurityGate            │
│                                                  │                  │
│                                                  ▼                  │
│                                             ActionEngine            │
│                                                  │                  │
│  Discord User ◄── Discord Bot ◄── CLL1 ◄── PC ◄─┘                  │
│                                                                     │
│  CLL1 neste modo: relay + heartbeats + status                       │
│  CLL1 NAO processa IA (PC manda)                                    │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                    ESTADO 2: PC OFFLINE                             │
│                                                                     │
│  Discord User ──► Discord Bot ──► CLL1 ──► edge_chat.py            │
│                                        │                            │
│                                        ├── Groq (chave edge)       │
│                                        ├── MemoryService (local)   │
│                                        └── SecurityGate (local)    │
│                                             │                      │
│                                             ▼                      │
│                                        resposta                    │
│                                                                     │
│  Discord User ◄── Discord Bot ◄── CLL1 ◄── resposta                │
│                                                                     │
│  CLL1 neste modo: IA completa (conversa + memoria + acoes seguras) │
│  CLL1 informa: "PC offline, modo edge ativo"                       │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                    ESTADO 3: TRANSICAO                              │
│                                                                     │
│  [T0] PC liga → handshake com CLL1                                 │
│  [T1] Sync bidirecional (memorias + personalidade)                  │
│  [T2] CLL1 notifica: "PC pronto, versao completa ativa"            │
│  [T3] CLL1 entra em standby, PC assume                             │
│                                                                     │
│  Durante T0-T2: cada um atende seu canal normalmente               │
│  Nao ha downtime na atendimento                                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. Arquivos — Criados vs. Modificados

### Novos (criar)

| Arquivo | Onde | Proposito |
|---|---|---|
| `core/cll1_server.py` | PC | Server TCP assincrono. Aceita conexoes do CLL1, autentica, despacha para `_input_queue` ou para sync. |
| `modules/discord_bot.py` | PC ou cloud | Bot Discord (disc.py). Recebe mensagens, roteia via `cll1_server` quando PC online, via edge quando offline. |
| `core/message_origin.py` | PC | Dataclass `MessageOrigin(source, channel, user_id, timestamp)` — proveniencia. |
| `core/sync_engine.py` | PC | Engine de sincronizacao: merge SQLite, resolucao de conflito (last-write-wins), sync log. |
| `edge/edge_chat.py` | CLL1 | Modo edge: chat com LLM proprio, personalidade sync, memoria local, SecurityGate local. |
| `edge/edge_config.py` | CLL1 | Config do edge: carrega `.env` do Termux, caminhos locais, fallback de personalidade. |
| `edge/edge_sync.py` | CLL1 | Sync client: envia pendencias ao PC, recebe atualizacoes, merge local. |

### Modificados (alterar existentes)

| Arquivo | O que muda | Reaproveita |
|---|---|---|
| `core/aris.py` | `send_message()` aceita `origin: MessageOrigin`. `_get_input()` propaga origin. `_build_handler_context()` inclui `"origin"`. | Fase 7 `_input_queue` |
| `core/neural/decision/decision_engine.py` | `Decision` ganha campo `origin: MessageOrigin`. | `Decision.source` existente |
| `core/neural/core.py` | `execute()` propaga `origin` no `ActionResult.metadata`. | `ActionResult.metadata` existente |
| `core/cll1_client.py` | Adicionar `sync_push()`, `sync_request()`, `handshake()`. | Protocolo 8-byte prefix existente |
| `core/cll1_heartbeat.py` | Heartbeat inclui `pc_status` (online/offline) e `edge_mode` (ativo/inativo). | `CLL1State` existente |
| `gateway.py` | Handlers `sync_push`, `sync_ack`, `handshake`, `relay_to_pc`, `relay_from_pc`. | Handlers existentes |
| `config/settings.py` | Novas configs: `EDGE_GROQ_API_KEY`, `DISCORD_BOT_TOKEN`, `SYNC_INTERVAL`. | `Settings` existente |
| `.env.example` | Adicionar `EDGE_GROQ_API_KEY`, `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`. | `.env.example` existente |

### Nao modificar

| Arquivo | Por que |
|---|---|
| `core/neural/security/security_gate.py` | E a mesma SecurityGate em ambos os instances. Nao muda. |
| `core/advanced_interpreter.py` | Interpretador e o mesmo. O prompt inclui "modo edge" quando apropriado. |
| `config/personality.py` | Fonte da verdade no PC. Nao muda — e sincronizado para o CLL1. |

---

## 9. Seguranca — Modelo de Ameaça Atualizado

### Vetores de ataque

| # | Vetor | Risco | Mitigacao |
|---|---|---|---|
| 1 | Token `CLL1_TOKEN` vaza | Atacante envia comandos ao PC | Token + TLS + janela 60s + SecurityGate |
| 2 | Chave `EDGE_GROQ_API_KEY` vaza | Atacante usa Groq no escopo do edge | Rate limit 100 req/dia; billing alert; chave revogavel |
| 3 | Atacante se passa por voce no Discord | Envia "desliga o PC" | Whitelist de user IDs; SecurityGate CRITICAL |
| 4 | Celular comprometido (malware) | Atacante tem acesso total ao CLL1 | Edge so tem: Groq (rate limited) + SQLite local. Sem acesso ao PC. |
| 5 | Man-in-the-middle CLL1 ↔ PC | Intercepta sync | TLS quando fora da LAN; token em cada mensagem |
| 6 | Replay de mensagens | Atacante reenvia comando valido | Timestamp + nonce; janela 60s |
| 7 | Sync injeta dados corrompidos no PC | Memoria corrompida | Validacao de schema antes de importar; backup antes de sync |
| 8 | Edge responde com info desatualizada | Usuario recebe resposta errada | Edge informa "PC offline, informacoes podem estar desatualizadas" |

### Hierarquia de seguranca

```
SecurityGate (mesma em ambos os instances)
    │
    ├── Aprova/rejeita AÇÕES (intent → decision → approve)
    │   Risk 1-2: aprovado automaticamente
    │   Risk 3: aprovado com audit log
    │   Risk 4: REQUIRES_CONFIRMATION (sempre)
    │
    ├── NAO tem bypass por origem
    │   "discord" != bypass
    │   "cll1" != bypass
    │   "edge" != bypass
    │
    └── Edge tem SecurityGate LOCAL
        Mesma allowlist (registrada no edge)
        Mesma classificacao de risco
        Mesma politica de confirmacao
        (Nao herda do PC — e uma copia identica)
```

---

## 10. Riscos e Trade-offs

### Risco 1: Duas instancias SQLite para manter sincronizadas

**Problema:** SQLite nao foi projetado para replicacao. A solucao manual (sync log + last-write-wins) e simplificada.

**Trade-off:** Aceitavel para uso pessoal (1 usuario, 2 dispositivos). Nao e um sistema distribuido de producao.

**Mitigacao:** Sync apenas quando ambos online. Backup antes de cada sync. Se conflito irresolve, PC vence (single source of truth).

---

### Risco 2: Edge e funcionalidade reduzida

**Problema:** O usuario pode se frustrar com "nao consigo fazer isso" do edge.

**Trade-off:** Preferivel a nao responder nada. A transparencia ("PC offline, estou no modo basico") e melhor que silencio.

**Mitigacao:** Documentar claramente no prompt do edge quais capacidades estao disponiveis. Sugerir WoL quando acao complexa e pedido.

---

### Risco 3: Chave Groq no celular

**Problema:** Se o celular for comprometido, o atacante tem uma chave de API.

**Trade-off:** Chave separada com rate limit e revogavel. Custo maximo: ~$5/mes (Groq e barato). Risco aceitavel.

**Mitigacao:** Billing alert no Groq; chave pode ser revogada em 30s via dashboard; não ha outros dados sensiveis no edge.

---

### Risco 4: Personalidade pode ficar desatualizada no edge

**Problema:** Se o usuario mudar a personalidade no PC e o CLL1 nao reconectar por dias, o edge usa versao antiga.

**Trade-off:** Aceitavel — a personalidade muda raramente.

**Mitigacao:** Edge verifica hash da personalidade a cada handshake. Se mudou, atualiza. Se PC nunca voltou, usa fallback.

---

### Risco 5: Sync pode ser lento para muitas memorias

**Problema:** Se o CLL1 ficou semanas offline e gerou centenas de memorias, o sync pode demorar.

**Trade-off:** Sync em background, nao bloqueia atendimento.

**Mitigacao:** Paginacao no protocolo de sync (envia 50 registros por vez). Edge continua respondendo enquanto sync roda.

---

### Risco 6: Dois caminhos de SecurityGate para manter

**Problema:** A allowlist do edge e uma copia da do PC. Se o PC adicionar um modulo novo, o edge nao vai conhecer.

**Trade-off:** Edge so registra modulos que ele suporta (websearch, remember, notify, etc.). Modulos novos do PC nao afetam o edge.

**Mitigacao:** Sync inclui lista de modulos registrados. Edge atualiza sua allowlist quando PC volta online.

---

### Risco 7: `_input_queue` nao tem persistencia

**Problema:** Se o PC reiniciar, mensagens na fila sao perdidas.

**Trade-off:** Mensagens do Discord sao reenviaveis (historico). Nao implementar fila persistente para nao adicionar dependencia.

**Mitigacao futura:** Fila SQLite pode ser adicionada como melhoria.

---

## 11. Checklist de Verificacao (pos-implementacao)

### Funcionalidade basica
- [ ] Mensagem do Discord chega ao `_input_queue` do PC (PC online)
- [ ] Resposta do NeuralCore volta ao Discord
- [ ] Quando PC offline, CLL1 responde com edge_chat.py
- [ ] Edge usa chave Groq separada (`EDGE_GROQ_API_KEY`)
- [ ] Edge usa personalidade sincronizada do PC
- [ ] Edge informa "PC offline" quando em modo edge

### Sincronizacao
- [ ] CLL1 envia memorias novas ao PC quando volta online
- [ ] PC importa memorias sem duplicatas (last-write-wins)
- [ ] Personalidade sincronizada a cada handshake
- [ ] Sync nao bloqueia atendimento de nenhum dos dois

### Seguranca
- [ ] SecurityGate valida acoes tanto no PC quanto no edge
- [ ] Acoes CRITICAL pedem confirmacao em ambos os instances
- [ ] Token CLL1 nao esta no git
- [ ] Chave Groq do edge e separada da chave master
- [ ] TLS ativo quando CLL1 esta fora da LAN

### Wake-on-LAN
- [ ] "Aris, liga o PC" → edge pede confirmacao → executa WoL
- [ ] "Aris, voce acha que eu vou usar o PC?" → resposta normal, sem WoL
- [ ] Apos WoL, PC assume atendimento e CLL1 notifica transicao
- [ ] WoL nunca executado automaticamente por rotina/previsao

### Testes
- [ ] Testes existentes continuam passando (552 coletados)
- [ ] Novos testes para sync_engine, edge_chat, message_origin

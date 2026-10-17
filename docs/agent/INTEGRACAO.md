# Integração — Parte 8 (ARIS antiga ↔ agente `aris_agent`)

Data: 2026-10-16 · Plano prévio em `docs/agent/INTEGRACAO_PLANO.md`
(escrito **antes** de tocar qualquer arquivo antigo, conforme o prompt).

## 1. Resumo

A A.R.I.S. passou a aceitar o agente novo (`aris_agent/`) por trás de um
**interruptor desligado por padrão** (`ARIS_AGENT_ENABLED`). Com o switch
desligado o comportamento é **idêntico ao atual** (paridade de suíte
comprovada). Com ele ligado, depois da Camada Reflexo/atalhos
determinísticos, um roteador leve decide: **conversa → caminho antigo
intacto; tarefa → agente completo** (planeja, usa ferramentas sob política
de segurança, confirma ações destrutivas por voz e responde falando).

Três arquivos antigos tocados (os únicos): `core/aris.py`,
`edge/edge_chat.py` e `requirements.txt`. Tudo mais é novo e vive em
`aris_agent/bridge/`.

## 2. Interruptor e variáveis

| Variável | Padrão | O que faz |
|---|---|---|
| `ARIS_AGENT_ENABLED` | **desligado** | liga a ponte (aliases: `ARIS_AGENT_AGENT_ENABLED`, ou `"agent_enabled": true` no `aris_agent.json`) |
| `ARIS_AGENT_PERFIL` | `desktop` | `edge` = só `web_*` + memória (nunca `pc_*`/`browser_*`) |
| `ARIS_AGENT_CONFIRM_TIMEOUT_S` | 30 | timeout da confirmação por voz/teclado (**estourou = nega**) |
| `ARIS_AGENT_MAX_STEPS` | 12 | limite de passos por tarefa |
| `ARIS_AGENT_MAX_TOOL_CHARS` | 8000 | corte do texto de cada resultado de ferramenta |
| `ARIS_AGENT_MAX_TOTAL_TOKENS_PER_TASK` | 60000 | orçamento de tokens por tarefa |
| `ARIS_AGENT_DATA_DIR` | `~/.aris_agent` | onde procurar `aris_agent.json` |
| `ARIS_AGENT_AUDIT_LOG` | `<data_dir>/audit.jsonl` | trilha de auditoria da Parte 5 |
| `ARIS_MEMORY_DIR` | `data/memory` | local da memória antiga (migração) |

Chaves de JSON: `agent_enabled`, `workspace_dir`, `data_dir`,
`allowed_roots`, `max_steps`, `confirm_timeout_s` e
`sections.{llm,safety,web}`. Use **`aris_agent.example.json`** como modelo:
a seção `llm` com `providers` + `chains` é obrigatória para o agente ligar —
sem ela a ponte loga aviso e fica fora (o caminho antigo continua
respondendo). Credenciais ficam no `.env`/ambiente e são referenciadas por
`api_key_env` (o JSON tem credenciais removidas com aviso, por design da
Parte 0).

## 3. Fluxo no loop principal (`core/aris.py`)

```
entrada (fila / teclado / microfone)
  → gate WhatsApp (como hoje)
  → Camada Reflexo (como hoje)
  → NeuralCore determinístico (como hoje)
  → [NOVO] ponte.processar(texto)      ← só se ARIS_AGENT_ENABLED
       ├─ frase "para tudo"       → KillSwitch + "Parei, chefe."
       ├─ kill já ativo           → None  (agente quieto)
       ├─ roteador: conversa      → None  (caminho antigo intacto)
       └─ roteador: tarefa        → ArisAgent.run(...) → resposta falada
  → answer-learning → LLM antigo (como hoje, quando a ponte devolveu None)
```

Qualquer exceção dentro do bloco vira log + `None` → o fluxo antigo
continua. A ponte nunca derruba o loop; a fábrica nunca derruba o boot.

## 4. Arquivos antigos tocados (só estes)

### `core/aris.py` — 5 pontos cirúrgicos (todos marcados `# Parte 8:`)

1. `__init__`: `self._agent_bridge = None` (logo após a Reflex Layer).
2. `start()`: `self._agent_bridge = self._build_agent_bridge()` logo após a
   criação do `ThreadPoolExecutor`.
3. `start()`: novo método `_build_agent_bridge()` — adapta `falar`/`ouvir` da
   voz ativa e chama `build_bridge(...)`; qualquer falha → `None` + aviso no
   logger legado.
4. Loop: bloco `if self._agent_bridge is not None:` entre o NeuralCore e o
   answer-learning, no mesmo formato do bloco reflex (cognitive trace →
   UI → voz → `continue`).
5. `shutdown()`: `self._agent_bridge.parar()` — cancela execução em
   andamento (KillSwitch) junto com os demais `stop()`.

### `edge/edge_chat.py` — 2 pontos

- `_agente_edge(texto)` (função de módulo, com cache): só tenta com
  `ARIS_AGENT_ENABLED=true`; perfil `edge` (só `web_*` + memória);
  falha de montagem vira `None` e fica em cache (não remonta a cada
  mensagem).
- `respond()`: logo após o rate limit e antes do fast path — `None` segue o
  fluxo atual.
- **Confirmação no edge**: sem canal de voz, `ouvir` devolve `None` → toda
  confirmação **nega por timeout** (seguro por padrão; documentado).

### `requirements.txt` (raiz)

Consolidação autorizada no plano §2.3 — só entradas que **faltavam**:
`httpx` (Parte 1), `send2trash`/`pywinauto` (Parte 2), `trafilatura`/`ddgs`
(Parte 3) e a pilha de voz que o código antigo usa mas o arquivo não tinha
(`faster-whisper`, `webrtcvad-wheels`, `pygame-ce`, `pyaudio`). Nada foi
removido.

## 5. Novos arquivos (`aris_agent/bridge/`)

| Arquivo | Papel |
|---|---|
| `factory.py` | `build_agent(cfg, perfil, llm)` → `PacoteAgente` (agente, executor, kill switch, memória, skills, registry). Qualquer falha → `None` + aviso |
| `rota.py` | `Roteador`: frases de parada (texto curto) + `classificar_regras` (o classificador avaliado na Parte 9) + gates: `perigoso` → agente sempre; frase >160 chars → conversa (recado não vira comando) |
| `voz.py` | `ConfirmanteDeVoz` (fala o resumo; hard exige começar com "sim/confirma") + `entrada_com_tempo` (teclado com timeout, Windows-safe) |
| `eventos.py` | `FaladorDeEventos`: `tool_call` → frase curta ("pesquisando..."), sem repetir em sequência, silêncio p/ desconhecidas |
| `migracao.py` | `importar_memoria_antiga`: lê `memory_entries` **read-only** e chama `SqliteMemory.import_records` (idempotente) |
| `ponte.py` | `Ponte.processar()` (fronteira: nunca lança exceção) + `build_bridge()` (lê o interruptor e monta tudo) |
| `__init__.py` | API pública: `build_bridge`, `Ponte`, `Roteador`, `ConfirmanteDeVoz`, `FaladorDeEventos`, `build_agent`, migração |

## 6. Migração da memória antiga

- Roda **uma vez por boot** da ponte (perfil desktop), antes da primeira
  tarefa; loga `created/updated/skipped`.
- Fonte: `<ARIS_MEMORY_DIR>/aris_memory.db` → `D:/ARIS_MEMORY` →
  `<repo>/data/memory`.
- Idempotente (dedup por texto): rodar N vezes não duplica. O banco legado
  **não é modificado** (conexão `mode=ro`); categorias viram
  `kind` (`UserProfile→preference`, `lessons→lesson`, resto `fact`).
- `created_at` TEXT legado: aceita epoch e ISO; formato desconhecido usa o
  "agora" (nunca falha a importação inteira por um registro).

## 7. Parada de emergência

- Voz: **"para tudo" / "pare tudo" / "cancela tudo" / "para agora" /
  "chega disso"** (frase curta; a mesma frase dentro de texto longo não
  conta) → `KillSwitch.engage(...)`: cancela a tarefa em andamento, nega
  todas as ferramentas e responde **"Parei, chefe."**
- Depois de ativo o agente fica quieto (`processar` → `None`; o caminho
  antigo continua respondendo) até **reiniciar a ARIS** — `engage` é em
  memória; o arquivo-sentinela `STOP` não é escrito pela ponte.
- Programático: `ponte.parar()` (chamado no `shutdown`) ou
  `ponte.kill_switch.engage("motivo")`.
- Atalho global (opcional, desligado por padrão): `"safety": {"enable_hotkey":
  true, "hotkey": "ctrl+alt+F12"}` no `aris_agent.json` → o `SafeExecutor`
  constrói o `KillSwitch` com o atalho e chama `start_hotkey()` (no Windows
  pode exigir admin; a lib `keyboard` é opcional — ver
  `requirements/parte5.txt`).

## 8. Confirmação por voz

- Ação destrutiva/em lote → a ponte **fala** o resumo e pergunta. Hard
  (destrutivo): fala "atenção: é ação destrutiva. Responda sim…" e exige
  começar com "sim/confirma"; soft: aceita "sim/pode/confirma".
- **Timeout = negar** (padrão 30 s; `ARIS_AGENT_CONFIRM_TIMEOUT_S`).
- A fala roda **com teto** (`fala_max_s`, 4 s): um TTS lento ou quebrado
  (ex.: edge-tts em retry) não pode comer o orçamento da confirmação — a
  ouvida começa com o tempo restante (descoberto no teste real da §9; bug
  corrigido aqui mesmo, no adaptador).
- Microfone ligado → `HybridVoice.listen`; senão → linha no terminal
  (`Confirmar (sim/não): `). Sem áudio/teclado, dúvida ou texto
  ininteligível → nega.

## 9. Resultados (paridade)

| Suíte | Antes | Depois |
|---|---|---|
| `tests/aris_agent` | 832 passed, 48 skipped, 0 failed | **900 passed, 48 skipped, 0 failed** (+68 da Parte 8) |
| `tests/` legado (fora de `aris_agent`) | 1133 passed, 16 failed | idêntico: 1133 passed, 16 failed |

Os 16 failed legados são pré-existentes (discord/gmail/NLU/path de Windows,
ver baseline no plano) — mesmos itens antes e depois; nenhum novo.

Os 69 testes de `tests/aris_agent/parte8/` cobrem: roteamento validado no
dataset real da Parte 9 (≥90% geral, ≥95% perigoso), frases de parada,
confirmação (timeout/hard/dúvida), eventos e dedup, migração idempotente,
fábrica (desktop vs edge vs sem providers), ponte ponta a ponta com
`FakeLLM` (conversa/tarefa/kill/negativa/execução real com `pc_delete_file`)
e o edge desligado por padrão.

### E2E real (Linux, agente ligado, LLM Groq de verdade)

Fumaça com `./aris.sh --mic-off` + `ARIS_AGENT_ENABLED=true` e entradas
pipeadas (`apaga o arquivo fumo_teste.txt` → `sim` → `para tudo` → `sair`):

- `pc_delete_file` executada de verdade após confirmação **"sim"** pelo
  teclado → arquivo foi para a Lixeira; trace final:
  *"Arquivo **fumo_teste.txt** apagado e enviado para a Lixeira, chefe."*
- "para tudo" → `KILL SWITCH ativado: parada por voz do usuário (ponte
  Parte 8)` + resposta "Parei, chefe."
- migração da memória antiga rodou no boot (1 registro importado de
  `D:/ARIS_MEMORY/aris_memory.db`, idempotente) e `sair` → shutdown limpo,
  **exit 0**.
- Descoberta dessa execução: o **edge-tts está em 403 neste ambiente**
  (retries de ~12 s) — com a fala síncrona antiga isso esgotava o orçamento
  de 15 s da confirmação antes da ouvida (negava por timeout). Corrigido no
  adaptador: fala com teto de 4 s (§8). A falha do edge-tts é do
  serviço/ambiente e afeta igualmente a fala do caminho antigo — não é da
  ponte (ver limitações no relatório final).

## 10. Reversão

1. **Desligar sem mexer em código**: `ARIS_AGENT_ENABLED` fora (ou
   `"agent_enabled": false`) → comportamento atual.
2. **Reverter o wiring**: `git checkout -- core/aris.py edge/edge_chat.py
   requirements.txt` (blocos novos isolados e marcados `# Parte 8:`).
3. Os arquivos novos (`aris_agent/bridge/`, testes, docs) não são importados
   por nenhum módulo antigo: podem sair sem efeito colateral.

## 11. Checklist manual

**Cenários pedidos para o Vinicius testar no Windows** (com o agente ligado):

1. **Voz**: dizer a wake word e um comando simples → resposta falada.
2. **Abrir app**: "abre o bloco de notas" → fala de status + eventual
   confirmação (`pc_open_app`).
3. **Pesquisa**: "pesquisa as notícias de hoje" → "pesquisando na web..."
   (`web_search`/`web_fetch`) e a resposta falada.
4. **Apagar arquivo com confirmação**: "apaga o arquivo X" → pergunta
   destrutiva por voz; "sim" executa, "não"/silêncio (30 s) nega.
5. **KillSwitch**: "para tudo" → "Parei, chefe."; as tarefas seguintes não
   passam pelo agente até reiniciar.
6. **Desligado** (`ARIS_AGENT_ENABLED` fora): tudo igual ao comportamento
   atual (paridade verificada por suíte).

Neste repo (Linux):

1. `cp aris_agent.example.json aris_agent.json` e conferir a seção `llm`
   (`api_key_env: GROQ_API_KEY`, com a chave no `.env`).
2. `ARIS_AGENT_ENABLED=true ./aris.sh` → no log deve aparecer
   `Ponte do agente ativa (ARIS_AGENT_ENABLED=true).` (sem ela, a ponte
   está desligada/indisponível e o `.env` é carregado pelo Settings).
3. "Aris, apaga o arquivo `algo.txt` no workspace" → deve falar a
   confirmação destrutiva; responda "sim".
4. "Aris, para tudo" → "Parei, chefe." (e tarefas seguintes não passam pelo
   agente).
5. Reinicie **sem** a variável → tudo volta ao fluxo antigo.

Windows: mesmos passos com `set ARIS_AGENT_ENABLED=true` no prompt antes do
`aris.bat`/`run_aris.bat` correspondente.

## 12. Fora de escopo (registrado em `docs/agent/pedidos/parte8.md`)

- Bug `core/aris.py:1734` (`message_callback=`, camada CLL1) — pré-existente,
  não tocado.
- `requirements/parte7.txt` com linha sem `#` (quebra `pip install -r`).
- `pyproject.toml` → script `aris = "main:main"` aponta para `main.py`
  inexistente.

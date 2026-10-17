# Plano de Integração — Parte 8 (escrito ANTES de editar qualquer arquivo antigo)

Data: 2026-10-16 · Autor: Parte 8 · Status: executado conforme plano
(resultado em `docs/agent/INTEGRACAO.md`)

## 1. Levantamento (só leitura) — resumo do fluxo atual

| Etapa | Onde | Como |
|---|---|---|
| Entrada | `core/aris.py` `Aris.send_message` (499) / `_get_input` (507) | fila assíncrona, stdin ou microfone (`HybridVoice.listen`); wake word em `core/perception/continuous_voice_sensor.py` |
| Gate WhatsApp | `core/aris.py:946-963` | roda antes de tudo (confirmações) |
| Camada Reflexo | `core/reflex_layer.py` `ReflexLayer.process` (417) | mini-agentes determinísticos (time, calc, sys, memory, jokenpo) |
| Neural determinístico | `core/neural/core.py` `NeuralCore.process` (210) | devolve `None` quando precisa de LLM |
| LLM antigo | `core/multi_provider.py` `MultiProviderChat.send` (54) → `core/llm/router.py` | providers via env (`GROQ_API_KEY` etc.), histórico em RAM (6000 chars) |
| Voz | `utils/voice_hybrid.py` `HybridVoice.speak` (181) / `listen` (399) | edge-tts → pygame; fallback pyttsx3 |
| Memória antiga | `core/memory.py` `MemoryManager` + `core/memory_db.py` (`memory_entries`) e `core/memcore/` | SQLite em `data/memory/aris_memory.db` (ou `ARIS_MEMORY_DIR`) |
| Configuração | `config/settings.py` (dataclass congelada) + `.env` | convenção de flags: `os.getenv("X_ENABLED") == "true"` |
| EDGE (celular) | `edge/edge_chat.py` `EdgeChat.respond` (226) | fast path → planner → NLU → Ollama/PC |
| Parada | `Aris.shutdown` (1791); não existe kill switch global | só exit/sair, SIGINT e barge-in de voz |

**Base de testes antes da integração:** `pytest tests/aris_agent` →
`832 passed, 48 skipped, 0 failed` (Windows marks aplicados na Parte 9).
O `cll1`/`message_callback=` vs `on_message=` (`core/aris.py:1734`) é bug
pré-existente **fora do escopo** (não tocar; ver §5).

## 2. Arquivos antigos que serão tocados (e só estes)

### 2.1 `core/aris.py` — 4 pontos cirúrgicos

1. **`__init__`** (logo após o bloco da Reflex Layer, linha ≈457): declara
   `self._agent_bridge: Ponte | None = None` (mesmo padrão de
   `self._reflex_layer`/`self._proactive_engine`).
2. **`start()`** (logo após `self._executor = ThreadPoolExecutor(...)` ≈834):
   chamar `build_bridge(...)` dentro de `try/except` — se
   `ARIS_AGENT_ENABLED` estiver ausente/desligado ou qualquer import falhar,
   `self._agent_bridge` fica `None` e só um warning é logado. **Nunca** derruba
   a ARIS.
3. **loop principal** (entre o bloco do NeuralCore, que termina na linha 1018,
   e o `_looks_like_answer`, linha 1020): inserir o bloco da ponte:

   ```python
   # Parte 8: roteamento para o agente (desligado por padrão)
   if self._agent_bridge is not None:
       try:
           resposta_agente = self._agent_bridge.processar(user_input, origin=msg_origin)
       except Exception as e:
           self._logger.error(f"Agente: falha; seguindo o caminho atual ({e})")
           resposta_agente = None
       if resposta_agente is not None:
           ... falar + registrar contexto + continue   # mesmo formato do bloco reflex
   ```

   A ponte devolve `None` ⇒ o fluxo antigo (answer-learning → LLM antigo)
   segue **intacto**.
4. **`shutdown()`** (junto aos demais `stop()`, ≈1865): `self._agent_bridge.parar()`
   — cancela execução em andamento (KillSwitch) e encerra a fábrica.

### 2.2 `edge/edge_chat.py` — 1 ponto

Em `EdgeChat.respond()`, **depois** do rate limit e **antes** do fast path:
bloco guardado por `ARIS_AGENT_ENABLED` (padrão desligado ⇒ zero mudança de
comportamento). Se ligado, usa a ponte no **perfil `edge`** (somente
`web_*` + memória, sem ferramentas de PC). Ponte `None` ou exceção ⇒ continua
no fluxo atual (`fast path` etc.).

### 2.3 `requirements.txt` (raiz)

Consolidar os `requirements/parteN.txt` (0–9) no arquivo raiz, mantendo as
entradas legadas que o código antigo usa (edge-tts, SpeechRecognition, etc.).
Nada é removido; só se adiciona o que falta (ex.: `faster-whisper`,
`webrtcvad`, `pygame-ce` já usados pelo código e ausentes do arquivo velho).

## 3. O que NÃO será tocado

- `core/multi_provider.py`, `core/llm/router.py`, `core/reflex_layer.py`,
  `core/neural/*`, `utils/voice*.py`, `core/memory*.py`, `core/memcore/*`,
  `config/settings.py`, `modules/`, `cll1/`, `agent/`, `plugins/` — leitura
  apenas.
- Bug do `message_callback=` em `core/aris.py:1734` (CLL1): **fora de escopo**
  (registrado em `docs/agent/pedidos/...`; corrigi-lo muda comportamento de
  distribuição que não tem teste).
- Nenhum refator de código antigo "aproveitando" (regra da Parte 8).

## 4. Novos arquivos (`meus`)

- `aris_agent/bridge/__init__.py`, `ponte.py`, `factory.py`, `rota.py`,
  `voz.py`, `eventos.py`, `migracao.py`
- `tests/aris_agent/parte8/…`
- `requirements/parte8.txt`, `docs/agent/INTEGRACAO.md`,
  `aris_agent.example.json`
- `docs/agent/pedidos/parte8.md` (se houver pedido)

**Ordem:** factory → rota → voz → eventos → migração → ponte → wiring em
`core/aris.py` → wiring em `edge/edge_chat.py` → testes → docs.

## 5. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Erro no loop principal quebrando a ARIS | bloco inteiro em `try/except`; falha ⇒ log + fluxo antigo (`None`) |
| Import do `aris_agent` quebrando o boot | `build_bridge` engole exceção de import/construct e devolve `None` com warning |
| Comportamento mudando com o agente desligado | switch `ARIS_AGENT_ENABLED` padrão **desligado**; testes de paridade; suíte antes/depois idêntica |
| Confirmação de voz travando o loop | timeout (padrão 15 s) com **timeout = negar**; teclado como alternativa |
| EDGE sem PC/som ganhando ferramentas de PC | perfil `edge` só `web_*` + memória; desligado por padrão |
| Migração duplicando memória antiga | `SqliteMemory.import_records` é idempotente (dedup por texto) — rodar N vezes é seguro |
| Kill switch persistindo entre reinícios | `KillSwitch.engage()` é em memória (arquivo-sentinela só é lido, não escrito por nós); estado dura até reiniciar a ARIS |

## 6. Plano de reversão

1. Desligar: remover/`false` em `ARIS_AGENT_ENABLED` no `.env` → a ARIS volta
   ao comportamento atual sem recompilar nada.
2. Reverter código: `git checkout -- core/aris.py edge/edge_chat.py requirements.txt`
   (os blocos novos estão isolados e comentados com `# Parte 8:`).
3. Os arquivos novos (`aris_agent/bridge/`, testes, docs) podem ser removidos
   sem efeito colateral: nenhum módulo antigo importa `bridge`.

## 7. Critérios de pronto

- Com o switch desligado: suíte antiga com o **mesmo resultado** do baseline
  (`832 passed, 48 skipped`) e comportamento idêntico (testes de paridade).
- Com o switch ligado (testes com `FakeLLM`): conversa segue o caminho antigo;
  tarefa vai ao agente; confirmação negada bloqueia a ferramenta; fábrica
  indisponível cai no caminho antigo com aviso.
- `docs/agent/INTEGRACAO.md` com diff resumido, switch, reversão e checklist
  manual no Windows.

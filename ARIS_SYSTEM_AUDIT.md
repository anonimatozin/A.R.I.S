# A.R.I.S. — Auditoria Completa do Sistema

> ⚠️ **HISTÓRICO** (revisado em 18/10/2026) — este documento descreve o
> estado do projeto NA ÉPOCA da auditoria e está **desatualizado**. Vários
> itens que ele aponta já foram corrigidos ou mudaram desde então:
> núcleo (`core/aris.py`) muito maior que as "543 linhas" citadas; olhos
> v2 com cenas/ambiente (`aris_eyes/`, `utils/eyes_bridge.py`,
> `utils/eyes_ambient.py`); wake word por palavra inteira + motor dedicado
> (`core/perception/wake_engine.py`, ver `docs/WAKE_WORD.md`); Mini Deck
> ESP32 com portal Wi-Fi (`firmware/esp32_aris/`); os 45 scripts mortos do
> `gateway/` foram removidos (arquivo apagado a pedido do usuário);
> CI (`.github/workflows/testes.yml`); NLU fast-path com resposta local
> rápida (decisão mantida). Use o código e os testes como fonte da
> verdade; este arquivo fica como referência histórica da arquitetura.

> Auditoria **somente-leitura** (sem implementação, sem refatoração, sem correção).
> Documento de referência para a arquitetura do projeto **Neural Core**.
> Escopos marcados como não confirmados usam os rótulos:
> `> NÃO FOI POSSÍVEL CONFIRMAR`, `> NÃO IMPLEMENTADO`, `> NÃO IDENTIFICADO NO PROJETO`.

---

## 1. Resumo Executivo

**A.R.I.S. (Assistente de Raciocínio e Integração de Sistemas)** é um assistente pessoal
de terminal em **Python 3.12**, de arquitetura modular, com:

- Núcleo único (`core/aris.py`, 543 linhas) que orquestra loop REPL, dispatch de intenções via
  `CommandRegistry` e um contexto de dependências montado em `_build_handler_context`.
- **22 intents registrados** em `core/handlers.py` + 2 plugins (`calc`, `hardware`).
- Suporte a voz (SAPI + `HybridVoice` com edge-tts) e STT via `speech_recognition`.
- Módulos de domínio em `modules/` (17 arquivos), gerenciados por `ModuleManager`.
- Integração **ESP32** via WebSocket (firmware em `firmware/esp32_aris/`).
- Memória persistente por arquivos JSON em `data/memory/` (14 categorias).
- Multi-provedor de LLM (`groq` primário + `gemini` fallback) com rate limiting.

**Estado geral**: funcional como protótipo de terminal; **nenhum teste roda hoje**, o
`ModuleManager` **não carrega 7 dos 17 módulos** (3 falhas logadas + 4 falhas silenciosas),
a documentação (**README.md**, **PROMPT_MESTRE.md**) está **desatualizada/incorreta**, e há
**credenciais WiFi em texto claro no firmware versionado** (achado crítico de segurança).
Não há GUI nem servidor web; o "HUD" é 100% ANSI no terminal.

> Total de linhas de código Python (excluindo firmware, docs e dados):
> ~5.400 linhas (contagem aproximada por arquivos lidos).

---

## 2. Contexto e Escopo da Auditoria

- **Objetivo**: inventariar arquitetura, integrações, qualidade, riscos e divergências do
  projeto A.R.I.S. para subsidiar o projeto **Neural Core** (executado por outro arquiteto).
- **Escopo**: todos os diretórios raiz (`core/`, `modules/`, `plugins/`, `config/`, `utils/`,
  `system/`, `search/`, `weather/`, `data/`, `logs/`, `firmware/`, `tests/`, `docs` em nível de
  README/PROMPT), `.env` (apenas nomes de variáveis), git history.
- **Fora de escopo**: execução do sistema, alteração de código, instalação de dependências.
- **Data**: 12/09/2026. **Ambiente**: Windows, PowerShell 5.1, Python 3.12.10 (venv local).

---

## 3. Metodologia e Ferramentas

- Leitura integral dos arquivos-chave com as ferramentas `Read`/`Glob`/`Grep`.
- Greps de verificação para integrações (voz, scheduler, thread pool, GUI, subprocess, eval).
- Verificação de git state (tracked files, `.env`, branch) — somente-leitura.
- Material primário:
  - `C:\Users\Administrator\Documents\Default Project\ARIS\logs\aris.log` (4 boots reais de hoje,
    16:08–16:27).
  - Árvore de arquivos em disco (nome + data de modificação dos módulos).
- **Limitação declarada**: não foi executado código; itens rotulados como não confirmados devem
  ser validados no Neural Core antes de decisões críticas.

---

## 4. Visão Geral do Projeto

- **Nome**: A.R.I.S. — Assistente de Raciocínio e Integração de Sistemas.
- **Linguagem/plataforma**: Python 3.12+; Windows (uso de `pywin32`, `os.system("cls")`, etc.).
- **Interface**: terminal (`input()`) com prompt estilizado ANSI (`utils/terminal.py`).
- **Geração de respostas**:
  `AdvancedInterpreter` (analisa com LLM) → intent `{module, action, params}` →
  `CommandRegistry.execute_intent` → handler em `core/handlers.py` → `ctx`.
- **Execução**: `aris.bat` ativa `venv` e roda `python main.py` (44 linhas).
- **Versionamento**: git privado `https://github.com/anonimatozin/A.R.I.S.git`, branch `main`,
  limpo; 5 commits (Initial → J.A.R.V.I.S. NEXUS → JARVIS v1.0.0 → rename JARVIS→ARIS → docs).

---

## 5. Estrutura de Diretórios

```
ARIS/
├── main.py                  # Ponto de entrada (44 L)
├── aris.bat                 # Launcher (venv + python main.py)
├── requirements.txt         # Dependências completas
├── pyproject.toml           # Mínimo (dotenv/openai/pywin32) — DIVERGENTE
├── README.md                # DESATUALIZADO (lista módulos inexistentes)
├── PROMPT_MESTRE.md         # Especificação "mestre" (dados incompatíveis com o código)
├── PROMPT_CLAUDE.md         # Especificação complementar (registry/plugin/safety/rate-limit)
├── MELHORIAS.txt            # Notas de evolução (2026-08-06)
├── .env                     # NÃO versionado (segredos) — carregado via python-dotenv
├── .gitignore               # Ignora .env, venv, logs/*.log, data/*.json, caches
├── config/                  # settings.py (frozen), esp32_config.py, personality.py
├── core/                    # aris.py, commands.py, handlers.py, intent.py,
│                            #  advanced_interpreter.py, multi_provider.py, rate_limiter.py,
│                            #  memory.py, memory_models.py, memory_organizer.py, module_manager.py
├── modules/                 # 17 módulos internos (ver Seção 18)
├── plugins/                 # calculator.py, esp32_deck.py
├── utils/                   # logger.py, terminal.py, voice.py, voice_hybrid.py, __init__.py
├── system/                  # analyzer.py (SystemAnalyzer)
├── search/                  # hyper_search.py (HyperSearch)
├── weather/                 # hyper_weather.py (HyperWeather)
├── security/                # PACOTE VAZIO (apenas __init__.py)
├── analytics/               # PACOTE VAZIO (apenas __init__.py)
├── automation/              # PACOTE VAZIO (apenas __init__.py)
├── data/                    # memory/ (14 categorias), skills.json, scheduled_tasks.json,
│                            #  screenshots/
├── logs/                    # aris.log (rotação)
├── tests/                   # test_esp32.py (230 L, pytest)
└── firmware/esp32_aris/     # esp32_aris.ino + platformio.ini
```

> **Achados estruturais**: `security/`, `analytics/`, `automation/` existem como **pacotes
> vazios** (apenas docstring em `__init__.py`) — `> NÃO IMPLEMENTADO`.

---

## 6. Dependências e Ambiente

- **Interpreter**: `venv` local com Python **3.12.10** (`C:\Users\Administrator\Documents\Default Project\ARIS\venv`).
- **requirements.txt** (completo, documenta o runtime real), principais:
  `python-dotenv`, `openai`, `google-genai`, `groq`, `requests`, `psutil`, `Pillow`,
  `pyautogui`, `edge-tts`, `pyttsx3`, `SpeechRecognition`, `pywin32`, `websockets`,
  `pytest` (para `tests/test_esp32.py`).
- **pyproject.toml**: conteúdo **mínimo** (`dotenv`/`openai`/`pywin32`) — **divergente** de
  `requirements.txt`.
- **websockets**: `> NÃO INSTALADO` no venv de acordo com o boot log
  (`Hardware: websockets não instalado. Execute: pip install websockets`).
  Consequência: **a conexão real com o ESP32 não estabelesse** (modo placeholder).
- **Git**: 2.55.0.3; identidade local `anonimatozin`; remote privado; `main` limpa.

---

## 7. Configuração

### 7.1 `config/settings.py`
- Classe `Settings` como **dataclass frozen**, valores carregados de `.env`.
- Campos confirmados por nome: `DATA_DIR`, `API_KEYS` (dict por provedor), `LOG_LEVEL`,
  `LOG_MAX_MB`, `PROMPT`, `VOICE_RATE`, `VOICE_VOLUME`, `CHAT_MODEL`, `MEMORY_ROOT`,
  **`SAFETY_PASSWORD`** (não existe `SAFETY_LEVEL` — ver bug na Seção 11).
- **`.env`** (não versionado) contém, por nome: `ARIS_LOG_LEVEL`, `ARIS_MAX_LOG_SIZE_MB`,
  `ARIS_PROMPT`, `ARIS_VOICE_RATE`, `ARIS_VOICE_VOLUME`, `GROQ_API_KEY`, `GEMINI_API_KEY`,
  `ARIS_CHAT_MODEL`, `ARIS_MEMORY_ROOT`, `ARIS_SAFETY_PASSWORD`, `ESP32_ENABLED`,
  `ESP32_WS_PORT`, `HARDWARE_SIMULATION`.

### 7.2 `config/esp32_config.py`
- `ESP32Config` (dataclass frozen): `enabled`, `simulation`, → `ws_port=8766`,
  `heartbeat_interval=5.0`, `heartbeat_timeout=15.0`, `reconnect_interval`, `max_reconnects=10`,
  botões: `button_single_click="voice_toggle"`, `button_double_click="stop_speaking"`,
  `button_long_press="turbo_mode"`.

### 7.3 `config/personality.py`
- Constante com a personalidade do assistente (nega ser Marvel/Tony Stark; define bloco de
  ações inegociáveis). Template de gerador de comandos JSON do `AdvancedInterpreter`.

---

## 8. Ponto de Entrada

`main.py` (44 linhas):
- `sys.stdout.reconfigure(encoding="utf-8")` (Windows).
- Adiciona a raiz do projeto ao `sys.path` (garante imports `core.*`, `config.*`).
- Instancia `Aris()` e chama `.start()`.
- Trata `KeyboardInterrupt` e erro fatal com mensagem amigável.

---

## 9. Núcleo — Classe `Aris` (`core/aris.py`, 543 L)

Responsabilidades e pontos-chave:

- **Montagem de dependências no `__init__`**:
  `Settings`, `Logger`, `MemoryManager`, `MemoryOrganizer`, `HyperSearch`, `HyperWeather`,
  `CommandRegistry`, `ModuleManager`, `ConversationContext`, `AdvancedInterpreter`, `Voice`,
  `HybridVoice`, `MultiProviderChat`, `SystemAnalyzer`, `Scheduler`, `Chat`, `KnowledgeGraph`,
  `SafetyManager`, `HardwareManager`, `ThreadPoolExecutor(max_workers=1)`.
- `start()` (linha ~239): cria estrutura de memória, `module_manager.load_modules()` (linha 245),
  `scheduler.start_checker(callback=self._on_task_due)` (**linha 267** — scheduler **está**
  integrado ao boot), banner e loop REPL com `input`.
- `_build_handler_context()` (linha ~170): monta o dict `ctx` entregue a cada handler com
  instâncias diretas: `memory`, `search`, `weather`, `settings`, `logger`, `chat`,
  `knowledge_graph`, `interpreter`, `voice`, `hardware`, `scheduler`, `safety`, `analyzer`,
  `modules`, `news`, `tasks_report`.
- `_execute_intent(module, action, params)`: se `module == "exit"` → `shutdown()`; senão chama
  `registry.execute_intent(module, action, params, **ctx)`. Handlers imprimem a resposta.
- `_execute_intent_legacy`: **vazio** (fallback morto).
- `_get_dynamic_prompt()`: definido, **nunca invocado** (o REPL usa `terminal`/`input`) → **código morto**.
- `self._intent = IntentAnalyzer()`: instanciado, **nunca utilizado** no loop → **código morto**
  (ver Seção 12).
- `_on_task_due(task)` (linha 397): imprime lembrete e tenta voz/notificações.
- LLM chamado em thread (`ThreadPoolExecutor`) com timeout/cancelamento.
- `shutdown()`: loga, finaliza executor e hardware.

---

## 10. Sistema de Comandos (`core/commands.py`, 183 L)

- `CommandRegistry(logger)`:
  - `register(name, description, callback, aliases)` — comandos por texto.
  - `register_intent(module, description)` — registra handler de intenção.
  - `execute_intent(module, action, params, **ctx)` — **try/except** em todo handler; falha vira
    string de erro (é o que mascara o bug `SAFETY_LEVEL`, Seção 11).
  - `execute_text(text)` — enumeração de comandos de texto.
- Mantém `_safety_levels` e `_pending_confirmation` (confirmação por token para ações
  destrutivas) — alicerce do esqueleto de safety.
- `core/__init__.py` exporta `Aris`, `ModuleManager`, `CommandRegistry`.

---

## 11. Handlers de Intenção (`core/handlers.py`, 622 L)

22 handlers registrados via `@registry.register_intent(...)`:

| Intent | Handler (linha) | Descrição |
|---|---|---|
| `weather` | `handle_weather` (22) | clima via `ctx["weather"].format_report` |
| `websearch` | `handle_websearch` (36) | busca via `ctx["search"].search_and_summarize` |
| `sys` | `handle_sys` (51) | análise CPU/RAM/disco via `ctx["analyzer"]` |
| `desktop` | `handle_desktop` (91) | mouse/teclado/mídia/janelas |
| `scheduler` | `handle_scheduler` (100) | `reminder`/`task`/`pomodoro` via `ctx["scheduler"]` (linhas 110–126) |
| `notify` | `handle_notify` (134) | notificações Windows |
| `context` | `handle_context` (147) | detectar atividade atual |
| `safety` | `handle_safety` (159) | segurança e permissões |
| `entertainment` | `handle_entertainment` (170) | piadas, curiosidades, jogos |
| `turbo` | `handle_turbo` (200) | análise profunda de arquivos/código |
| `knowledge` | `handle_knowledge` (230) | grafo de conhecimento |
| `awareness` | `handle_awareness` (269) | screenshot + OCR |
| `redact` | `handle_redact` (302) | auto-redação de dados sensíveis (13 regex) |
| `digest` | `handle_digest` (329) | briefing diário |
| `browser` | `handle_browser` (360) | automação de navegador (Playwright async) |
| `agents` | `handle_agents` (396) | multi-agente/delegação |
| `skills` | `handle_skills` (427) | sistema de skills |
| `dictation` | `handle_dictation` (455) | modo dictação (falar e digitar) |
| `remember` | `handle_remember` (492) | salvar memória |
| `search` | `handle_search_memory` (535) | buscar memória |
| `config` | `handle_config` (556) | **BUG — atributo inexistente** |
| `speak` | `handle_speak` (571) | ligar/desligar voz |

**BUG CONFIRMADO — intent `config`** (`handlers.py:556`):
`handle_config` acessa `settings.SAFETY_LEVEL`, que **não existe** em `Settings`
(existe `SAFETY_PASSWORD`). A chamada levanta `AttributeError`, capturada pelo try/except de
`execute_intent`, então o intent `config` **sempre retorna string de erro** em vez de funcionar.

> Observação: os handlers dependem do `ctx` construído por `_build_handler_context`; o vínculo
> exato de cada handler com a instância de módulo carregada pelo `ModuleManager`
> `> NÃO FOI POSSÍVEL CONFIRMAR 100% por inspeção estática`.

---

## 12. Analisadores de Intenção

### 12.1 `core/intent.py`
- `Intent` (dataclass): `module`, `action`, `params`, `confidence`; `IntentAnalyzer` com
  `register_modules` e triggers (ex.: `"lembrete"`, `"agendar"`, `"pomodoro"`).
- Contém typo de texto: `"digitção por voz"` (falta espaço) na descrição do módulo dictação.
- **Não está ligado ao loop**: `Aris.__init__` cria `self._intent = IntentAnalyzer()`, mas o
  objeto **nunca é usado** — o dispatch real usa `AdvancedInterpreter` + `CommandRegistry`.

### 12.2 `core/advanced_interpreter.py`
- `Intent` próprio (com `order`, `conditional`, `context`), `ConversationContext` (deque,
  `maxlen=20`), `_register_defaults` com módulos: settings, desktop (apps como discord/spotify/
  youtube/chrome/firefox), scheduler, safety, etc.
- Palavras "jogo/jogar/minecraft/steam" e "discord/chat/conversa" são apenas **triggers de texto**
  → map**eados** para `desktop/open_app` (ver Seção 30, discord/minecraft).
- `update_context` contém a palavra `"música"` **duplicada** (typo de dados).

---

## 13. Provedores de IA (`core/multi_provider.py`)

- `AIProvider` + `MultiProviderChat`:
  - **Primário**: Groq `llama-3.3-70b-versatile` (confirmado no log).
  - **Fallback automático**: Gemini `gemini-2.0-flash` (confirmado no log).
- Cada provider registrado com seu **rate limiter** (Seção 14).
- Modelo do chat central configurável via `ARIS_CHAT_MODEL`.

---

## 14. Rate Limiting e Quotas (`core/rate_limiter.py`)

- Implementação de **janela deslizante** com **bloqueio de 10 s** ao estourar.
- Escalas documentadas (PROMPT_CLAUDE.md) e integradas em `multi_provider.py` e
  `hyper_search.py`:
  - Groq: 30 req/min
  - SerpAPI: 5 req/min
  - Gemini: 60 req/min
  - Ollama: 20 req/min
- `> NÃO FOI POSSÍVEL CONFIRMAR` se os limites são atingidos em uso real (sem dados de execução).

---

## 15. Sistema de Memória (`core/memory.py`, `memory_models.py`)

- `MemoryManager`: índice em `data/memory/Index/memory_index.json`; metadados em
  `data/memory/Index`; **14 categorias** (`MemoryCategory`): Profile, Knowledge, Projects,
  Conversations, Devices, Automations, Plugins, Config, Cache, Logs, Temporary, Backups,
  Archive, Index.
- `data/memory/` contém hoje as 14 subpastas (criadas no boot).
- `MemoryEntry` (dataclass): `importance` 1–10 (`Importance`), `priority` (Crítica/Alta/Média/
  Baixa), tags, source, `is_permanente`, `is_stale` (90 dias sem acesso e importância < 5).
- Serialização JSON com `ensure_ascii=False`.
- Estado atual: **índice não existe** — o log registra `Nenhum índice encontrado. Criando novo.`
  a cada boot; nenhuma memória persistida foi observada.

---

## 16. Organizador de Memória (`core/memory_organizer.py`, 254 L)

- `MemoryOrganizer.run_maintenance()` compõe 7 operações:
  `clean_cache`, `clean_temporary` (7 dias), `archive_old_logs` (30 dias),
  `compact_old_backups` (mantém 10), `remove_duplicates` (por conteúdo), `archive_stale_memories`
  (`is_stale`), `verify_integrity` (órfãs).
- `get_disk_info()` via `shutil.disk_usage`.
- **IMPORTANTE**: o organizador é **instanciado** em `aris.py:100`, mas `run_maintenance()`
  **nunca é chamado** em nenhum lugar do código → **rotina de manutenção é código morto**.

---

## 17. Gerenciador de Módulos (`core/module_manager.py`, 191 L)

Mecanismo:
- Escaneia `modules/*.py` (ignora `_<nome>`), **executa o arquivo** via
  `spec_from_file_location`, e instancia a classe cujo nome **PascalCase do nome do arquivo**
  (`"".join(word.capitalize() for word in name.split("_"))`) sem argumentos.
- **Fallback**: se não houver classe com esse nome, procura classes com método `execute`.
- Erros de instanciação são logados (`Erro ao instanciar ...`); ausência de classe compatível
  retorna `None` **silenciosamente**.
- Plugins (`plugins/*.py`) são carregados e podem auto-registrar intents via
  `register(registry)`.

**RECONCILIAÇÃO com o log real** (`Total carregado: 10 (0 plugins)`):

| Tipo | Módulos | Motivo |
|---|---|---|
| Carregados (10) | `auto_redaction`, `browser_automation`, `context_detector`, `desktop_awareness`, `desktop_tools`, `dictation_mode`, `entertainment`, `morning_digest`, `skills_system`, `turbo_mode` | classe PascalCase casa com nome do arquivo |
| Falha logada (3) | `chat`, `knowledge_graph`, `scheduler` | construtor exige `api_key` / `data_dir` |
| Falha silenciosa (4) | `esp32_hardware`, `notifications`, `safety`, `multi_agent` | classe não casa com PascalCase do arquivo **e** nenhuma classe tem `execute` |

Detalhes das falhas silenciosas (a classe real difere do nome esperado):
- `esp32_hardware.py` → esperada `Esp32Hardware`, real **`HardwareManager`**.
- `notifications.py` → esperada `Notifications`, real **`NotificationManager`**.
- `safety.py` → esperada `Safety`, real **`SafetyManager`**.
- `multi_agent.py` → esperada `MultiAgent`, real **`MultiAgentSystem`** (sem `execute`).

> **Consequência de arquitetura**: os subsistemas críticos (`chat`, `knowledge_graph`,
> `scheduler`, `safety`, `hardware`) **não vêm do ModuleManager** — são instanciados
> **diretamente** no `__init__` de `Aris` e entregues via `_build_handler_context`. O
> `ModuleManager` é, na prática, **decorativo** para o runtime (sua contagem "10" não reflete a
> capacidade real do sistema). Este é um insight-chave para o Neural Core.

---

## 18. Inventário de Módulos (`modules/`, 17 arquivos)

| Arquivo | Classe principal | Construtor | Carga via ModuleManager |
|---|---|---|---|
| `auto_redaction.py` | `AutoRedaction` | no-arg | sim |
| `browser_automation.py` | `BrowserAutomation` | `data_dir=None` | sim |
| `context_detector.py` | `ContextDetector` | no-arg | sim |
| `desktop_awareness.py` | `DesktopAwareness` | `data_dir=None` | sim |
| `desktop_tools.py` | `DesktopTools` | no-arg | sim |
| `dictation_mode.py` | `DictationMode` | no-arg | sim |
| `entertainment.py` | `Entertainment` | `data_dir=None` | sim |
| `morning_digest.py` | `MorningDigest` | `data_dir=None` | sim |
| `skills_system.py` | `SkillsSystem` | `data_dir=None` | sim |
| `turbo_mode.py` | `TurboMode` | `logger=None` | sim |
| `chat.py` | `Chat` | `api_key` (obrigatório) | **não** (falha logada) |
| `knowledge_graph.py` | `KnowledgeGraph` | `data_dir` (obrigatório) | **não** (falha logada) |
| `scheduler.py` | `Scheduler` | `data_dir` (obrigatório) | **não** (falha logada) |
| `esp32_hardware.py` | `HardwareManager` | `config` (obrigatório) | **não** (silenciosa) |
| `notifications.py` | `NotificationManager` | `data_dir=None` | **não** (silenciosa) |
| `safety.py` | `SafetyManager` | `data_dir=None` | **não** (silenciosa) |
| `multi_agent.py` | `MultiAgentSystem` | `data_dir=None` | **não** (silenciosa) |

Detalhes de implementação relevantes:
- `scheduler`: `TaskPriority` (1–4), `TaskStatus`, `ScheduledTask`, `PomodoroTimer` com thread.
- `esp32_hardware`: `SystemState` (11 estados), `LEDColor` (`to_dict`/`from_hex`),
  `STATE_COLORS`, `BUTTON_ACTIONS`, callback de botão.
- `safety`: `SafetyLevel` (1–4), `SafetyAction`, listas SAFE/CAUTION/DANGER/CRITICAL.
- `desktop_tools`: usa `pyautogui` (FAILSAFE ativo, `PAUSE=0.1`) + `subprocess`.
- `auto_redaction`: 13 padrões regex de PII.

---

## 19. Sistema de Plugins (`plugins/`, 2 arquivos)

- **`calculator.py`** (39 L): registra intent `calc` e **substitui o handler genérico**
  (`registry._intent_handlers["calc"] = handle_calc`). Sanitização por whitelist de caracteres
  `0123456789+-*/.().% ` + `eval` com `# noqa: S307`. Funciona, mas o padrão de
  monkeypatch no dict interno é **frágil por design**.
- **`esp32_deck.py`** (~120 L): registra intent `hardware` com ações
  `status/connect/disconnect/state/led_left/led_right` delegando ao `HardwareManager`.
- O log confirma: **0 plugins carregados** nos boots atuais — contradição aparente com o plugin
  `calculator.py` presente. Explicação possível:
  `> NÃO FOI POSSÍVEL CONFIRMAR por inspeção estática` — verificado que o carregamento de
  plugins exige `register(registry)` em `plugins/`, e o cálculo de plugins conta apenas os que
  **instanciam**; `calculator.py` registra handlers mas a classe `Calculator` não deve ser
  instanciável (não há classe com nome PascalCase `Calculator` nem `execute`) → 0 plugins
  carregados é **plausível** e consistente.

---

## 20. Integração ESP32

### 20.1 Firmware — `firmware/esp32_aris/esp32_aris.ino`
- Plataforma `espressif32`/`esp32dev` (`platformio.ini`); ArduinoJson + WebSocket.
- Conecta como **WebSocket client** ao IP do PC na porta **8766**.
- **ACHADO DE SEGURANÇA**: o arquivo contém **credenciais WiFi (SSID/senha) em texto claro** e
  o IP do PC, e **está versionado no repositório** (`git ls-files` confirma). Os valores não
  são reproduzidos aqui por política da auditoria. (**Seção 30**.)
- Protocolo de mensagens JSON com o nó `tipo`: `heartbeat`, `button`, `state`, `led`.

### 20.2 Módulo Python (`modules/esp32_hardware.py`)
- `HardwareManager(config, logger)`:
  - WebSocket client para `ws://PC:8766`; `_heartbeat_loop` com intervalo configurável.
  - Sem `websockets` instalado no venv, `start()` cai em **placeholder/simulação**, e o log
    registra apenas linhas sintéticas: `[HARDWARE] LED LEFT ? RGB(0,50,100)`,
    `Estado: initializing ? idle`.
  - Botões: `single_click → voice_toggle`, `double_click → stop_speaking`,
    `long_press → turbo_mode`.
  - Estado atual em execução: **sem conexão real** (`websockets` ausente + usuário não testou
    hardware), `HARDWARE_SIMULATION` configurável via env.
- `data/screenshots/` existe (usada pelo desktop awareness).

---

## 21. Voz e STT

- **`utils/voice.py`** — `Voice` (SAPI via `win32com`/`pyttsx3`), com `enabled`,
  `rate`, `volume`. `utils/__init__.py` reexporta `Voice`.
- **`utils/voice_hybrid.py`** — `HybridVoice`: edge-tts (melhor qualidade) → pyttsx3 → SAPI;
  `enabled` flag. Loop de eventos próprio (`asyncio`) interno para edge-tts.
- **Uso real confirmado** em `core/aris.py`:
  - linha 273 (`process_input`): `voice = self._hybrid_voice if self._hybrid_voice.enabled else self._voice`
    → respostas são faladas quando a voz híbrida está ativa.
  - linha 415–427: toggle mudo (`speak` na verdade).
- **STT** (`SpeechRecognition`): reconhecimento ativo documentado para dictação
  (`dictation_mode`) e voz; integração completa com o loop
  `> NÃO FOI POSSÍVEL CONFIRMAR` sem execução (não há mic/threads de escuta contínua no aris.py).

---

## 22. Interface de Usuário

- Terminal ANSI: `utils/terminal.py` com `ArisUI`/estilos e `os.system("cls"/"clear")`
  (limpeza de tela).
- Prompt: `> ` (padrão) configuração via `ARIS_PROMPT`.
- Entrada por `input()`; comandos digitados vão para o `AdvancedInterpreter` (LLM) que devolve
  intents JSON; fallbacks de keyword para intents básicos.
- **`>` GUI**: `> NÃO IMPLEMENTADO`. Greps por `tkinter|flask|fastapi|gradio|PyQt|pyside`:
  **nenhuma ocorrência** no código Python. Não há HUD gráfico nem servidor web.
- Comando `help` no boot lista módulos/tarefas (linhas 444/487/521 do aris.py).

---

## 23. Scheduler e Tarefas

- `Scheduler(data_dir)`: persistência em `data/scheduled_tasks.json` (hoje `[]` — vazio).
- **Integrado de verdade ao boot**: `aris.py:267` `start_checker(callback=self._on_task_due)`;
  intent `scheduler` (reminder/task/pomodoro) em `handlers.py:100–126`; tarefas pendentes
  expostas no contexto (`tasks_report`) e no help/status.
- `PomodoroTimer` roda em thread própria.
- Threads existentes hoje: (1) `ThreadPoolExecutor(max_workers=1)` do LLM em `aris.py:287`,
  (2) thread de checker do scheduler, (3) thread do pomodoro, (4) heartbeat/híbrid voice em
  loops próprios. **Não há `asyncio` no núcleo** (APENAS interno do edge-tts).

---

## 24. Safety e Permissões

- `SafetyManager` (`modules/safety.py`): `SafetyLevel` 1–4, `SafetyAction`, listas
  SAFE/CAUTION/DANGER/CRITICAL; audit ref. `data/safety_audit.json`
  (`> NÃO FOI POSSÍVEL CONFIRMAR` a existência atual do arquivo — não listado no `data/`).
- `CommandRegistry`: `_safety_levels` + `_pending_confirmation` (por token) para ações
  destrutivas.
- **Problema estrutural**: `SafetyManager` **não carrega via ModuleManager** (falha silenciosa)
  e **não está no ctx dos handlers** (o `ctx` tem `safety` direto do `__init__` — portanto
  acessível); a auditoria não observa **evidência de gate de segurança de fato aplicado no
  pipeline** de intents além da construção do objeto.
  `> NÃO FOI POSSÍVEL CONFIRMAR` se há enforcement real sem execução.
- `config/settings.py` expõe `SAFETY_PASSWORD` (ver bug da Seção 11).

---

## 25. Busca e Clima (subsistemas de internet)

- **`search/hyper_search.py` — `HyperSearch`**: busca multi-fonte com fallback; usa
  rate limiter (SerpAPI 5/min); método `search_and_summarize`.
- **`weather/hyper_weather.py` — `HyperWeather`**: agregador de clima com
  `format_report(...)`.
- Ambos instanciados diretamente em `Aris` e expostos no `ctx` (`ctx["search"]`,
  `ctx["weather"]`).
- Comportamento offline/limite de chamadas sem rede
  `> NÃO FOI POSSÍVEL CONFIRMAR`.

---

## 26. Análise de Sistema (`system/analyzer.py`)

- `SystemAnalyzer`: coleta CPU, memória, disco (via `psutil`) para o intent `sys`
  (`handle_sys` → `ctx["analyzer"].run()`).
- Usado também no status/boot.

---

## 27. Estado dos Dados (`data/`)

| Caminho | Estado |
|---|---|
| `data/memory/` | 14 subpastas criadas no boot; **nenhum índice** (`memory_index.json` ausente) |
| `data/skills.json` | ~246 linhas, definições de skills; **typo**: `"O que émachine learning?"` (espaço faltando) |
| `data/scheduled_tasks.json` | `[]` (vazio) |
| `data/screenshots/` | presente (suporte do desktop awareness) |
| `data/safety_audit.json` | não listado no diretório (`> NÃO FOI POSSÍVEL CONFIRMAR`) |

> Ausências relevantes: `chat history`, `knowledge_graph.json`, `notifications.json`,
> `morning_digest.json`, scores de jogos — módulos não persistiram nada ainda (só criam arquivos
> em uso).

---

## 28. Logs (`logs/aris.log`, hoje 63 linhas)

4 boots reais em **12/09/2026 (16:08–16:27)** documentam:

- Suite de boot correta: memória criada (`data/memory`), index novo, providers Groq + Gemini
  inicializados.
- **Erros repetidos em TODOS os boots**:
  1. `Erro ao instanciar Chat: Chat.__init__() missing 1 required positional argument: 'api_key'`
  2. `Erro ao instanciar KnowledgeGraph: ... missing 1 ... 'data_dir'`
  3. `Erro ao instanciar Scheduler: ... missing 1 ... 'data_dir'`
  - Seguidos de `Total carregado: 10 (0 plugins)`.
- `Hardware: websockets não instalado` → placeholder (sem ESP32 real).
- `[HARDWARE] LED LEFT ? RGB(0,50,100)` etc.: linhas **sintéticas** de simulação.
- **Importante**: estes erros são **atuais e reprodutíveis** (não são de build antigo); o
  sistema inicia mesmo assim porque os subsistemas críticos são instanciados diretamente (Seção 17).

---

## 29. Discrepâncias de Documentação

| Fonte | ALEGA | REALIDADE |
|---|---|---|
| `README.md` | `.env.example` existe | `> NÃO IDENTIFICADO NO PROJETO` (só há `.env`) |
| `README.md` | modules `help.py`, `clear.py`, `status.py`, `version.py`, `exit.py` | **não existem**; módulos reais = Seção 18 |
| `README.md` | tabela de comandos `help/clear/status/version/exit` | representação simplificada; runtime = intents (Seção 11) |
| `README.md` | env vars mínimas (3) | `.env` tem 13 variáveis (Seção 7) |
| `README.md` | "Adicionando módulos: classe PascalCase + `execute()`" | real: carrega por PascalCase do nome do arquivo e fallback `execute`; 7 módulos não carregam hoje (Seção 18) |
| `requirements.txt` vs `pyproject.toml` | — | requirements completo; pyproject mínimo/depasado |
| `PROMPT_MESTRE.md` | `core/aris.py` tem **733 linhas** | real: **543 linhas** |
| `PROMPT_MESTRE.md` | caminho de projeto `C:\Users\Administrator\Documents\ARIS` | real: `C:\Users\Administrator\Documents\Default Project\ARIS` |
| `PROMPT_CLAUDE.md` | registry/plugin/safety/rate-limiter | **confirmado** no código |
| `MELHORIAS.txt` | módulos não integrados ao registry; god class em aris.py; registry só aceita callable sem args; MEMORY_ROOT hardcoded; modelo fixo | **parcialmente corrigido**: registry ganhou intents+ctx; resto permanece (ver Seção 31) |
| Ref. "jarvis" em `PROMPT_MESTRE.md` | — | intencional (repos de referência) |

---

## 30. Achados de Segurança

1. **CRÍTICO — Credenciais WiFi em texto claro no firmware versionado**:
   `firmware/esp32_aris/esp32_aris.ino` contém SSID/senha e o IP do PC, e o arquivo está
   **trackeado pelo git** (commit inicial incluído). Mesmo que o repo seja privado, segredo em
   texto claro em histórico é risco. **Tratar**: rotação de credenciais + mover para
   `secrets`/`provisionamento` fora do versionamento.
2. **MÉDIO — `desktop_tools.py:211`**: `subprocess.Popen(["start", app_name], shell=True)` —
   nome de app vem de intent (potencialmente influenciado por LLM). A lista de apps conhecidos
   no `advanced_interpreter` mitiga, mas `shell=True` + entrada externa é vetor de injeção.
3. **MÉDIO — `plugins/calculator.py:25`**: `eval()` com whitelist de caracteres
   `0123456789+-*/.().% ` — aceitável para matemática, mas `eval` em plugin é superfície de
   risco se a expressão vier de fonte externa não sanitizada.
4. **MÉDIO — `.env` não versionado (bom)** mas `logs/` e `data/*.json` também são ignoradas;
   `firmware/` **não** está no `.gitignore`.
5. **BAIXO — `terminal.py:51`**: `os.system("cls"/"clear")` (limpeza de tela, cosmético).
6. **BAIXO — delegação de segurança**: enforcement de safety em execução não pôde ser
   confirmado (Seção 24).

---

## 31. Riscos e Fragilidades

- **Fragilidade nº 1 — envio de dependências por casamento de nome**: 7 de 17 módulos não
  carregam; mapear por `cls()` sem args inviabiliza DI.
- **Fragilidade nº 2 — god class**: `core/aris.py` concentra bootstrap de ~20 dependências.
- **Fragilidade nº 3 — handler ctx acoplado a instâncias diretas** vs ModuleManager paralelo:
  dois caminhos de injeção diferentes para o mesmo domínio.
- **Fragilidade nº 4 — `eval`/`subprocess` com dados do LLM** (Seção 30).
- **Fragilidade nº 5 — `pyproject.toml` e `README.md` mentem** sobre dependências/nome de
  módulos/comandos (risco para onboarding do Neural Core).
- **Fragilidade nº 6 — sem testes executáveis no CI**: `tests/test_esp32.py` requer `pytest` e
  não cobre `core/`.
- **Fragilidade nº 7 — `websockets` ausente do venv**: ESP32 real não conecta hoje.
- **Fragilidade nº 8 — sem persistência efetiva**: memória e tarefas nunca gravados em uso real
  (índice recriado a cada boot).
- **Fragilidade nº 9 — voz/STT não end-to-end verificável** sem hardware/mic.

---

## 32. Débito Técnico e Código Morto

| Item | Local | Situação |
|---|---|---|
| `_execute_intent_legacy` | `core/aris.py` | **morto** (pass) |
| `_get_dynamic_prompt` | `core/aris.py` | **morto** (nunca chamado) |
| `IntentAnalyzer` / `intent.py` | `core/aris.py:114` | **morto** (instanciado, nunca usado) |
| `MemoryOrganizer.run_maintenance` | `aris.py:100` | **morto** (nunca chamado) |
| `security/`, `analytics/`, `automation/` | raiz | pacotes vazios |
| Fallback `dir()` do ModuleManager | `module_manager.py:161` | só mascara a ausência de convenção |
| Monkeypatch `_intent_handlers["calc"]` | `plugins/calculator.py:39` | frágil (meio-interno) |
| Trigger meia-boca p/ discord/minecraft | `advanced_interpreter.py:182,188` | apenas map_texto → `desktop/open_app` (`> NÃO IMPLEMENTADO`) |

---

## 33. Qualidade de Código e Erros Textuais

- Typos de dados: `"O que émachine learning?"` (`data/skills.json`); `"digitção por voz"`
  (`core/intent.py`); `"música"` duplicado (`core/advanced_interpreter.py`).
- Erro real de atributo: `SAFETY_LEVEL` inexistente em `settings.Safety` → intent `config`
  sempre falha (Seção 11).
- Convenções inconsistentes de nome de classe vs arquivo (raiz da falha de carga, Seção 18).
- Docstrings/idioma: pt-BR consistente; organização geral razoável por responsabilidade.

---

## 34. Testes

- Único arquivo de teste: `tests/test_esp32.py` (230 L, pytest).
- Cobertura: `ESP32Config`, `LEDColor`, `SystemState`/`STATE_COLORS`, `HardwareManager` em
  **modo simulação** (sem hardware), callbacks de botão, mensagens JSON, no-crash sem ESP32.
- **Não cobre**: `core/`, `modules/` em geral, registry, handlers, memória, multi-provider.
- **Não roda em pipeline CI**; pytest não é listado no `pyproject.toml`.
- `> NÃO FOI POSSÍVEL CONFIRMAR` que a suíte passa no venv atual.

---

## 35. Recomendações para o Projeto Neural Core

1. **Substituir o casamento por nome/`cls()`** por **injeção de dependência explícita**
   (construtores com deps tipadas) — causa raiz de 55%+ das falhas de carga.
2. **Unificar o caminho de instâncias**: uma única fábrica de serviços (ex.: container DI)
   alimentando handlers via contexto tipado, em vez de `ModuleManager` paralelo +
   `_build_handler_context`.
3. **Enforce de segurança no pipeline** de intents (gate central antes de executar ações
   destrutivas) usando `SafetyManager`.
4. **Persistir de verdade**: inicializar índice/memória/tarefas no boot e chamar
   `MemoryOrganizer.run_maintenance` agendado.
5. **Remover segredos do firmware** e mover credenciais para provisioning/`secrets` gitignorados.
6. **Mover de `eval`/`subprocess(shell=True)`** para whitelist forte + `subprocess.run` sem
   shell (ou AST para `calc`).
7. **Conectar de fato**: instalar `websockets` + testar ESP32 real; senão remover placeholder.
8. **Alinhar docs**: regenerar `README.md` (módulos/comandos reais) e corrigir
   `PROMPT_MESTRE.md` (543 L, caminho atual); consolidar `requirements.txt` e `pyproject.toml`.
9. **Eliminar código morto**: `_execute_intent_legacy`, `_get_dynamic_prompt`, `IntentAnalyzer`
   órfão.
10. **Base de testes ampliada** + CI: registry/handlers/memória com pytest, antes de evoluir.
11. **GUI/API**: decidir explicitamente (`> NÃO IMPLEMENTADO` hoje); se desejado, superfície
    REST/WebSocket separada do loop de terminal.
12. **Observabilidade**: métricas por rate-limiter/LLM latência/token para dimensionar o Neural Core.

---

## 36. Conclusão

O A.R.I.S. é um **protótipo maduro de terminal** (registro amplo de intents, multi-provider com
fallback, rate limiting, voz híbrida, memória e integração ESP32 planejada), mas com **três
fragilidades estruturais**: (1) carregamento de módulos por convenção de nome que falha em 7/17
módulos; (2) persistência e manutenção de memória **não executadas**; (3) documentação fora de
sincronia com o código. O ponto mais valioso para o Neural Core é o **padrão de dispatch por
intents com contexto de dependências** e o **multi-provider com rate limiting**, que podem ser
reaproveitados como base sólida; o padrão de bootstrap manual (god class) e o acoplamento
nome→instância devem ser **redesenhados** no novo projeto, não copiados.

> Auditoria concluída em 12/09/2026 — somente-leitura, sem alterações no repositório.
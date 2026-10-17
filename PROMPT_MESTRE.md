# A.R.I.S. — PROMPT-MESTRE (Documento de Contexto Completo)
# Versão: 1.0.0 | Data: 07/08/2026
# Uso: Cole este documento inteiro em uma segunda IA para gerar sugestões de evolução.

---

## PARTE 1 — VISÃO GERAL DO PROJETO

**Nome:** A.R.I.S. — Assistente de Raciocínio e Integração de Sistemas
**Localização:** `C:\Users\Administrator\Documents\ARIS`
**Plataforma:** Windows 10/11, Python 3.12
**Tipo:** Assistente de IA via terminal com controle total do PC
**Versão:** 1.0.0
**Linguagem primária:** Português do Brasil (PT-BR)
**Repositório de referência:** `aris-nexus` (anonimatozin/jarvis-nexus v24.0) — clonado localmente mas o projeto é só "ARIS", sem "NEXUS"

**Objetivo:** Assistente pessoal via terminal que controla o PC por voz/texto, gerencia tarefas, pesquisa, automação, e se auto-evolui.

---

## PARTE 2 — ARQUITETURA ATUAL

```
ARIS/
├── main.py                    # Entry point
├── requirements.txt           # Dependências
├── .env                       # Chaves de API (GROQ, OPENWEATHER, WEATHERAPI, SERPAPI)
├── core/                      # Núcleo do sistema
│   ├── aris.py              # Orquestrador principal (733 linhas)
│   ├── advanced_interpreter.py # NLU multi-comando
│   ├── multi_provider.py      # Fallback Groq → Gemini → Ollama
│   ├── intent.py              # Intent analyzer legado (fallback)
│   ├── memory.py              # CRUD de memória
│   ├── memory_models.py       # Modelos MemoryEntry, Priority
│   ├── memory_organizer.py    # Auto-limpeza de memória
│   ├── module_manager.py      # Loader dinâmico de módulos (DI)
│   ├── commands.py            # Registro de comandos
│   ├── services/              # Service Container + Event Bus
│   └── neural/                # NEURAL CORE (arquitetura cognitiva)
│       ├── core.py            # Orquestrador do pipeline
│       ├── events.py / event_bus.py
│       ├── state.py           # GlobalState (goal, falhas, eventos)
│       ├── memory/            # WorkingMemory + Episódica + Procedural
│       ├── attention/         # AttentionEngine (filtro de eventos)
│       ├── context/           # ContextEngine (monta contexto)
│       ├── reasoning/         # ReasoningRouter (determinístico/LLM)
│       ├── decision/          # DecisionEngine (risco)
│       ├── security/          # SecurityGate (allowlist de ações)
│       ├── actions/           # ActionEngine (execução via registry)
│       ├── feedback/          # FeedbackEngine (sucesso/falha)
│       ├── planning/          # Planner (planos multi-etapas)
│       └── learning/          # ExperienceStore (estatísticas)
├── modules/                   # Módulos de funcionalidade
│   ├── chat.py                # Chat via Groq com RAG de memória
│   ├── desktop_tools.py       # Mouse, teclado, mídia, janelas
│   ├── scheduler.py           # Lembretes + Pomodoro
│   ├── notifications.py       # Notificações Windows
│   ├── context_detector.py    # Detecção de atividade do usuário
│   ├── safety.py              # Segurança em 4 níveis
│   ├── entertainment.py       # Piadas, curiosidades, 20 perguntas
│   ├── turbo_mode.py          # Análise profunda de arquivos
│   ├── knowledge_graph.py     # Grafo de entidades/relações/fatos
│   ├── desktop_awareness.py   # Captura de tela + OCR
│   ├── auto_redaction.py      # Redação automática de dados sensíveis
│   ├── morning_digest.py      # Briefing diário matinal
│   ├── browser_automation.py  # Automação Playwright
│   ├── multi_agent.py         # Sistema de delegação de agentes
│   ├── skills_system.py       # Skills reutilizáveis
│   └── dictation_mode.py      # Ditado por voz (speech-to-text)
├── config/
│   ├── settings.py            # Dataclass de configuração
│   └── personality.py         # System prompt da personalidade
├── utils/
│   ├── terminal.py            # Terminal UI + ArisUI (ASCII art)
│   ├── voice.py               # TTS Windows SAPI
│   ├── voice_hybrid.py        # edge-tts + pyttsx3 + STT
│   └── logger.py              # Logger rotativo
├── system/
│   └── analyzer.py            # Monitor CPU/RAM/disk/rede
├── weather/
│   └── hyper_weather.py       # Clima multi-fonte
├── search/
│   └── hyper_search.py        # Busca SerpAPI
├── security/                  # (vazio, módulo futuro)
├── automation/                # (vazio, módulo futuro)
├── analytics/                 # (vazio, módulo futuro)
└── aris-nexus/              # Repositório de referência clonado
```

---

## PARTE 3 — DEPENDÊNCIAS (requirements.txt)

```
groq>=0.13.0
openai>=1.99.0
pyttsx3>=2.99
edge-tts>=6.1.12
SpeechRecognition>=3.10.4
openai-whisper>=20231117
requests>=2.31.0
beautifulsoup4>=4.12.0
psutil>=5.9.0
pyautogui>=0.9.54
pyperclip>=1.8.2
rich>=13.0.0
python-dotenv>=1.0.0
psutil>=5.9.0
screeninfo>=0.8.1
pygetwindow>=0.0.9
keyboard>=0.13.5
pynput>=1.7.6
selenium>=4.25.0
webdriver-manager>=4.0.2
pillow>=10.0.0
pytesseract>=0.3.10
playwright>=1.40.0
httpx>=0.27.0
python-dateutil>=2.8.2
pydantic>=2.0.0
aiohttp>=3.9.0
sounddevice>=0.4.6
soundfile>=0.12.1
numpy>=1.24.0
torch>=2.0.0
transformers>=4.35.0
tiktoken>=0.5.0
newspaper3k>=0.2.8
fake-useragent>=1.4.0
numpy>=1.24.0
```

**Observações:**
- Playwright + Chromium instalados (`playwright install chromium`)
- torch + transformers declarados mas NÃO são usados ativamente
- whisper declarado mas NÃO integrado no voice_hybrid.py

---

## PARTE 4 — CHAVES DE API (configuradas no .env)

| Chave             | Status    | Uso                              |
|-------------------|-----------|----------------------------------|
| GROQ_API_KEY      | Configurada | Chat primário (llama-3.3-70b)  |
| OPENWEATHER_API_KEY| Configurada | Clima (OpenWeather)            |
| WEATHERAPI_KEY    | Configurada | Clima (WeatherAPI backup)      |
| SERPAPI_KEY       | Configurada | Busca web (SerpAPI)            |
| GEMINI_API_KEY    | NÃO configurada | Fallback Ollama/Gemini (opcional) |
| OPENAI_API_KEY    | NÃO configurada | Whisper STT (opcional)        |

---

## PARTE 5 — MÓDULOS DETALHADOS

### 5.1 CORE (Núcleo)

#### `core/aris.py` — Orquestrador Principal (733 linhas)
- Inicializa 25+ módulos
- Loop principal: lê input → interpreta → executa → responde
- `_execute_intent()` é um monolito de ~400 linhas com TODOS os comandos hardcoded
- Gerencia estado: voice_mode, dictation_mode, turbo_mode, pomodoro
- Trata sinais (Ctrl+C), mensagens de boas-vindas, horário do dia
- Suporta: `--cli`, `--test` flags

#### `core/advanced_interpreter.py` — NLU Multi-Comando
- Interpreta comandos complexos como "pesquise X e salve em Y"
- Divide em sub-comandos: pesquisar → extrair → salvar
- Classifica: ações, alvos, parâmetros, dependências
- Fallback para intent.py se AdvancedInterpreter falhar

#### `core/multi_provider.py` — Multi-Provider LLM
- Fallback: Groq → Gemini (se configurado) → Ollama (local)
- Retry com exponential backoff
- Status de cada provider

#### `core/memory.py` + `memory_models.py` + `memory_organizer.py`
- CRUD completo: salvar, recuperar, listar, buscar, deletar
- Categorias: preferência, fato, contexto, tarefa, habilidade, segurança, decay
- Prioridades: CRITICAL, HIGH, MEDIUM, LOW, DECAY
- Organizador automático: limpa memórias antigas, consolida fatos

#### `core/module_manager.py`
- Auto-loader de módulos do diretório `modules/`
- Plugins directory para extensões

#### `core/commands.py`
- Registry centralizado de comandos registrados

#### `core/neural/` — NEURAL CORE (arquitetura cognitiva híbrida)
Pipeline de processamento por evento: atenção → working memory → contexto →
reasoning router → decisão → security gate → plano → ação → feedback →
memória episódica/procedural + learning. Regras:
- **Sem LLM em toda decisão**: um motor determinístico cobre padrões
  conhecidos (intents digitadas, monitoramento, clima); LLM é fallback (None
  se indisponível).
- **Sem reinforcement learning**: aprendizado é baseado em estatísticas
  simples de sucesso/falha (ExperienceStore) + memória episódica.
- **Segurança**: SecurityGate valida decisões contra allowlist de
  capacidades do registry (módulo/action); ações de risco alto exigem
  confirmação; nunca executa capacidades desconhecidas.
- Interligado ao `core/services` (ServiceContainer) e `EventBus`.

### 5.2 MÓDULOS

#### `modules/chat.py`
- Chat via Groq API (llama-3.3-70b-versatile)
- RAG simples: busca memória relevante e inclui no contexto
- Streaming de respostas
- Histórico de conversa (in-memory, não persistente)

#### `modules/desktop_tools.py`
- Mouse: mover, clicar, arrastar, scroll
- Teclado: digitar, pressionar combinações
- Mídia: play/pause/next/prev
- Janelas: listar, focar, minimizar, maximizar
- Captura de tela

#### `modules/scheduler.py`
- Lembretes com data/hora
- Pomodoro timer (25/5)
- Tarefas recorrentes
- Persistência em JSON

#### `modules/notifications.py`
- Notificações nativas Windows (win10toast)

#### `modules/context_detector.py`
- Detecta: working, gaming, idle, media
- Usa janela ativa + processos

#### `modules/safety.py`
- 4 níveis: low, medium, high, paranoid
- Validação de comandos antes de executar
- Logging de ações perigosas

#### `modules/entertainment.py`
- Piadas, curiosidades, 20 perguntas
- Músicas, calculadora

#### `modules/turbo_mode.py`
- Análise profunda de arquivos de código
- Leitura + contexto + sugestões

#### `modules/knowledge_graph.py` (NOVO)
- Entidades, relações, fatos
- Query por entidade, relação, ou facts
- Export para JSON
- Problema: não salva persistência automática

#### `modules/desktop_awareness.py` (NOVO)
- Captura de tela + OCR (pytesseract)
- Monitoramento de atividade
- Reconhecimento de texto na tela

#### `modules/auto_redaction.py` (NOVO)
- Redação de: CPF, email, telefone, cartão, IP, address, name, api_key
- 4 níveis de severidade
- Regex patterns

#### `modules/morning_digest.py` (NOVO)
- Briefing: hora, resumo memórias, tarefas pendentes, clima, dica
- Gera string formatada

#### `modules/browser_automation.py` (NOVO)
- Playwright: abrir, clicar, preencher, screenshot
- Problema: async não integrado no loop síncrono do aris.py

#### `modules/multi_agent.py` (NOVO)
- Agentes: researcher, coder, analyst, writer
- Task delegation
- Problema: não usa LLM real, é placeholder

#### `modules/skills_system.py` (NOVO)
- Skills reutilizáveis com parâmetros
- Auto-load de skills do diretório
- Nenhuma skill pré-criada

#### `modules/dictation_mode.py` (NOVO)
- Speech-to-text via Whisper ou SpeechRecognition
- Ditado → texto no clipboard
- Problema: requer microfone + configuração de áudio

### 5.3 UTILS

#### `utils/terminal.py`
- `Terminal`: cls, print_colorido, print_erro, print_sucesso, print_aviso, input_colorido
- `ArisUI`: banner ASCII art, prompt estilizado, indicadores de ação

#### `utils/voice.py`
- Windows SAPI TTS
- Rate, volume configuráveis
- Fallback se não disponível

#### `utils/voice_hybrid.py`
- edge-tts ( Alta qualidade, online)
- pyttsx3 (Offline fallback)
- SpeechRecognition (STT)
- Whisper STT (declarado mas não integrado)

#### `utils/logger.py`
- Logger rotativo com max_size_mb
- Arquivo + console

### 5.4 SYSTEM

#### `system/analyzer.py`
- CPU, RAM, disco, rede em tempo real
- `get_system_info()`, `get_quick_status()`

### 5.5 WEATHER

#### `weather/hyper_weather.py`
- Multi-fonte: OpenWeather → WeatherAPI → fallback
- Formatação bonita com emojis

### 5.6 SEARCH

#### `search/hyper_search.py`
- SerpAPI: web, news, images, videos
- Fallback httpx se SerpAPI falhar

### 5.7 CONFIG

#### `config/settings.py`
- Dataclass com todos os paths e configs
- `ensure_directories()` cria dirs necessários

#### `config/personality.py`
- System prompt detalhado para o LLM
- Define personalidade,limites, estilo de resposta

---

## PARTE 6 — COMANDOS SUPORTADOS (via terminal)

| Comando                                    | Módulo            |
|-------------------------------------------|-------------------|
| `chat [mensagem]`                         | chat.py           |
| `pesquisar [query]`                       | hyper_search.py   |
| `clima [cidade]`                          | hyper_weather.py  |
| `abrir [programa/url]`                    | desktop_tools.py  |
| `fechar [janela]`                         | desktop_tools.py  |
| `listar janelas`                          | desktop_tools.py  |
| `focar [janela]`                          | desktop_tools.py  |
| `screenshot`                              | desktop_tools.py  |
| `mouse [posição]`                         | desktop_tools.py  |
| `digitar [texto]`                         | desktop_tools.py  |
| `pressionar [tecla]`                      | desktop_tools.py  |
| `midia [play/pause/next/prev]`            | desktop_tools.py  |
| `lembrete [tempo] [ação]`                 | scheduler.py      |
| `pomodoro`                                | scheduler.py      |
| `notificar [mensagem]`                    | notifications.py  |
| `status`                                  | analyzer.py       |
| `sistema`                                 | analyzer.py       |
| `memoria [salvar/buscar/listar/deletar]`  | memory.py         |
| `turbo [arquivo]`                         | turbo_mode.py     |
| `conhecimento [entidade]`                 | knowledge_graph.py|
| `tela`                                    | desktop_awareness.py |
| `redigir [texto]`                         | auto_redaction.py |
| `resumo`                                  | morning_digest.py |
| `navegar [url]`                           | browser_automation.py |
| `agente [tarefa]`                         | multi_agent.py    |
| `skill [nome]`                            | skills_system.py  |
| `ditado`                                  | dictation_mode.py |
| `limpar memória`                          | memory.py         |
| `voz on/off`                              | aris.py         |
| `sair`                                    | aris.py         |

---

## PARTE 7 — PROBLEMAS E LIMITAÇÕES CONHECIDOS

### 7.1 Problemas Críticos
1. **`_execute_intent()` monolítico** — ~400 linhas, difícil de manter
2. **Sem wake word** — precisa digitar "aris" ou usar atalho
3. **Sem GUI** — apenas terminal (removido o HUD)
4. **Sem ESP32 integration** — hardware não integrado
5. **Sem streaming de respostas** — resposta aparece tudo de uma vez
6. **Sem histórico persistente** — conversa Some ao fechar
7. **Sem rate limiting** — pode estourar quota de API
8. **Sem background tasks** — tudo é síncrono e bloqueante
9. **Sem plugin system real** — module_manager existe mas não é usado
10. **browser_automation async não integrado** — Playwright é async, loop é sync

### 7.2 Problemas Médios
11. **knowledge_graph não persiste** — dados Somem ao reiniciar
12. **multi_agent é placeholder** — não usa LLM real
13. **skills_system sem skills** — sistema existe mas vazio
14. **dictation_mode requer configuração** — microfone + Whisper não testado
15. **auto_redaction não aplicado automaticamente** — só funciona se chamado manualmente
16. **morning_digest não tem trigger automático** — precisa chamar manualmente
17. **context_detector não afeta comportamento** — detecta mas não reage
18. **safety não bloqueia realmente** — apenas avisa

### 7.3 Problemas Menores
19. **requirements.txt com dependências não usadas** — torch, transformers, newspaper3k
20. **Import circular potencial** — memory_models importado em vários lugares
21. **Logger não estruturado** — sem correlação de requests
22. **~Cobertura de testes parcial** — pytest configurado (72 testes) mas módulos
    de voz/awareness/browser ainda sem cobertura
23. **Sem CI/CD** — nenhum pipeline

---

## PARTE 8 — COMPARAÇÃO COM REFERÊNCIAS (GitHub)

### Referência: anonimatozin/jarvis-nexus (v24.0)
O que a referência TEM e o ARIS atual NÃO tem:
- GUI Qt5 (HUD com orb animada, painéis, abas)
- Wake word detection (porrona/snowboy)
- Visão por computador (webcam + YOLO)
- Integração ESP32 (lâmpada BLE)
- Discord bot
- Dashboard web (Flask + auth)
- Output manager com múltiplos canais
- Boot/autostart no Windows
- Personality com greetings dinâmicos

### Referência: OpenClaw (~385k stars features)
- Code execution sandboxed
- Browser automation (mais completo)
- Multi-modal (imagem, áudio, vídeo)
- Plugin marketplace
- Self-improvement loop

### Referência: ethanplusai/jarvis
- Whisper STT integrado
- ElevenLabs TTS
- GPT-4 com function calling
- Múltiplos agentes especializados

### Referência: thevickypedia/Jarvis
- macOS integration
- Email automation
- WhatsApp integration
- Google Calendar

---

## PARTE 9 — O QUE NÃO FAZER (ANTI-PADRÕES)

1. **NÃO criar GUI complexa agora** — foque em terminal robusto
2. **NÃO adicionar mais dependências sem necessidade** — requirements.txt já está grande
3. **NÃO fazer refatoração massiva** — evoluir incrementalmente
4. **NÃO ignorar a base existente** — construir sobre o que já funciona
5. **NÃO adicionar features sem testar** — criar testes básicos primeiro
6. **NÃO copiar códigos de referência** — adaptar conceitos, não copiar
7. **NÃO quebrar compatibilidade** — manter comandos existentes funcionando
8. **NÃO usar APIs pagas sem fallback** — sempre ter plano B
9. **NÃO deixar módulos sem integração** — todo módulo novo deve ser chamado pelo aris.py
10. **NÃO esquecer do prompt-mestre** — toda evolução deve ser documentada

---

## PARTE 10 — ROADMAP SUGERIDO (Próximas Semanas)

### Fase 1: Consolidação (Semana 1-2)
- [ ] Refatorar `_execute_intent()` em handler functions separados
- [ ] Criar testes básicos com pytest
- [ ] Integrar browser_automation (async → sync bridge)
- [ ] Persistir knowledge_graph em JSON
- [ ] Ativar auto_redaction no pipeline de output
- [ ] Criar pelo menos 3 skills padrão

### Fase 2: Integração (Semana 3-4)
- [ ] Adicionar wake word (porrona ou similar)
- [ ] Integrar background tasks com threading
- [ ] Criar plugin system simples
- [ ] Integrar Whisper STT no voice_hybrid
- [ ] Adicionar streaming de respostas no chat
- [ ] Histórico persistente de conversas

### Fase 3: Hardware (Semana 5-6)
- [ ] Protocolo de comunicação ESP32 (WebSocket/HTTP)
- [ ] Integração com dispositivos IoT
- [ ] Monitoramento de hardware via ESP32
- [ ] Controle de periféricos (lâmpadas, tomadas)

### Fase 4: Inteligência (Semana 7-8)
- [ ] Context detector que AFETA comportamento
- [ ] Safety que REALMENTE bloqueia
- [ ] Multi-agent com LLM real
- [ ] Auto-redesign: Aris sugere melhorias para si mesmo
- [ ] Mood detector baseado em padrões de uso

---

## PARTE 11 — PERSONALIDADE E COMPORTAMENTO

**Nome:** A.R.I.S.
**Estilo:** Assistente inteligente, direto, útil, com personalidade levemente sarcástica
**Língua:** Português do Brasil (PT-BR)
**Tom:** Profissional mas amigável
**Limitações:** Não executa ações destrutivas sem confirmação, não expõe dados sensíveis

---

## PARTE 12 — CONTEXTO DO USUÁRIO

- **Hardware:** PC Windows, monitores duplos, ESP32 disponíveis
- **Servidor:** HP ProLiant mencionado na referência (possível uso futuro)
- **Nível técnico:** Avançado — quer controle total, não interfaces simplificadas
- **Preferência:** PT-BR, respostas diretas, sem enrolação
- **APIs disponíveis:** Groq, OpenWeather, WeatherAPI, SerpAPI
- **Objetivo:** Assistente pessoal completo que controla PC, pesquisa, gerencia tarefas, e se auto-evolui

---

## PARTE 13 — MODELO DE DADOS

### MemoryEntry
```python
@dataclass
class MemoryEntry:
    id: str
    category: MemoryCategory  # preference, fact, context, task, skill, safety, decay
    priority: Priority  # CRITICAL, HIGH, MEDIUM, LOW, DECAY
    key: str
    value: str
    context: str
    tags: List[str]
    created_at: datetime
    accessed_at: datetime
    access_count: int
    decay_rate: float
```

### KnowledgeGraph
```python
# Entidades: {entity_id: {name, type, properties, created_at}}
# Relações: {relation_id: {source, target, type, properties, weight}}
# Fatos: {fact_id: {subject, predicate, object, confidence, source, timestamp}}
```

---

## PARTE 14 — COMO USAR ESTE DOCUMENTO

Para a segunda IA:

1. **Analise** a arquitetura completa acima
2. **Identifique** gaps prioritários baseado no roadmap
3. **Sugira** implementações específicas com código
4. **Priorize** por impacto vs esforço
5. **NÃO** sugira features que já existem (ver inventário)
6. **Considere** o contexto Windows + Python 3.12
7. **Respeite** os anti-padrões listados
8. **Documente** cada sugestão com: o quê, por quê, como, onde

---

## PARTE 15 — ESTRUTURA DE DIRETÓRIOS DETALHADA

```
C:\Users\Administrator\Documents\ARIS\
├── main.py
├── requirements.txt
├── .env
├── .env.example
├── PROMPT_MESTRE.md
├── core/
│   ├── __init__.py
│   ├── aris.py
│   ├── advanced_interpreter.py
│   ├── multi_provider.py
│   ├── intent.py
│   ├── memory.py
│   ├── memory_models.py
│   ├── memory_organizer.py
│   ├── module_manager.py
│   └── commands.py
├── modules/
│   ├── __init__.py
│   ├── chat.py
│   ├── desktop_tools.py
│   ├── scheduler.py
│   ├── notifications.py
│   ├── context_detector.py
│   ├── safety.py
│   ├── entertainment.py
│   ├── turbo_mode.py
│   ├── knowledge_graph.py
│   ├── desktop_awareness.py
│   ├── auto_redaction.py
│   ├── morning_digest.py
│   ├── browser_automation.py
│   ├── multi_agent.py
│   ├── skills_system.py
│   └── dictation_mode.py
├── config/
│   ├── __init__.py
│   ├── settings.py
│   └── personality.py
├── utils/
│   ├── __init__.py
│   ├── terminal.py
│   ├── voice.py
│   ├── voice_hybrid.py
│   └── logger.py
├── system/
│   ├── __init__.py
│   └── analyzer.py
├── weather/
│   ├── __init__.py
│   └── hyper_weather.py
├── search/
│   ├── __init__.py
│   └── hyper_search.py
├── security/
│   └── __init__.py
├── automation/
│   └── __init__.py
├── analytics/
│   └── __init__.py
└── aris-nexus/ (referência, NÃO modificar)
```

---

## PARTE 16 — COMANDOS DE EXECUÇÃO

```bash
# Executar ARIS
python main.py

# Executar com flags
python main.py --cli
python main.py --test

# Instalar dependências
pip install -r requirements.txt

# Instalar Playwright
playwright install chromium

# Rodar testes (pytest, incluindo ESP32 e Neural Core)
python -m pytest tests/
```

---

## PARTE 17 — MÉTRICAS DE SUCESSO

1. **Redução de código** em `_execute_intent()` (meta: <100 linhas)
2. **Cobertura de testes** (meta: 50%+ dos módulos)
3. **Tempo de resposta** do LLM (meta: <3s para comandos simples)
4. **Uso de memória** (meta: <500MB RAM)
5. **Zero crashes** por 24h de uso contínuo
6. **Todos os módulos** integrados e funcionando
7. **Plugin system** capaz de carregar módulos externos
8. **Persistência** de memória e configurações entre sessões

---

## PARTE 18 — REFERÊNCIAS E INSPIRAÇÃO

| Projeto | Stars | Feature Principal |
|---------|-------|-------------------|
| OpenClaw | ~385k | Code execution, browser automation |
| anonimatozin/jarvis-nexus | - | GUI Qt5, ESP32, Discord bot |
| ethanplusai/jarvis | - | Whisper STT, multi-agent |
| thevickypedia/Jarvis | - | macOS, email, WhatsApp |
| fedcal | - | Jarvis com funções variadas |
| GauravSingh9356 | - | JarvisAI com ML |

---

*Documento gerado em 07/08/2026 por A.R.I.S. para uso como contexto de segunda IA.*
*Versão: 1.0.0*

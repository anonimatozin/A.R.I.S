# A.R.I.S.

[![testes](https://github.com/anonimatozin/A.R.I.S/actions/workflows/testes.yml/badge.svg)](https://github.com/anonimatozin/A.R.I.S/actions/workflows/testes.yml)

**A.R.I.S. — Assistente de Raciocínio e Integração de Sistemas**

Assistente virtual inspirado no conceito de A.R.I.S., construído com foco em modularidade, escalabilidade e facilidade de manutenção.

## Requisitos

- Python 3.12+
- Terminal / Console

## Estrutura do Projeto

```
Aris/
├── main.py                 # Ponto de entrada principal
├── requirements.txt        # Dependências do projeto (runtime + dev)
├── pyproject.toml          # Metadata + ferramentas (ruff, pytest, mypy)
├── .env.example            # Variáveis de ambiente (modelo)
├── config/                 # Sistema de configuração
│   ├── __init__.py
│   └── settings.py         # Classe Settings
├── core/                   # Componentes centrais
│   ├── __init__.py
│   ├── aris.py             # Classe principal Aris (orquestrador)
│   ├── module_manager.py   # Gerenciador de módulos (com DI)
│   ├── commands.py         # Sistema de comandos (Registry)
│   ├── memory.py           # Memória de longo prazo (JSON)
│   ├── services/           # Service Container + Event Bus
│   └── neural/             # Neural Core (arquitetura cognitiva)
│       ├── core.py         # Orquestrador do pipeline cognitivo
│       ├── events.py / event_bus.py
│       ├── state.py        # GlobalState
│       ├── memory/         # WorkingMemory + Episódica/Procedural
│       ├── attention/      # Filtro de atenção
│       ├── context/        # Construtor de contexto
│       ├── reasoning/      # Reasoning Router (determinístico/LLM)
│       ├── decision/       # Decisões com nível de risco
│       ├── security/       # Security Gate (allowlist)
│       ├── actions/        # Executor de ações
│       ├── feedback/       # Feedback e aprendizado
│       ├── planning/       # Planner multi-etapas
│       └── learning/       # Experience Store
├── modules/                # 17 módulos (chat, desktop, scheduler,
│                           # notifications, safety, ESP32, ...)
├── plugins/                # Plugins de terceiros
├── gateway/                # Gateway HTTP/WebSocket (código vivo;
│                           # scripts antigos em _manutencao_antiga/)
├── utils/                  # Utilitários (logger, terminal, voz)
├── firmware/esp32_aris/    # Firmware ESP32 (.ino + credentials.h)
├── logs/                   # Arquivos de log
├── data/                   # Dados persistentes
├── tests/                  # Testes pytest
└── assets/                 # Recursos estáticos
```

## Como Executar

```bash
python main.py                 # qualquer sistema (opções: --text-only, --mic-off, --no-tts)
./aris.sh                      # Linux: prepara PortAudio/X11 e usa venv-linux
```

No Windows também funciona `aris.bat` (CLI do agente) e `run_aris.bat`.

Para desenvolvimento:

```bash
pip install -r requirements.txt
python -m pytest tests/        # rodar a suíte de testes
python -m ruff check core/ modules/ plugins/ utils/ tests/ config/
```

## Comandos Disponíveis

Além do diálogo em linguagem natural, comandos diretos estão registrados
via `CommandRegistry` (listáveis com `help`): `chat`, `pesquisar`, `clima`,
`abrir`, `status`, `sistema`, `memoria`, `turbo`, `navegar`, `agente`,
`skill`, `ditado`, `sair`, e integração ESP32/hardware.

## Configuração

Copie o arquivo `.env.example` para `.env` e ajuste as variáveis conforme necessário:

```bash
cp .env.example .env
```

### Variáveis de Ambiente

| Variável                  | Descrição                          | Padrão   |
|---------------------------|------------------------------------|----------|
| `ARIS_LOG_LEVEL`        | Nível de log                       | `INFO`   |
| `ARIS_MAX_LOG_SIZE_MB`  | Tamanho máximo do log (MB)         | `10`     |
| `ARIS_PROMPT`           | Texto do prompt de entrada         | `> `     |

### Mini Deck (ESP32) — Wi-Fi por portal

O deck tem portal de configuração: sem rede salva, ele cria o ponto de
acesso `ARIS-Deck-XXXX` e serve a página `http://192.168.4.1` (SSID +
senha). As credenciais ficam no NVS do deck (nunca em log/Serial/JSON),
falha de conexão **não** as apaga e o botão segurado 10 s é o único jeito
de limpar. Detalhes, LEDs, flashing e recuperação:
[`firmware/esp32_aris/README.md`](firmware/esp32_aris/README.md).

O PC descobre o deck por **beacon UDP** (porta 8767) e recebe
`wifi_status` no WebSocket (porta 8766); o rosto reage em tempo real:
configurando (surprised) → conectando (thinking) → conectado (happy) →
erro (error). Com a ARIS ociosa ela também avisa por voz
(`ARIS_WIFI_FALA=0` desliga o aviso).

| Variável                | Descrição                                    | Padrão   |
|-------------------------|----------------------------------------------|----------|
| `ESP32_ENABLED`         | Liga o HardwareManager (server + beacon)     | `true`   |
| `ESP32_WS_HOST`         | Interface do servidor WebSocket              | `0.0.0.0`|
| `ESP32_WS_PORT`         | Porta do WebSocket do deck                   | `8766`   |
| `ESP32_BEACON_PORT`     | Porta do beacon UDP (0 = desliga)            | `8767`   |
| `ESP32_BEACON_INTERVAL` | Intervalo do beacon (s)                      | `3.0`    |
| `ARIS_WIFI_FALA`        | Aviso falado ao conectar/falhar (se ociosa)  | `1`      |

### Cenas de ambiente nos olhos (Spotify, fone, bateria, sono)

Com o aris_eyes rodando, os olhos também mostram o que está acontecendo
fora da conversa (`utils/eyes_ambient.py`, thread daemon própria):

| Cena | Quando aparece |
|---|---|
| `bateria` | bateria abaixo de 15% e descarregando |
| `conectado` | o Mini Deck conectou no Wi-Fi (transitória) |
| `comemorar` | o estado `success` é emitido (transitória) |
| `spotify` | música tocando no Spotify/MPRIS (+ `prop headphones on` se o fone estiver ligado) |
| `fone` | fone de ouvido ligado sem música |
| `dormir` | ARIS ociosa há 15+ min entre 22h e 6h |

A cor da capa da música vira o `accent` do rosto (baixada em thread,
timeout 3 s, só a cor — título/faixa nunca sai da máquina). Regra de
precedência: **os estados da ARIS (ouviu/pensando/falando/...) sempre
passam na frente** — a cena fica guardada e volta sozinha no idle.

| Variável                        | Descrição                                 | Padrão   |
|---------------------------------|-------------------------------------------|----------|
| `ARIS_EYES_AMBIENT`             | Kill-switch do módulo inteiro             | `1`      |
| `ARIS_EYES_AMBIENT_PLAYERS`     | Players MPRIS (separados por vírgula)     | `spotify`|
| `ARIS_EYES_AMBIENT_INTERVAL`    | Ciclo de reconciliação (s)                | `3`      |
| `ARIS_EYES_AMBIENT_IDLE_DORMIR` | Minutos de ociosidade p/ scene `dormir`   | `15`     |

Música usa `playerctl` (preferido) ou `busctl`/`dbus-send` (MPRIS direto);
fone usa `pactl` ou `wpctl` (PipeWire). Sem nenhum, o recurso desliga uma
vez no log. Detalhes e testes: `tests/test_eyes_ambient.py`.

### Voz — wake word e TTS

A wake word pode ser decidida ANTES de transcrever: com o motor dedicado
openWakeWord (offline, opcional), nada é transcrito antes de acordar —
fala alheia/TV nunca chega ao STT. Padrão continua o modo `transcript`
(compatível). Ao acordar toca um bip (`assets/sounds/wake.wav`), os olhos
vão para `listening` e só o comando é transcrito.

| Variável | Descrição | Padrão |
|---|---|---|
| `ARIS_WAKE_ENGINE` | `openwakeword` (dedicado) ou `transcript` | `transcript` |
| `ARIS_WAKE_MODEL` | Caminho do modelo .onnx treinado p/ a Áris | — |
| `ARIS_WAKE_THRESHOLD` | Limiar do motor dedicado (0..1) | `0.5` |
| `ARIS_TTS_CACHE` | Cache de frases curtas do TTS (`0` desliga) | `1` |

TTS: frases curtas ficam em cache (`~/.cache/aris/tts`) e respostas longas
são faladas FRASE A FRASE (primeira frase sai ~1-2 s antes). Detalhes,
treino do modelo e medições: [`docs/WAKE_WORD.md`](docs/WAKE_WORD.md).

## Arquitetura

O projeto segue uma arquitetura modular com separação clara de responsabilidades:

- **config/**: Configurações centralizadas carregadas de variáveis de ambiente.
- **core/**: Componentes centrais (Aris, ModuleManager, CommandRegistry).
- **core/neural/**: Neural Core — pipeline cognitivo híbrido (determinístico
  + LLM under demanda), com atenção, contexto, reasoning, decisão com risco,
  security gate, planner e feedback que alimenta a memória episódica/procedural.
- **core/services/**: Service Container (DI) + Event Bus.
- **modules/**: 17 módulos independentes (chat, desktop tools, scheduler,
  notificações, ESP32, ...), carregados via ModuleManager com injeção de
  dependência explícita.
- **plugins/**: Diretório reservado para plugins de terceiros.
- **utils/**: Utilitários reutilizáveis (logger, terminal, voz híbrida).
- **firmware/esp32_aris/**: Firmware do ESP32; credenciais WiFi ficam fora do
  versionamento (em `credentials.h`, gitignored).

### Adicionando Novos Módulos

1. Crie um arquivo Python em `modules/`.
2. Defina uma classe com o nome em PascalCase do arquivo.
3. Implemente o método `execute()`.
4. O módulo será carregado automaticamente na próxima inicialização
   (ou registrado via DI pelo ModuleManager).

### Adicionando Novos Comandos

Use o `CommandRegistry` para registrar comandos programaticamente:

```python
from core.commands import CommandRegistry

registry = CommandRegistry(logger)
registry.register(
    name="meu_comando",
    description="Descrição do comando",
    callback=minha_funcao,
)
```

## Sistema de Logs

Logs são gravados em `logs/aris.log` com rotação automática.

- Nível padrão: `INFO`
- Tamanho máximo: `10 MB`
- Arquivos de backup: `5`

## Licença

Projeto para fins educacionais e de desenvolvimento pessoal.

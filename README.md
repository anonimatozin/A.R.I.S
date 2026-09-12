# A.R.I.S.

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
├── utils/                  # Utilitários (logger, terminal, voz)
├── firmware/esp32_aris/    # Firmware ESP32 (.ino + credentials.h)
├── logs/                   # Arquivos de log
├── data/                   # Dados persistentes
├── tests/                  # Testes pytest
└── assets/                 # Recursos estáticos
```

## Como Executar

```bash
python main.py
```

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

# J.A.R.V.I.S.

**Just A Rather Very Intelligent System**

Assistente virtual inspirado no conceito de J.A.R.V.I.S., construído com foco em modularidade, escalabilidade e facilidade de manutenção.

## Requisitos

- Python 3.12+
- Terminal / Console

## Estrutura do Projeto

```
Jarvis/
├── main.py                 # Ponto de entrada principal
├── requirements.txt        # Dependências do projeto
├── .env.example            # Variáveis de ambiente (modelo)
├── config/                 # Sistema de configuração
│   ├── __init__.py
│   └── settings.py         # Classe Settings
├── core/                   # Componentes centrais
│   ├── __init__.py
│   ├── jarvis.py           # Classe principal Jarvis
│   ├── module_manager.py   # Gerenciador de módulos
│   └── commands.py         # Sistema de comandos
├── modules/                # Módulos do sistema
│   ├── __init__.py
│   ├── help.py             # Comando help
│   ├── clear.py            # Comando clear
│   ├── status.py           # Comando status
│   ├── version.py          # Comando version
│   └── exit.py             # Comando exit
├── plugins/                # Plugins de terceiros
├── utils/                  # Utilitários
│   ├── __init__.py
│   ├── logger.py           # Sistema de logs
│   └── terminal.py         # Utilitários de terminal
├── logs/                   # Arquivos de log
├── data/                   # Dados persistentes
├── tests/                  # Testes automatizados
└── assets/                 # Recursos estáticos
```

## Como Executar

```bash
python main.py
```

## Comandos Disponíveis

| Comando   | Descrição                          |
|-----------|------------------------------------|
| `help`    | Exibe a lista de comandos          |
| `clear`   | Limpa a tela do terminal           |
| `status`  | Exibe o status do sistema          |
| `version` | Exibe a versão do sistema          |
| `exit`    | Encerra o sistema                  |

## Configuração

Copie o arquivo `.env.example` para `.env` e ajuste as variáveis conforme necessário:

```bash
cp .env.example .env
```

### Variáveis de Ambiente

| Variável                  | Descrição                          | Padrão   |
|---------------------------|------------------------------------|----------|
| `JARVIS_LOG_LEVEL`        | Nível de log                       | `INFO`   |
| `JARVIS_MAX_LOG_SIZE_MB`  | Tamanho máximo do log (MB)         | `10`     |
| `JARVIS_PROMPT`           | Texto do prompt de entrada         | `> `     |

## Arquitetura

O projeto segue uma arquitetura modular com separação clara de responsabilidades:

- **config/**: Configurações centralizadas carregadas de variáveis de ambiente.
- **core/**: Componentes centrais (Jarvis, ModuleManager, CommandRegistry).
- **modules/**: Módulos independentes que estendem funcionalidades.
- **plugins/**: Diretório reservado para plugins de terceiros.
- **utils/**: Utilitários reutilizáveis (logger, terminal).

### Adicionando Novos Módulos

1. Crie um arquivo Python em `modules/`.
2. Defina uma classe com o nome em PascalCase do arquivo.
3. Implemente o método `execute()`.
4. O módulo será carregado automaticamente na próxima inicialização.

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

Logs são gravados em `logs/jarvis.log` com rotação automática.

- Nível padrão: `INFO`
- Tamanho máximo: `10 MB`
- Arquivos de backup: `5`

## Licença

Projeto para fins educacionais e de desenvolvimento pessoal.

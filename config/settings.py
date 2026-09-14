"""Sistema de configuração do A.R.I.S.

Carrega configurações de variáveis de ambiente e arquivos .env.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    """Configurações centrais do projeto.

    Attributes:
        PROJECT_NAME: Nome do projeto.
        VERSION: Versão atual do sistema.
        BASE_DIR: Diretório raiz do projeto.
        LOG_DIR: Diretório de logs.
        DATA_DIR: Diretório de dados.
        MODULES_DIR: Diretório de módulos.
        PLUGINS_DIR: Diretório de plugins.
        LOG_LEVEL: Nível de log (DEBUG, INFO, WARNING, ERROR).
        MAX_LOG_SIZE_MB: Tamanho máximo do arquivo de log em MB.
        PROMPT: Texto do prompt de entrada.
    """

    PROJECT_NAME: str = "A.R.I.S."
    VERSION: str = "1.0.0"

    BASE_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    LOG_DIR: Path = field(init=False)
    DATA_DIR: Path = field(init=False)
    MODULES_DIR: Path = field(init=False)
    PLUGINS_DIR: Path = field(init=False)

    LOG_LEVEL: str = field(init=False)
    MAX_LOG_SIZE_MB: int = field(init=False)
    PROMPT: str = field(init=False)
    VOICE_RATE: int = field(init=False)
    VOICE_VOLUME: int = field(init=False)
    GROQ_API_KEY: str = field(init=False)
    GEMINI_API_KEY: str = field(init=False)
    CHAT_MODEL: str = field(init=False)
    MEMORY_ROOT: Path = field(init=False)
    SCHEDULER_DIR: Path = field(init=False)
    SAFETY_PASSWORD: str = field(init=False)
    ESP32_ENABLED: bool = field(init=False)
    ESP32_WS_PORT: int = field(init=False)
    ESP32_SIMULATION: bool = field(init=False)

    # Saudação contextual
    GREETING_TIMEZONE: str = field(init=False)
    GREETING_LATITUDE: float = field(init=False)
    GREETING_LONGITUDE: float = field(init=False)
    GREETING_CITY: str = field(init=False)
    GREETING_COOLDOWN_HOURS: int = field(init=False)

    def __post_init__(self) -> None:
        """Inicializa valores derivados e carrega variáveis de ambiente."""
        object.__setattr__(self, "LOG_DIR", self.BASE_DIR / "logs")
        object.__setattr__(self, "DATA_DIR", self.BASE_DIR / "data")
        object.__setattr__(self, "MODULES_DIR", self.BASE_DIR / "modules")
        object.__setattr__(self, "PLUGINS_DIR", self.BASE_DIR / "plugins")

        object.__setattr__(self, "LOG_LEVEL", os.getenv("ARIS_LOG_LEVEL", "INFO"))
        object.__setattr__(self, "MAX_LOG_SIZE_MB", int(os.getenv("ARIS_MAX_LOG_SIZE_MB", "10")))
        object.__setattr__(self, "PROMPT", os.getenv("ARIS_PROMPT", "> "))
        object.__setattr__(self, "VOICE_RATE", int(os.getenv("ARIS_VOICE_RATE", "0")))
        object.__setattr__(self, "VOICE_VOLUME", int(os.getenv("ARIS_VOICE_VOLUME", "100")))
        object.__setattr__(self, "GROQ_API_KEY", os.getenv("GROQ_API_KEY", ""))
        object.__setattr__(self, "GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
        object.__setattr__(self, "CHAT_MODEL", os.getenv("ARIS_CHAT_MODEL", "openai/gpt-oss-120b"))
        object.__setattr__(self, "MEMORY_ROOT", Path(os.getenv("ARIS_MEMORY_ROOT", str(self.BASE_DIR / "data" / "memory"))))
        object.__setattr__(self, "SCHEDULER_DIR", self.DATA_DIR)
        object.__setattr__(self, "SAFETY_PASSWORD", os.getenv("ARIS_SAFETY_PASSWORD", ""))
        object.__setattr__(self, "ESP32_ENABLED", os.getenv("ESP32_ENABLED", "true").lower() == "true")
        object.__setattr__(self, "ESP32_WS_PORT", int(os.getenv("ESP32_WS_PORT", "8766")))
        object.__setattr__(self, "ESP32_SIMULATION", os.getenv("HARDWARE_SIMULATION", "false").lower() == "true")

        # Saudação contextual
        object.__setattr__(self, "GREETING_TIMEZONE", os.getenv("ARIS_GREETING_TIMEZONE", "America/Sao_Paulo"))
        object.__setattr__(self, "GREETING_LATITUDE", float(os.getenv("ARIS_GREETING_LATITUDE", "-23.55")))
        object.__setattr__(self, "GREETING_LONGITUDE", float(os.getenv("ARIS_GREETING_LONGITUDE", "-46.63")))
        object.__setattr__(self, "GREETING_CITY", os.getenv("ARIS_GREETING_CITY", "São Paulo"))
        object.__setattr__(self, "GREETING_COOLDOWN_HOURS", int(os.getenv("ARIS_GREETING_COOLDOWN_HOURS", "4")))

    def ensure_directories(self) -> None:
        """Cria os diretórios necessários se não existirem."""
        for directory in [self.LOG_DIR, self.DATA_DIR]:
            directory.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        return f"Settings(project={self.PROJECT_NAME!r}, version={self.VERSION!r})"

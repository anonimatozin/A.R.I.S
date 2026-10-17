"""Modelos de dados do sistema de memória do A.R.I.S.

Define as estruturas de dados para armazenamento de memórias.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum


class MemoryCategory(Enum):
    """Categorias de memória."""
    PROFILE = "Profile"
    KNOWLEDGE = "Knowledge"
    PROJECTS = "Projects"
    CONVERSATIONS = "Conversations"
    DEVICES = "Devices"
    AUTOMATIONS = "Automations"
    PLUGINS = "Plugins"
    CONFIG = "Config"
    CACHE = "Cache"
    LOGS = "Logs"
    TEMPORARY = "Temporary"
    BACKUPS = "Backups"
    ARCHIVE = "Archive"
    INDEX = "Index"


class Importance(Enum):
    """Níveis de importância (1-10)."""
    CRITICAL = 10    # Configurações do sistema, banco de memória
    HIGH = 8         # Plugins, scripts, histórico recente
    MEDIUM = 5       # Conversas úteis, logs recentes
    LOW = 2          # Cache
    MINIMAL = 1      # Arquivos temporários

    @classmethod
    def from_value(cls, value: int) -> "Importance":
        """Retorna o nível de importância a partir de um valor."""
        for member in cls:
            if member.value == value:
                return member
        if value >= 9:
            return cls.CRITICAL
        elif value >= 7:
            return cls.HIGH
        elif value >= 4:
            return cls.MEDIUM
        elif value >= 2:
            return cls.LOW
        return cls.MINIMAL


class Priority(Enum):
    """Níveis de prioridade."""
    CRITICAL = "Crítica"
    HIGH = "Alta"
    MEDIUM = "Média"
    LOW = "Baixa"


@dataclass
class MemoryEntry:
    """Entrada de memória.

    Attributes:
        id: Identificador único.
        title: Título da memória.
        content: Conteúdo da memória.
        category: Categoria da memória.
        importance: Nível de importância (1-10).
        priority: Prioridade da memória.
        tags: Tags para indexação.
        source: Origem da informação.
        file_path: Caminho do arquivo associado (se houver).
        created_at: Data de criação.
        last_accessed: Data da última utilização.
        access_count: Quantidade de acessos.
        is_permanente: Se a memória é permanente (não pode ser apagada).
    """
    id: str
    title: str
    content: str
    category: MemoryCategory
    importance: int = 5
    priority: Priority = Priority.MEDIUM
    tags: list[str] = field(default_factory=list)
    source: str = "conversation"
    scope: str = "shared"
    file_path: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now().isoformat())
    access_count: int = 0
    is_permanente: bool = False

    def to_dict(self) -> dict:
        """Converte para dicionário."""
        data = asdict(self)
        data["category"] = self.category.value
        data["priority"] = self.priority.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        """Cria uma instância a partir de um dicionário."""
        data = dict(data)
        data["category"] = MemoryCategory(data["category"])
        data["priority"] = Priority(data["priority"])
        data.setdefault("scope", "shared")
        data["scope"] = str(data["scope"] or "shared")
        return cls(**data)

    def to_json(self) -> str:
        """Converte para JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "MemoryEntry":
        """Cria uma instância a partir de JSON."""
        return cls.from_dict(json.loads(json_str))

    def access(self) -> None:
        """Registra um acesso à memória."""
        self.access_count += 1
        self.last_accessed = datetime.now().isoformat()

    @property
    def is_stale(self) -> bool:
        """Verifica se a memória está obsoleta (sem acesso há muito tempo)."""
        try:
            last = datetime.fromisoformat(self.last_accessed)
            days_old = (datetime.now() - last).days
            return days_old > 90 and self.importance < 5
        except (ValueError, TypeError):
            return False

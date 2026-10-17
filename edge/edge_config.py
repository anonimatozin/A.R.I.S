"""Edge Config — configuracao da instancia edge (CLL1/Termux).

Carrega variaveis de ambiente do Termux e fornece config
para o edge_chat.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

FALLBACK_PERSONALITY = """# A.R.I.S. (modo edge — PC offline)
Voce e o A.R.I.S., um assistente pessoal criado pelo operador.
Responda em portugues, seja direto e util.
Nao comecce com "Claro!", "Certamente!" ou "Como posso ajudar?".
Se for algo que requer o PC ligado, diga naturalmente que so consegue
fazer isso com o PC ativo.
"""


@dataclass(frozen=True)
class EdgeConfig:
    """Configuracao da instancia edge."""

    edge_groq_api_key: str = ""
    edge_model: str = "openai/gpt-oss-120b"
    edge_rate_limit: int = 100
    cll1_host: str = "192.168.0.106"
    cll1_port: int = 8765
    cll1_token: str = ""
    # expanduser(): Path("~/x") NÃO expande o "~" sozinho — sem isto os testes (e
    # qualquer EdgeConfig() com valores padrão) criavam uma pasta literal "~" no
    # diretório atual.
    memory_dir: Path = field(default_factory=lambda: Path("~/cll1/data").expanduser())
    personality_path: Path = field(
        default_factory=lambda: Path("~/cll1/data/personality_sync.md").expanduser()
    )
    sync_enabled: bool = True

    @classmethod
    def from_env(cls) -> EdgeConfig:
        """Carrega configuracao de variaveis de ambiente."""
        home = Path.home()
        return cls(
            edge_groq_api_key=os.getenv("EDGE_GROQ_API_KEY", ""),
            edge_model=os.getenv("EDGE_MODEL", "openai/gpt-oss-120b"),
            edge_rate_limit=int(os.getenv("EDGE_RATE_LIMIT", "100")),
            cll1_host=os.getenv("CLL1_HOST", "192.168.0.106"),
            cll1_port=int(os.getenv("CLL1_PORT", "8765")),
            cll1_token=os.getenv("CLL1_TOKEN", ""),
            memory_dir=Path(os.getenv("EDGE_MEMORY_DIR", str(home / "cll1" / "data"))),
            personality_path=Path(
                os.getenv(
                    "EDGE_PERSONALITY_PATH",
                    str(home / "cll1" / "data" / "personality_sync.md"),
                )
            ),
            sync_enabled=os.getenv("EDGE_SYNC_ENABLED", "true").lower() == "true",
        )

    def load_personality(self) -> str:
        """Carrega personalidade sincronizada ou fallback."""
        try:
            if self.personality_path.exists():
                return self.personality_path.read_text(encoding="utf-8")
        except Exception:
            pass
        return FALLBACK_PERSONALITY

    def save_personality(self, content: str) -> bool:
        """Salva personalidade sincronizada do PC."""
        try:
            self.personality_path.parent.mkdir(parents=True, exist_ok=True)
            self.personality_path.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

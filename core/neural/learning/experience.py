"""ExperienceStore do A.R.I.S.

Agrega estatísticas de aprendizado derivadas de cada ação executada.
Não usa reinforcement learning: apenas coleta fatos (sucesso/falha por
capacidade) e expõe contadores e sugestões simples derivadas de
padrões observados.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.neural.feedback.feedback_engine import FeedbackReport
from utils.logger import Logger

# Quantos episódios de falha por capacidade acionam um alerta de revisão
ALERT_THRESHOLD = 3


@dataclass
class ExperienceStore:
    """Estoque de experiências agregadas (estatísticas de aprendizado).

    Attributes:
        logger: Logger do sistema.
        file_path: Onde persistir as estatísticas.
    """

    logger: Logger | None = None
    file_path: Path = field(default_factory=lambda: (
        Path(__file__).resolve().parents[3] / "data" / "memory" / "Index" / "experience_stats.json"
    ))
    stats: dict[str, dict[str, int]] = field(default_factory=dict)
    total: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self) -> None:
        self.stats = defaultdict(lambda: {"success": 0, "failure": 0, "last": ""})
        self._load()

    # ── Persistência ─────────────────────────────────────────

    def _load(self) -> None:
        if self.file_path.exists():
            try:
                with open(self.file_path, encoding="utf-8") as f:
                    raw = json.load(f)
                self.stats = defaultdict(
                    lambda: {"success": 0, "failure": 0, "last": ""}, raw.get("stats", {})
                )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"ExperienceStore: falha ao carregar ({e})")

    def _save(self) -> None:
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump({"stats": dict(self.stats)}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"ExperienceStore: falha ao salvar ({e})")

    # ── Registro ─────────────────────────────────────────────

    def record(self, report: FeedbackReport) -> None:
        """Registra o desfecho de uma capacidade."""
        module = report.event.payload.get("module", "unknown")
        bucket = self.stats[module]
        bucket[report.outcome] = bucket.get(report.outcome, 0) + 1
        bucket["last"] = datetime.now().isoformat()
        self._save()

    def counter(self) -> dict[str, dict[str, int]]:
        return dict(self.stats)

    def failure_rate(self, module: str) -> float:
        """Taxa de falha de uma capacidade (0.0 a 1.0)."""
        s = self.stats[module]
        total = s["success"] + s["failure"]
        if total == 0:
            return 0.0
        return round(s["failure"] / total, 2)

    def concerning_modules(self, threshold: int = ALERT_THRESHOLD) -> list[str]:
        """Capacidades com muitas falhas consecutivas (para revisão)."""
        return [
            module for module, s in self.stats.items()
            if s["failure"] >= threshold and s["success"] == 0
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stats": dict(self.stats),
            "concerning": self.concerning_modules(),
            "total_events": sum(s["success"] + s["failure"] for s in self.stats.values()),
        }

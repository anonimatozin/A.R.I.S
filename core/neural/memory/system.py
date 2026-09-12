"""Sistema de memória do A.R.I.S. (Neural Core).

Separa a memória em quatro tipos:

- **Working Memory**  : volátil, tarefa em curso (``WorkingMemory``).
- **Episodic Memory** : experiências relevantes com avaliação de sucesso.
- **Semantic Memory** : conhecimento consolidado (reusa ``MemoryManager``).
- **Procedural Memory**: procedimentos passo a passo.

A implementação atual continua em JSON (sem banco complexo). O
principal objetivo é corrigir a persistência real dos dados: o índice
não pode ser reconstruído do zero a cada boot.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.neural.memory.working_memory import WorkingMemory
from utils.logger import Logger

# ── Experiência (Episodic Memory) ─────────────────────────────

@dataclass
class Experience:
    """Uma experiência registrada pelo sistema.

    Attributes:
        timestamp: Momento da ocorrência.
        event: Descrição/evento ocorrido.
        goal: Objetivo relacionado.
        actions: Ações executadas.
        result: Resultado observado.
        success: Se a experiência foi bem-sucedida.
        context: Contexto associado.
        importance: Importância estimada (0.0 a 1.0).
    """

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    event: str = ""
    goal: str = ""
    actions: list[str] = field(default_factory=list)
    result: str = ""
    success: bool | None = None
    context: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário."""
        return {
            "id": uuid.uuid4().hex[:10],
            "timestamp": self.timestamp,
            "event": self.event,
            "goal": self.goal,
            "actions": list(self.actions),
            "result": self.result,
            "success": self.success,
            "context": self.context,
            "importance": round(self.importance, 2),
        }


class EpisodicMemory:
    """Memória episódica persistente em JSON.

    Não registra tudo: relevância é calculada por critérios
    determinísticos (importância e confiança). Apenas experiências
    acima do piso são persistidas.
    """

    DEFAULT_PLACE = "Episodic"
    FILENAME = "episodes.json"

    def __init__(
        self,
        memory_root: Path | None = None,
        logger: Logger | None = None,
        relevance_floor: float = 0.45,
    ) -> None:
        if memory_root is None:
            memory_root = Path(__file__).resolve().parents[3] / "data" / "memory"
        self._logger = logger
        self._floor = relevance_floor
        self._dir = memory_root / self.DEFAULT_PLACE
        self._path = self._dir / self.FILENAME
        self._episodes: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                self._episodes = data.get("episodes", []) if isinstance(data, dict) else []
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"EpisodicMemory: falha ao carregar ({e})")
                self._episodes = []
        else:
            self._save()

    def _save(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"episodes": self._episodes}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            if self._logger:
                self._logger.warning(f"EpisodicMemory: falha ao salvar ({e})")

    def relevance(self, experience: Experience) -> float:
        """Calcula a relevância determinística de uma experiência."""
        score = experience.importance
        if experience.success is not None:
            score += 0.1
        if experience.goal:
            score += 0.1
        return round(min(1.0, score), 2)

    def record(self, experience: Experience, force: bool = False) -> dict[str, Any] | None:
        """Registra uma experiência se relevante o suficiente.

        Args:
            experience: Experiência a registrar.
            force: Ignora o piso de relevância.

        Returns:
            Dicionário persistido (ou None se não registrada).
        """
        if not force and self.relevance(experience) < self._floor:
            return None
        data = experience.to_dict()
        data["relevance"] = self.relevance(experience)
        self._episodes.append(data)
        self._save()
        return data

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Episódios mais recentes."""
        return list(self._episodes[-limit:])[::-1]

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Busca episódios por texto."""
        q = query.lower()
        results = [
            e for e in self._episodes
            if q in e["event"].lower() or q in e["goal"].lower() or q in (e["result"] or "").lower()
        ]
        return results[:limit]

    def successes(self) -> int:
        """Quantidade de experiências bem-sucedidas."""
        return sum(1 for e in self._episodes if e.get("success") is True)

    def total(self) -> int:
        return len(self._episodes)


# ── Semantic Memory ───────────────────────────────────────────

class SemanticMemory:
    """Memória semântica: conhecimentos consolidados.

    Reaproveita o ``MemoryManager`` existente (memória de longo prazo
    em ``data/memory``), preservando categorias e dados atuais.
    """

    def __init__(self, memory_manager) -> None:
        self._backend = memory_manager

    @property
    def backend(self):
        """Instância do MemoryManager subjacente."""
        return self._backend

    def save(self, title: str, content: str, category=None, importance: int = 5,
             tags: list[str] | None = None, source: str = "semantic") -> Any:
        return self._backend.save(
            title=title,
            content=content,
            category=category,
            importance=importance,
            tags=tags,
            source=source,
        )

    def search(self, query: str = "", category=None, min_importance: int = 0,
               tags: list[str] | None = None, limit: int = 20) -> list[Any]:
        if self._backend is None:
            return []
        return self._backend.search(
            query=query, category=category, min_importance=min_importance,
            tags=tags, limit=limit,
        )

    def get(self, memory_id: str):
        return self._backend.get(memory_id)


# ── Procedural Memory ─────────────────────────────────────────

@dataclass
class Procedure:
    """Um procedimento passo a passo do sistema."""
    name: str
    steps: list[str] = field(default_factory=list)
    description: str = ""
    procedures: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": list(self.steps),
        }


class ProceduralMemory:
    """Memória procedural persistente em JSON.

    Abstração para armazenar procedimentos (ex.: como abrir o
    navegador). Nesta fase é armazenamento manual apenas; sem
    aprendizado automático de procedimentos.
    """

    DEFAULT_PLACE = "Procedural"
    FILENAME = "procedures.json"

    def __init__(self, memory_root: Path | None = None, logger: Logger | None = None) -> None:
        if memory_root is None:
            memory_root = Path(__file__).resolve().parents[3] / "data" / "memory"
        self._logger = logger
        self._dir = memory_root / self.DEFAULT_PLACE
        self._path = self._dir / self.FILENAME
        self._procedures: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                self._procedures = data.get("procedures", {}) if isinstance(data, dict) else {}
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"ProceduralMemory: falha ao carregar ({e})")
                self._procedures = {}
        else:
            self._save()

    def _save(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"procedures": self._procedures}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            if self._logger:
                self._logger.warning(f"ProceduralMemory: falha ao salvar ({e})")

    def save_procedure(self, procedure: Procedure) -> None:
        """Salva (ou sobrescreve) um procedimento."""
        self._procedures[procedure.name] = procedure.to_dict()
        self._save()

    def get(self, name: str) -> dict[str, Any] | None:
        return self._procedures.get(name)

    def has(self, name: str) -> bool:
        return name in self._procedures

    def delete(self, name: str) -> bool:
        if name in self._procedures:
            del self._procedures[name]
            self._save()
            return True
        return False

    def names(self) -> list[str]:
        return list(self._procedures.keys())

    def total(self) -> int:
        return len(self._procedures)


# ── Memory System (orquestrador) ──────────────────────────────

class MemorySystem:
    """Sistema de memória integrado do A.R.I.S.

    Compõe Working, Episodic, Semantic e Procedural em uma única
    porta, mantendo cada tipo independente.
    """

    def __init__(
        self,
        working_memory: WorkingMemory,
        semantic: SemanticMemory,
        episodic: EpisodicMemory,
        procedural: ProceduralMemory,
    ) -> None:
        self.working = working_memory
        self.semantic = semantic
        self.episodic = episodic
        self.procedural = procedural

    @classmethod
    def build(cls, memory_manager, logger: Logger | None = None,
              memory_root: Path | None = None) -> MemorySystem:
        """Constrói o sistema completo a partir do MemoryManager atual."""
        working = WorkingMemory()
        semantic = SemanticMemory(memory_manager)
        episodic = EpisodicMemory(memory_root=memory_root, logger=logger)
        procedural = ProceduralMemory(memory_root=memory_root, logger=logger)
        return cls(working, semantic, episodic, procedural)

    def snapshot(self) -> dict[str, Any]:
        """Visão geral das memórias."""
        return {
            "working_task": self.working.snapshot(),
            "semantic_total": (
                self.semantic.backend.get_stats().get("total_memories", 0)
                if self.semantic.backend is not None else 0
            ),
            "episodic_total": self.episodic.total(),
            "procedural_total": self.procedural.total(),
            "episodic_successes": self.episodic.successes(),
        }

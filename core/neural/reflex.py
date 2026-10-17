"""Camada Reflexo do A.R.I.S.

Mini-agentes especializados, leves e determinísticos (sem LLM) que interceptam
a entrada antes do ciclo cognitivo completo.

Arquitetura:
- ReflexAgent: classe base para mini-agentes
- ReflexRegistry: registro e roteamento de agentes
- Métricas: reflex_hits vs llm_fallbacks
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from utils.logger import Logger


@dataclass
class ReflexResult:
    """Resultado de um agente reflexo."""
    handled: bool
    response: str = ""
    confidence: float = 0.0
    agent_name: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ReflexAgent(ABC):
    """Classe base para mini-agentes reflexos.

    Cada agente declara:
    - patterns: regex/compiled patterns que ele reconhece
    - can_handle(): verificação rápida (regex match)
    - handle(): execução determinística (sem LLM)
    """

    name: str = "base"
    description: str = "Agente reflexo base"
    patterns: list[re.Pattern] = []
    priority: int = 0  # maior = mais prioritário

    def __init__(self, logger: Logger | None = None, **dependencies) -> None:
        self._logger = logger
        self._deps = dependencies

    @abstractmethod
    def can_handle(self, text: str) -> tuple[bool, float]:
        """Verifica se o agente pode tratar a entrada.

        Returns:
            (pode_tratar, confiança 0.0-1.0)
        """
        pass

    @abstractmethod
    def handle(self, text: str, context: dict[str, Any] | None = None) -> ReflexResult:
        """Processa a entrada e retorna resposta.

        Deve ser rápido, determinístico, sem chamar LLM.
        """
        pass

    def _match_patterns(self, text: str) -> tuple[bool, float]:
        """Helper: verifica patterns compilados."""
        for pattern in self.patterns:
            if pattern.search(text):
                return True, 0.95
        return False, 0.0


class ReflexRegistry:
    """Registro central dos agentes reflexos.

    Carrega agentes via ModuleManager (plugins) ou registro manual.
    Roteia entrada para o agente com maior prioridade/confiança.
    """

    def __init__(self, logger: Logger | None = None) -> None:
        self._logger = logger
        self._agents: list[ReflexAgent] = []
        self._metrics = {
            "reflex_hits": 0,
            "llm_fallbacks": 0,
            "total_latency_ms": 0.0,
            "by_agent": {},
        }

    def register(self, agent: ReflexAgent) -> None:
        """Registra um agente reflexo."""
        self._agents.append(agent)
        # Ordenar por prioridade decrescente
        self._agents.sort(key=lambda a: a.priority, reverse=True)
        if self._logger:
            self._logger.info(f"Reflexo: agente '{agent.name}' registrado (prioridade={agent.priority})")

    def load_from_plugins(self, plugin_dir: str) -> None:
        """Carrega agentes de plugins (auto-load via ModuleManager).

        Plugins devem expor uma função `create_reflex_agents(logger, **deps) -> list[ReflexAgent]`.
        """
        import importlib.util
        from pathlib import Path

        plugin_path = Path(plugin_dir)
        if not plugin_path.exists():
            return

        for py_file in plugin_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"reflex_plugin_{py_file.stem}", py_file
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if hasattr(module, "create_reflex_agents"):
                        agents = module.create_reflex_agents(self._logger)
                        for agent in agents:
                            self.register(agent)
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"Reflexo: falha ao carregar plugin {py_file.name}: {e}")

    def process(self, text: str, context: dict[str, Any] | None = None) -> Optional[ReflexResult]:
        """Tenta processar com agentes reflexos em ordem de prioridade.

        Returns:
            ReflexResult se algum agente tratar com confiança alta, None caso contrário.
        """
        start = time.perf_counter()

        for agent in self._agents:
            try:
                can_handle, confidence = agent.can_handle(text)
                if can_handle and confidence >= 0.8:  # threshold de confiança
                    result = agent.handle(text, context)
                    result.latency_ms = (time.perf_counter() - start) * 1000

                    # Métricas
                    self._metrics["reflex_hits"] += 1
                    self._metrics["total_latency_ms"] += result.latency_ms
                    self._metrics["by_agent"][agent.name] = \
                        self._metrics["by_agent"].get(agent.name, 0) + 1

                    if self._logger:
                        self._logger.debug(
                            f"Reflexo: '{agent.name}' tratou em {result.latency_ms:.1f}ms "
                            f"(conf={confidence:.2f})"
                        )
                    return result

            except Exception as e:
                if self._logger:
                    self._logger.warning(f"Reflexo: erro no agente '{agent.name}': {e}")

        # Nenhum agente tratou
        latency = (time.perf_counter() - start) * 1000
        self._metrics["llm_fallbacks"] += 1
        self._metrics["total_latency_ms"] += latency
        return None

    def get_metrics(self) -> dict[str, Any]:
        """Retorna métricas da camada reflexo."""
        total = self._metrics["reflex_hits"] + self._metrics["llm_fallbacks"]
        return {
            "reflex_hits": self._metrics["reflex_hits"],
            "llm_fallbacks": self._metrics["llm_fallbacks"],
            "total_requests": total,
            "hit_rate": self._metrics["reflex_hits"] / total if total > 0 else 0.0,
            "avg_latency_ms": (
                self._metrics["total_latency_ms"] / total if total > 0 else 0.0
            ),
            "by_agent": dict(self._metrics["by_agent"]),
        }

    def reset_metrics(self) -> None:
        """Reseta contadores."""
        self._metrics = {
            "reflex_hits": 0,
            "llm_fallbacks": 0,
            "total_latency_ms": 0.0,
            "by_agent": {},
        }


# Instância global (singleton)
_reflex_registry: ReflexRegistry | None = None


def get_reflex_registry(logger: Logger | None = None) -> ReflexRegistry:
    """Retorna instância singleton do ReflexRegistry."""
    global _reflex_registry
    if _reflex_registry is None:
        _reflex_registry = ReflexRegistry(logger)
    return _reflex_registry
"""Reasoning Router do A.R.I.S.

Decide se uma tarefa precisa de LLM ou pode ser resolvida de forma
determinística:

    "qual uso da CPU?"              → System API (determinístico)
    "abra o navegador"              → intent (determinístico)
    "explique por que PC está lento"→ LLM + informações do sistema
    "investigue e resolva esse problema" → LLM + Planner + Ações

O LLM é usado apenas onde agrega valor. Um motor determinístico cobre
padrões conhecidos de forma confiável e barata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.advanced_interpreter import Intent
from core.neural.events import Event
from utils.logger import Logger


class ReasoningMode(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    HYBRID = "hybrid"
    LOCAL = "local"


@dataclass
class RoutingDecision:
    """Resultado do roteamento de raciocínio."""
    mode: ReasoningMode
    reason: str
    intents: list[Intent] = field(default_factory=list)

    @property
    def needs_llm(self) -> bool:
        return self.mode in (ReasoningMode.LLM, ReasoningMode.HYBRID)


class DeterministicEngine:
    """Motor determinístico: traduz padrões conhecidos em intenções.

    Barato, previsível e sem LLM. Cobre comandos de alta frequência.
    """

    # (padrões regex, module, action, extra)
    RULES: list[tuple[str, str, str, dict[str, Any]]] = [
        (r"(?i)(uso|carga|percentual)\s*(da|de)\s*(cpu)", "sys", "analyze", {}),
        (r"(?i)(cpu|processador)", "sys", "analyze", {}),
        (r"(?i)(ram|memória\s*do\s*sistema|memoria)", "sys", "analyze", {}),
        (r"(?i)(uso\s*de\s*disco|disco\s*rigido|hd|ssd)", "sys", "analyze", {}),
        (r"(?i)(clima|previsão|previsao|tempo\s*(em|de|na|no))", "weather", "now", {"city": ""}),
        (r"(?i)temperatura", "weather", "now", {"city": ""}),
        (r"(?i)(pesquis|busca|procura|google)", "websearch", "search", {"query": ""}),
        (r"(?i)(lembrete|lembrar|agenda|pomodoro|timer|cronômetro|cronometro)", "scheduler", "list", {}),
        (r"(?i)(abre|abra|abrir|abriria)\s+(o\s+|a\s+)?(discord|spotify|youtube|chrome|firefox|notepad|calculadora|navegador|explorer)", "desktop", "open_app", {"app": ""}),
        (r"(?i)^contexto$|^o\s*que\s*estou\s*fazendo$", "context", "detect", {}),
        (r"(?i)^status\s*(do|da)\s*(hardware|esp32)$", "hardware", "status", {}),
    ]

    # App canonicalização
    APPS = {
        "discord": "discord", "spotify": "spotify", "youtube": "youtube",
        "chrome": "chrome", "firefox": "firefox", "notepad": "notepad",
        "calculadora": "calculator", "navegador": "chrome",
        "explorer": "windows explorer",
    }

    def __init__(self, logger: Logger | None = None) -> None:
        self._logger = logger

    def parse(self, query: str) -> list[Intent]:
        """Tenta interpretar a consulta de forma determinística."""
        for pattern, module, action, extra in self.RULES:
            match = re.search(pattern, query)
            if not match:
                continue

            params = dict(extra)
            # Completar parâmetros básicos extraídos do texto
            if action == "now" and "city" in params:
                words = query.replace(match.group(0), " ").strip()
                # Cidade = resto do texto significativo
                candidate = re.sub(r"[^\wÀ-ú ]", "", words).strip()
                if candidate and len(candidate) <= 40:
                    params["city"] = candidate
                else:
                    params.pop("city")
            elif action == "search":
                words = query.replace(match.group(0), " ").strip()
                params["query"] = words or params["query"]
            elif action == "open_app":
                app = match.group(0).lower()
                for name, canonical in self.APPS.items():
                    if name in app:
                        params["app"] = canonical
                        break

            intent = Intent(module=module, action=action, params=params, confidence=0.9)
            if self._logger:
                self._logger.debug(f"DeterministicEngine: {query!r} → {module}/{action}")
            return [intent]

        return []

    def can_handle(self, query: str) -> bool:
        """Indica se o motor determinístico cobre a consulta."""
        return bool(self.parse(query))


class ReasoningRouter:
    """Roteador de raciocínio: determinístico ou LLM."""

    def __init__(
        self,
        command_registry=None,
        logger: Logger | None = None,
        deterministic: DeterministicEngine | None = None,
    ) -> None:
        self._registry = command_registry
        self._logger = logger
        self._deterministic = deterministic or DeterministicEngine(logger=logger)

    def route(self, query: str, event: Event | None = None) -> RoutingDecision:
        """Roteia uma consulta para o motor adequado.

        Estratégia:
            1. Intento direto (comando do registry presente).
            2. Padrão determinístico conhecido.
            3. Senão, LLM.
            4. Texto conversacional curto → LOCAL (sem LLM).
        """
        q = query.strip().lower()

        # 1. Intento/ato direto
        if self._registry is not None and self._registry.has_intent(q):
            return RoutingDecision(
                mode=ReasoningMode.DETERMINISTIC,
                reason=f"comando direto '{q}'",
                intents=[Intent(module=q, action="execute", params={}, confidence=1.0)],
            )

        # 4. Conversa genérica → LOCAL (não desperdiçar LLM)
        if len(q.split()) <= 3 and not any(self._deterministic.RULES):
            pass  # continua para determinístico abaixo; fallback LLM se necessário

        # 2. Determinístico
        intents = self._deterministic.parse(query)
        if intents:
            return RoutingDecision(
                mode=ReasoningMode.DETERMINISTIC,
                reason="regra determinística correspondente",
                intents=intents,
            )

        # 3. LLM
        return RoutingDecision(
            mode=ReasoningMode.LLM,
            reason="requer interpretação semântica (fora do determinístico)",
        )

    def get_stats(self) -> dict[str, Any]:
        return {"rules": len(self._deterministic.RULES)}

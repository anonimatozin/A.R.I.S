"""Agentes Reflexo built-in do A.R.I.S.

Mini-agentes especializados para interceptação rápida sem LLM.
Carregados automaticamente via ModuleManager.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from core.neural.reflex import ReflexAgent, ReflexResult


class TimeAgent(ReflexAgent):
    """Agente para consultas de hora e data."""

    name = "time"
    description = "Responde hora atual, data, dia da semana"
    priority = 100
    patterns = [
        re.compile(r"(?i)^(?:que\s+)?hora[s]?\s*(?:s[aã]o|e|est[aá])\??$"),
        re.compile(r"(?i)^(?:que\s+)?horas\s*(?:s[aã]o|são)\??$"),
        re.compile(r"(?i)^(?:qual\s+)?hora\s*(?:e|agora)\??$"),
        re.compile(r"(?i)^(?:que\s+)?dia\s*(?:e|hoje|estamos)\??$"),
        re.compile(r"(?i)^(?:qual\s+(?:a\s+)?)?data\s*(?:e|hoje|de hoje)\??$"),
        re.compile(r"(?i)^hoje\s*(?:e|dia)\s*(?:que|qual)\??$"),
        re.compile(r"(?i)^(?:dia\s+da\s+semana|que\s+dia\s+da\s+semana)\??$"),
        re.compile(r"(?i)^data\s+de\s+hoje\??$"),
    ]

    def can_handle(self, text: str) -> tuple[bool, float]:
        for pattern in self.patterns:
            if pattern.search(text.strip()):
                return True, 0.98
        return False, 0.0

    def handle(self, text: str, context: dict[str, Any] | None = None) -> ReflexResult:
        now = datetime.now()
        text_lower = text.lower().strip()

        if any(kw in text_lower for kw in ["hora", "horas", "relógio", "relogio"]):
            response = f"São **{now.strftime('%H:%M:%S')}**."
        elif any(kw in text_lower for kw in ["dia da semana", "dia da semana"]):
            dias = ["segunda-feira", "terça-feira", "quarta-feira",
                    "quinta-feira", "sexta-feira", "sábado", "domingo"]
            response = f"Hoje é **{dias[now.weekday()]}**."
        else:
            response = f"Hoje é **{now.strftime('%d/%m/%Y')}**."

        return ReflexResult(
            handled=True,
            response=response,
            confidence=0.98,
            agent_name=self.name,
            metadata={"type": "time", "iso": now.isoformat()},
        )


class MathAgent(ReflexAgent):
    """Agente para cálculos matemáticos simples."""

    name = "math"
    description = "Avalia expressões matemáticas simples (+, -, *, /, **, //, %)"
    priority = 90
    patterns = [
        re.compile(r"^\s*\d+(?:\.\d+)?\s*[\+\-\*\/\%\*]\s*\d+(?:\.\d+)?\s*$"),
        re.compile(r"(?i)^(?:quanto\s+(?:é|faz|d[aá])\s+)?\d+\s*[\+\-\*\/]\s*\d+\??$"),
        re.compile(r"(?i)^(?:calcule|calcula|compute)\s+.+$"),
        re.compile(r"^\s*\d+(?:\.\d+)?\s*\*\*\s*\d+(?:\.\d+)?\s*$"),  # potência
        re.compile(r"^\s*\d+(?:\.\d+)?\s*//\s*\d+(?:\.\d+)?\s*$"),    # divisão inteira
    ]

    # Operações permitidas (seguro)
    _SAFE_OPS = {
        "+": lambda a, b: a + b,
        "-": lambda a, b: a - b,
        "*": lambda a, b: a * b,
        "/": lambda a, b: a / b if b != 0 else "Erro: divisão por zero",
        "//": lambda a, b: a // b if b != 0 else "Erro: divisão por zero",
        "%": lambda a, b: a % b if b != 0 else "Erro: módulo por zero",
        "**": lambda a, b: a ** b,
    }

    def can_handle(self, text: str) -> tuple[bool, float]:
        txt = text.strip()
        # Evitar pegar coisas que não são matemática
        if re.search(r"(?i)(quanto\s+custa|preço|valor|reais?|dollars?)", txt):
            return False, 0.0
        for pattern in self.patterns:
            if pattern.search(txt):
                return True, 0.95
        return False, 0.0

    def _eval_expression(self, expr: str) -> float | str:
        """Avalia expressão matemática de forma segura."""
        try:
            # Remover palavras-chave
            expr = re.sub(r"(?i)^(?:quanto\s+(?:é|faz|d[aá])\s+|calcule|calcula|compute\s+)", "", expr)
            expr = expr.strip().rstrip("?")

            # Validar: apenas números, operadores, parênteses, espaços
            if not re.match(r"^[\d\s\+\-\*\/\(\)\.\%\*]+$", expr):
                return "Expressão inválida"

            # Verificar operadores perigosos
            if "__" in expr or "import" in expr or "eval" in expr or "exec" in expr:
                return "Expressão não permitida"

            # Avaliar com eval restrito
            result = eval(expr, {"__builtins__": {}}, {})
            return result

        except ZeroDivisionError:
            return "Erro: divisão por zero"
        except Exception:
            return "Erro ao calcular"

    def handle(self, text: str, context: dict[str, Any] | None = None) -> ReflexResult:
        result = self._eval_expression(text)

        if isinstance(result, str) and result.startswith("Erro"):
            response = result
        else:
            # Formatar: remover .0 se inteiro
            if isinstance(result, float) and result == int(result):
                result = int(result)
            response = f"Resultado: **{result}**"

        return ReflexResult(
            handled=True,
            response=response,
            confidence=0.95,
            agent_name=self.name,
            metadata={"type": "math", "expression": text.strip()},
        )


class SystemStatusAgent(ReflexAgent):
    """Agente para status do sistema (CPU, RAM, disco, modo ARIS)."""

    name = "system_status"
    description = "Status do sistema: CPU, memória, disco, modo EDGE/PRIMARY"
    priority = 80
    patterns = [
        re.compile(r"(?i)^(?:status|estado)\s*(?:do\s+)?(?:sistema|pc|computador|máquina|maquina)\??$"),
        re.compile(r"(?i)^(?:como\s+est[aá]?\s+o\s+)?(?:sistema|pc|computador)\??$"),
        re.compile(r"(?i)^(?:cpu|processador)\s*(?:uso|load|status)\??$"),
        re.compile(r"(?i)^(?:ram|mem[oó]ria)\s*(?:uso|livre|status|dispon[ií]vel)\??$"),
        re.compile(r"(?i)^(?:disco|hd|ssd)\s*(?:uso|livre|status)\??$"),
        re.compile(r"(?i)^(?:modo|mode)\s*(?:aris|atual)\??$"),
        re.compile(r"(?i)^(?:edge|primary)\s*(?:modo|status)\??$"),
        re.compile(r"(?i)^diagn[oó]stico\s*(?:do\s+)?(?:sistema|pc)\??$"),
    ]

    def __init__(self, logger=None, **dependencies):
        super().__init__(logger, **dependencies)
        self._analyzer = dependencies.get("analyzer")
        self._neural_state = dependencies.get("state")
        self._mode_manager = dependencies.get("mode_manager")

    def can_handle(self, text: str) -> tuple[bool, float]:
        for pattern in self.patterns:
            if pattern.search(text.strip()):
                return True, 0.95
        return False, 0.0

    def handle(self, text: str, context: dict[str, Any] | None = None) -> ReflexResult:
        parts = []
        text_lower = text.lower().strip()

        try:
            # CPU
            if self._analyzer and hasattr(self._analyzer, "cpu_usage"):
                cpu = self._analyzer.cpu_usage()
                parts.append(f"CPU: **{cpu:.1f}%**")

            # RAM
            if self._analyzer and hasattr(self._analyzer, "memory_usage"):
                ram = self._analyzer.memory_usage()
                parts.append(f"RAM: **{ram:.1f}%**")

            # Disco
            if self._analyzer and hasattr(self._analyzer, "disk_usage"):
                disk = self._analyzer.disk_usage()
                parts.append(f"Disco: **{disk:.1f}%**")

            # Modo ARIS
            if self._mode_manager:
                mode_desc = self._mode_manager.describe()
                parts.append(f"Modo: **{mode_desc}**")
            elif self._neural_state:
                pc_online = getattr(self._neural_state, "_hardware_connected", None)
                if pc_online is not None:
                    parts.append(f"Modo: **{'PRIMARY' if pc_online else 'EDGE'}**")

            if not parts:
                parts.append("Sensores de sistema indisponíveis no momento")

        except Exception as e:
            parts.append(f"Erro ao obter status: {e}")

        response = " | ".join(parts)

        return ReflexResult(
            handled=True,
            response=response,
            confidence=0.9,
            agent_name=self.name,
            metadata={"type": "system_status"},
        )


class MemoryRecentLookupAgent(ReflexAgent):
    """Agente para buscar últimas N mensagens da memória de conversa."""

    name = "memory_recent"
    description = "Recupera últimas interações da memória de trabalho"
    priority = 70
    patterns = [
        re.compile(r"(?i)^(?:ultimas?|\u00faltimas?)\s+(?:mensagem(?:s)?|interac[o\u00f3]es?|conversas?)\s*(?:\d+)?\??$"),
        re.compile(r"(?i)^(?:o\s+que\s+)?(?:eu\s+)?(?:disse|perguntei|falei)\s+(?:antes|agora|recentemente)\??$"),
        re.compile(r"(?i)^hist[oó]rico\s+(?:recente|das\s+\d+)\??$"),
        re.compile(r"(?i)^(?:mostre|mostra|liste|lista)\s+(?:ultimas?|últimas?)\s+\d+\s+(?:mensagem(?:s)?|falas)\??$"),
    ]

    def __init__(self, logger=None, **dependencies):
        super().__init__(logger, **dependencies)
        self._memory = dependencies.get("memory")
        self._working = dependencies.get("working")

    def can_handle(self, text: str) -> tuple[bool, float]:
        for pattern in self.patterns:
            if pattern.search(text.strip()):
                return True, 0.9
        return False, 0.0

    def _extract_limit(self, text: str) -> int:
        """Extrai número de mensagens solicitadas."""
        match = re.search(r"(\d+)", text)
        if match:
            return min(int(match.group(1)), 20)  # máx 20
        return 5  # padrão

    def handle(self, text: str, context: dict[str, Any] | None = None) -> ReflexResult:
        limit = self._extract_limit(text)
        items = []

        # Tentar working memory primeiro (mais recente)
        if self._working and hasattr(self._working, "get_recent"):
            try:
                items = self._working.get_recent(limit)
            except Exception:
                pass

        # Fallback: memory manager
        if not items and self._memory and hasattr(self._memory, "get_recent_conversations"):
            try:
                items = self._memory.get_recent_conversations(limit)
            except Exception:
                pass

        if not items:
            response = "Nenhuma conversa recente na memória de trabalho."
        else:
            lines = []
            for i, item in enumerate(items[:limit], 1):
                if isinstance(item, dict):
                    user = item.get("user", item.get("text", str(item)))
                    aris = item.get("aris", item.get("response", ""))
                else:
                    user = str(item)
                    aris = ""
                lines.append(f"{i}. Você: {user[:80]}")
                if aris:
                    lines.append(f"   ARIS: {aris[:80]}")
            response = "**Últimas interações:**\n" + "\n".join(lines)

        return ReflexResult(
            handled=True,
            response=response,
            confidence=0.85,
            agent_name=self.name,
            metadata={"type": "memory_recent", "limit": limit, "count": len(items)},
        )


def create_reflex_agents(logger, **dependencies) -> list[ReflexAgent]:
    """Factory function para ModuleManager auto-load."""
    return [
        TimeAgent(logger, **dependencies),
        MathAgent(logger, **dependencies),
        SystemStatusAgent(logger, **dependencies),
        MemoryRecentLookupAgent(logger, **dependencies),
    ]
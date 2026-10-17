"""Reflex Layer — Mini-agentes leves e determinísticos para respostas rápidas.

Interceptam a entrada ANTES do ciclo completo do NeuralCore.
Casos simples e recorrentes respondem na hora, sem LLM.
Fallback automático pro ciclo completo quando nenhum reconhece com alta confiança.

Extensível via Plugin System (core/module_manager.py) passando pelo SecurityGate.
"""

from __future__ import annotations

import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from core.memory import MemoryManager
from core.neural.security.security_gate import GateOutcome, SecurityGate
from utils.logger import Logger


@dataclass
class ReflexResult:
    """Resultado de um reflex agent."""
    handled: bool
    response: str = ""
    confidence: float = 0.0
    module: str = ""
    action: str = ""
    speak: bool = True  # se deve falar via TTS


class ReflexAgent(ABC):
    """Base para mini-agentes reflexivos."""

    name: str = "base"
    description: str = ""
    priority: int = 0  # maior = executado primeiro
    min_confidence: float = 0.8  # threshold mínimo para responder

    def __init__(
        self,
        memory: MemoryManager | None = None,
        security_gate: SecurityGate | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._memory = memory
        self._security = security_gate
        self._logger = logger

    @abstractmethod
    def can_handle(self, text: str) -> float:
        """Retorna confidence (0.0-1.0) se este agente pode lidar com o texto."""
        pass

    @abstractmethod
    def handle(self, text: str, origin: Any = None) -> ReflexResult:
        """Processa o texto e retorna resultado."""
        pass

    def _check_security(self, module: str, action: str) -> bool:
        """Verifica se a ação passa no SecurityGate."""
        if not self._security:
            return True
        from core.neural.decision.decision_engine import Decision
        decision = Decision(module=module, action=action, parameters={}, confidence=1.0, risk=1, source="reflex")
        gate = self._security.approve(decision)
        return gate.outcome in (GateOutcome.APPROVED, GateOutcome.REQUIRES_CONFIRMATION)


class TimeReflexAgent(ReflexAgent):
    """Responde hora/data atuais."""

    name = "time"
    description = "Hora e data atuais"
    priority = 100
    min_confidence = 0.9

    _TIME_PATTERNS = [
        r"^que\s*horas?\s*(?:são|é)?\s*\??$",
        r"^horas?\s*\??$",
        r"^que\s*horas\s*(?:tem|temos)?\s*\??$",
        r"^hora\s*atual\s*\??$",
        r"^what\s*(?:time|hour)\s*(?:is\s*it)?\s*\??$",
    ]

    _DATE_PATTERNS = [
        r"^que\s*dia\s*(?:é|hoje)?\s*\??$",
        r"^data\s*(?:de\s*hoje)?\s*\??$",
        r"^hoje\s*(?:é\s*dia)?\s*\??$",
        r"^qual\s*a\s*data\s*\??$",
        r"^what\s*(?:date|day)\s*(?:is\s*it)?\s*\??$",
    ]

    def can_handle(self, text: str) -> float:
        lower = text.lower().strip()
        for pattern in self._TIME_PATTERNS:
            if re.match(pattern, lower):
                return 0.95
        for pattern in self._DATE_PATTERNS:
            if re.match(pattern, lower):
                return 0.95
        return 0.0

    def handle(self, text: str, origin: Any = None) -> ReflexResult:
        lower = text.lower().strip()

        is_time = any(re.match(p, lower) for p in self._TIME_PATTERNS)
        is_date = any(re.match(p, lower) for p in self._DATE_PATTERNS)

        if is_time:
            response = f"São {time.strftime('%H:%M')}."
            return ReflexResult(True, response, 0.95, "time", "current_time")
        elif is_date:
            response = f"Hoje é {time.strftime('%d/%m/%Y')}."
            return ReflexResult(True, response, 0.95, "time", "current_date")

        return ReflexResult(False)


class CalcReflexAgent(ReflexAgent):
    """Calculadora simples para expressões matemáticas."""

    name = "calc"
    description = "Cálculos matemáticos simples"
    priority = 90
    min_confidence = 0.85

    _CALC_PATTERNS = [
        r"^quanto\s*(?:é|dá|faz)?\s*[\d\s\+\-\*\/\(\)\.]+$",
        r"^calcula\s+[\d\s\+\-\*\/\(\)\.]+$",
        r"^[\d\s\+\-\*\/\(\)\.]+\s*=\s*\??$",
        r"^\d+\s*[\+\-\*\/]\s*\d+(?:\s*[\+\-\*\/]\s*\d+)*\s*\??$",
    ]

    def can_handle(self, text: str) -> float:
        lower = text.lower().strip()
        for pattern in self._CALC_PATTERNS:
            if re.match(pattern, lower):
                return 0.9
        # Expressão matemática pura
        if re.match(r"^[\d\s\+\-\*\/\(\)\.]+\s*$", lower) and any(op in lower for op in "+-*/"):
            return 0.7
        return 0.0

    def handle(self, text: str, origin: Any = None) -> ReflexResult:
        lower = text.lower().strip()

        # Extrair expressão
        expr = lower
        for prefix in ["quanto é", "quanto dá", "quanto faz", "calcula", "calcule"]:
            if expr.startswith(prefix):
                expr = expr[len(prefix):].strip()
                break

        # Remover "?" final
        expr = expr.rstrip("?")

        try:
            # Validar expressão (apenas números e operadores básicos)
            if not re.match(r"^[\d\s\+\-\*\/\(\)\.]+$", expr):
                return ReflexResult(False)
            if "**" in expr or "//" in expr:
                return ReflexResult(False)  # evita DoS (9**9**9)
            # Avaliar com segurança via AST (sem eval)
            import ast as _ast
            import operator as _op
            _ops = {_ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mult: _op.mul,
                    _ast.Div: _op.truediv, _ast.USub: _op.neg, _ast.UAdd: _op.pos}
            def _eval(node):
                if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
                    return node.value
                if isinstance(node, _ast.BinOp) and type(node.op) in _ops:
                    return _ops[type(node.op)](_eval(node.left), _eval(node.right))
                if isinstance(node, _ast.UnaryOp) and type(node.op) in _ops:
                    return _ops[type(node.op)](_eval(node.operand))
                raise ValueError("expressão inválida")
            tree = _ast.parse(expr, mode="eval")
            result = _eval(tree.body)
            response = f"{expr} = {result}"
            return ReflexResult(True, response, 0.9, "calc", "calculate", speak=True)
        except Exception:
            return ReflexResult(False)


class SystemStatusReflexAgent(ReflexAgent):
    """Status rápido do sistema (CPU, RAM)."""

    name = "sys_status"
    description = "Status rápido do sistema"
    priority = 80
    min_confidence = 0.85

    _PATTERNS = [
        r"^status\s*(?:do\s*sistema)?\s*\??$",
        r"^como\s*(?:tá|está)\s*(?:o\s*sistema|o\s*pc|a\s*máquina)?\s*\??$",
        r"^sistema\s*\??$",
        r"^cpu\s*(?:e\s*ram|e\s*memória)?\s*\??$",
        r"^memória\s*(?:e\s*cpu)?\s*\??$",
        r"^ram\s*\??$",
        r"^system\s*status\s*\??$",
    ]

    def __init__(self, analyzer: Any = None, **kwargs):
        super().__init__(**kwargs)
        self._analyzer = analyzer

    def can_handle(self, text: str) -> float:
        lower = text.lower().strip()
        for pattern in self._PATTERNS:
            if re.match(pattern, lower):
                return 0.9
        return 0.0

    def handle(self, text: str, origin: Any = None) -> ReflexResult:
        if not self._analyzer:
            return ReflexResult(False)

        try:
            cpu = self._analyzer.cpu_usage()
            mem = self._analyzer.get_memory_usage()
            response = f"CPU: {cpu:.0f}%, RAM: {mem:.0f}%"
            return ReflexResult(True, response, 0.9, "sys", "status")
        except Exception:
            return ReflexResult(False)


class MemoryLookupReflexAgent(ReflexAgent):
    """Lookup rápido de memória recente."""

    name = "memory_lookup"
    description = "Busca na memória recente"
    priority = 70
    min_confidence = 0.75

    _PATTERNS = [
        r"^o\s*que\s*(?:eu\s*)?(?:falei|disse|pedi)\s*(?:anteontem|ontem|ha\s*pouco|agora\s*pouco)\s*\??$",
        r"^última\s*(?:coisa|mensagem|fala)\s*(?:que\s*(?:eu\s*)?(?:falei|disse))?\s*\??$",
        r"^o\s*que\s*eu\s*disse\s*\??$",
        r"^(?:último|ultimo)\s*(?:comando|pedido|fala)\s*\??$",
    ]

    def can_handle(self, text: str) -> float:
        lower = text.lower().strip()
        for pattern in self._PATTERNS:
            if re.match(pattern, lower):
                return 0.8
        return 0.0

    def handle(self, text: str, origin: Any = None) -> ReflexResult:
        if not self._memory:
            return ReflexResult(False)

        try:
            results = self._memory.search(query="", limit=1)
            if results:
                last = results[0]
                response = f"Última coisa que você disse: {last.content[:120]}"
                return ReflexResult(True, response, 0.8, "search", "recent")
        except Exception:
            pass
        return ReflexResult(False)


class JokenpoReflexAgent(ReflexAgent):
    """Pedra-papel-tesoura — sorteio local (sem LLM), placar determinístico.

    O resultado da rodada também vai para a matriz de LED via ``/num``
    (0=empate, 1=ARIS venceu, 2=você venceu); LED opcional (None = sem).
    """

    name = "jokenpo"
    description = "Pedra-papel-tesoura (sorteio local, sem LLM)"
    priority = 85
    min_confidence = 0.9

    MOVES = ("pedra", "papel", "tesoura")

    _START_RE = re.compile(
        r"^(?:aris\s*,?\s*)?"
        r"(?:vamos\s+|bora\s+|quero\s+|quer\s+|podemos\s+|chama\s+)?"
        r"(?:jogar?\s+|brincar\s+de\s+|partida\s+de\s+)?"
        r"(?:pedra[\s\-]*papel[\s\-]*tesoura|jokenpo|jokemp[oô]|ppt|"
        r"rock[\s\-]*paper[\s\-]*scissors)"
        r"\s*[.?!]*$",
        re.IGNORECASE,
    )
    _MOVE_RE = re.compile(
        r"^(?:eu\s+)?(?:vou\s+de\s+|jog[oa]\s+|coloco\s+|escolho\s+|manda\s+)?"
        r"(pedra|papel|tesoura)\s*[.?!]*$",
        re.IGNORECASE,
    )
    _SCORE_RE = re.compile(
        r"^(?:qual\s+o\s+placar|mostra\s+(?:o\s+)?placar|placar|"
        r"como\s+(?:ta|est[áa])\s+o\s+jogo)\s*[.?!]*$",
        re.IGNORECASE,
    )
    _RESET_RE = re.compile(
        r"^(?:zera(?:r)?\s+(?:o\s+)?placar|novo\s+jogo|"
        r"reinicia(?:r)?\s+(?:o\s+)?jogo|reset(?:a(?:r)?)?(?:\s+o\s+jogo)?)"
        r"\s*[.?!]*$",
        re.IGNORECASE,
    )

    def __init__(self, face_matrix: Any = None, rng: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._face = face_matrix
        self._rng = rng if rng is not None else random.Random()
        self.score: dict[str, int] = {"aris": 0, "user": 0, "draw": 0}

    def can_handle(self, text: str) -> float:
        t = (text or "").strip()
        if not t:
            return 0.0
        if (
            self._MOVE_RE.match(t)
            or self._START_RE.match(t)
            or self._SCORE_RE.match(t)
            or self._RESET_RE.match(t)
        ):
            return 0.95
        return 0.0

    def handle(self, text: str, origin: Any = None) -> ReflexResult:
        t = (text or "").strip()

        if self._RESET_RE.match(t):
            self.score = {"aris": 0, "user": 0, "draw": 0}
            self._led_number(0)
            return ReflexResult(
                True, "Placar zerado. Novo jogo: pedra, papel ou tesoura?",
                0.95, self.name, "reset",
            )

        if self._SCORE_RE.match(t):
            return ReflexResult(True, self._score_text(), 0.95, self.name, "score")

        if self._START_RE.match(t):
            return ReflexResult(
                True,
                "Bora! Jogando pedra-papel-tesoura. "
                "Faça sua jogada: pedra, papel ou tesoura.",
                0.95, self.name, "start",
            )

        m = self._MOVE_RE.match(t)
        if not m:
            return ReflexResult(False)

        user_move = m.group(1).lower()
        aris_move = self._rng.choice(self.MOVES)

        # diff = 0 empate; 1 ARIS vence; 2 usuário vence
        diff = (self.MOVES.index(aris_move) - self.MOVES.index(user_move)) % 3
        if diff == 0:
            self.score["draw"] += 1
            code, verdict = 0, "Empate!"
        elif diff == 1:
            self.score["aris"] += 1
            code, verdict = 1, "Eu ganhei!"
        else:
            self.score["user"] += 1
            code, verdict = 2, "Você ganhou!"

        self._led_number(code)
        response = (
            f"{verdict} Você: {user_move} | Eu: {aris_move}. "
            f"{self._score_text()}"
        )
        return ReflexResult(True, response, 0.95, self.name, "round")

    def _score_text(self) -> str:
        return (
            f"Placar — você {self.score['user']}, "
            f"A.R.I.S. {self.score['aris']}, empates {self.score['draw']}."
        )

    def _led_number(self, value: int) -> None:
        """Envia o resultado da rodada para a matriz de LED (/num)."""
        if self._face is None:
            return
        try:
            self._face.show_number(value)
        except Exception:
            pass  # periférico opcional — nunca quebra a partida


class ReflexLayer:
    """Camada Reflex — orquestra os mini-agentes."""

    def __init__(
        self,
        agents: list[ReflexAgent] | None = None,
        security_gate: SecurityGate | None = None,
        memory: MemoryManager | None = None,
        analyzer: Any = None,
        face_matrix: Any = None,
        logger: Logger | None = None,
    ) -> None:
        self._logger = logger
        self._security = security_gate

        # Agentes padrão
        self._agents: list[ReflexAgent] = agents or [
            TimeReflexAgent(memory=memory, security_gate=security_gate, logger=logger),
            CalcReflexAgent(memory=memory, security_gate=security_gate, logger=logger),
            SystemStatusReflexAgent(analyzer=analyzer, memory=memory, security_gate=security_gate, logger=logger),
            MemoryLookupReflexAgent(memory=memory, security_gate=security_gate, logger=logger),
            JokenpoReflexAgent(face_matrix=face_matrix, memory=memory, security_gate=security_gate, logger=logger),
        ]

        # Ordenar por prioridade (maior primeiro)
        self._agents.sort(key=lambda a: a.priority, reverse=True)

    def process(self, text: str, origin: Any = None) -> ReflexResult | None:
        """Tenta processar via reflex agents. Retorna resultado se algum lidou com alta confiança."""
        if not text or not text.strip():
            return None

        for agent in self._agents:
            try:
                confidence = agent.can_handle(text)
                if confidence >= agent.min_confidence:
                    result = agent.handle(text, origin)
                    if result.handled and result.confidence >= agent.min_confidence:
                        if self._logger:
                            self._logger.debug(f"Reflex [{agent.name}]: {result.response[:60]} (conf={result.confidence:.2f})")
                        return result
            except Exception as e:
                if self._logger:
                    self._logger.debug(f"Reflex [{agent.name}] erro: {e}")

        return None

    def register_agent(self, agent: ReflexAgent) -> None:
        """Registra novo agente reflexivo (extensível via Plugin System)."""
        self._agents.append(agent)
        self._agents.sort(key=lambda a: a.priority, reverse=True)

    def get_agents(self) -> list[ReflexAgent]:
        return list(self._agents)


def build_reflex_layer(
    aris_instance,
    security_gate: SecurityGate | None = None,
    logger: Logger | None = None,
) -> ReflexLayer:
    """Constrói a ReflexLayer integrada ao Aris."""
    return ReflexLayer(
        security_gate=security_gate,
        memory=aris_instance._memory if hasattr(aris_instance, "_memory") else None,
        analyzer=aris_instance._analyzer if hasattr(aris_instance, "_analyzer") else None,
        face_matrix=getattr(aris_instance, "_face_matrix", None),
        logger=logger,
    )

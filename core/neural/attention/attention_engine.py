"""Attention Engine do A.R.I.S.

Determina o que merece processamento, atribuindo a cada evento uma
pontuação de prioridade determinística. Não usa machine learning para
calcular prioridade: o objetivo é confiabilidade e previsibilidade.

Fatores considerados:
    urgência, relevância, confiança, contexto, fonte, intenção do
    operador e custo computacional estimado.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.neural.events import (
    EVENT_HARDWARE,
    EVENT_SCREEN_CHANGED,
    EVENT_SYSTEM_ALERT,
    EVENT_TIMER_FINISHED,
    EVENT_USER_MESSAGE,
    EVENT_VOICE_COMMAND,
    Event,
)
from utils.logger import Logger


@dataclass
class AttentionScore:
    """Pontuação de atenção de um evento."""
    event: Event
    score: float = 0.0
    factors: dict[str, float] = field(default_factory=dict)

    def should_process(self, threshold: float = 0.15) -> bool:
        return self.score >= threshold

    def __repr__(self) -> str:
        return f"AttentionScore({self.event.event_type}, score={self.score:.2f})"


class AttentionEngine:
    """Motor de atenção determinístico."""

    # Peso padrão por fator
    WEIGHTS = {
        "urgency": 0.30,
        "relevance": 0.25,
        "confidence": 0.15,
        "source": 0.10,
        "user_intent": 0.20,
    }

    # Prioridade de origem vs custo de processamento
    SOURCE_BASELINE = {
        EVENT_VOICE_COMMAND: 0.9,
        EVENT_USER_MESSAGE: 0.8,
        EVENT_SYSTEM_ALERT: 0.95,
        EVENT_TIMER_FINISHED: 0.7,
        EVENT_HARDWARE: 0.6,
        EVENT_SCREEN_CHANGED: 0.3,
    }

    COST_PENALTY = 0.15  # penalidade máxima por custo alto

    @classmethod
    def with_defaults(cls, logger: Logger | None = None) -> AttentionEngine:
        return cls(logger=logger)

    def __init__(self, weights: dict[str, float] | None = None, logger: Logger | None = None) -> None:
        self._logger = logger
        self._weights = dict(self.WEIGHTS)
        if weights:
            # Redefine apenas os pesos fornecidos
            for key, value in weights.items():
                if key in self._weights:
                    self._weights[key] = value

    # ── Fatores ──────────────────────────────────────────────

    def _urgency(self, event: Event) -> float:
        """Urgência a partir da prioridade da fonte (0-100 → 0-1)."""
        return min(1.0, event.priority / 100.0)

    def _relevance(self, event: Event, user_intent: str | None = None) -> float:
        """Relevância em relação à intenção/tarefa corrente."""
        if event.event_type in (EVENT_USER_MESSAGE, EVENT_VOICE_COMMAND):
            return 1.0
        if user_intent:
            # Aproximação: evento falado na intenção corrente é relevante
            text = event.text.lower()
            intent_lower = user_intent.lower()
            if intent_lower in text:
                return 0.9
        return 0.5

    def _confidence(self, event: Event) -> float:
        return max(0.0, min(1.0, event.confidence))

    def _source(self, event: Event) -> float:
        return self.SOURCE_BASELINE.get(event.event_type, 0.4)

    def _cost(self, event: Event) -> float | None:
        """Custo computacional estimado (None = baixo/ignorar)."""
        payload_length = sum(len(str(v)) for v in event.payload.values())
        if event.event_type in (EVENT_SCREEN_CHANGED,) or payload_length > 2000:
            return self.COST_PENALTY
        return None

    # ── Pontuação ────────────────────────────────────────────

    def score(self, event: Event, user_intent: str | None = None) -> AttentionScore:
        """Calcula a pontuação de atenção de um evento."""
        urgency = self._urgency(event)
        relevance = self._relevance(event, user_intent)
        confidence = self._confidence(event)
        source = self._source(event)
        user_intent_factor = 1.0 if event.event_type in (
            EVENT_USER_MESSAGE, EVENT_VOICE_COMMAND, EVENT_SYSTEM_ALERT) else 0.5

        factors = {
            "urgency": urgency,
            "relevance": relevance,
            "confidence": confidence,
            "source": source,
            "user_intent": user_intent_factor,
        }

        score = (
            self._weights["urgency"] * urgency
            + self._weights["relevance"] * relevance
            + self._weights["confidence"] * confidence
            + self._weights["source"] * source
            + self._weights["user_intent"] * user_intent_factor
        )

        cost = self._cost(event)
        if cost is not None:
            score -= cost
            factors["cost_penalty"] = -cost

        return AttentionScore(event=event, score=round(max(0.0, min(1.0, score)), 3), factors=factors)

    def evaluate(self, events: list[Event], user_intent: str | None = None,
                 top: int = 5) -> list[AttentionScore]:
        """Avalia vários eventos, retornando os mais importantes."""
        scored = [self.score(e, user_intent) for e in events]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top]

    def should_process(self, event: Event, threshold: float = 0.15,
                       user_intent: str | None = None) -> AttentionScore:
        """Retorna o score e decide se o evento merece processamento."""
        return self.score(event, user_intent)

    def get_weights(self) -> dict[str, float]:
        return dict(self._weights)

"""Attention Engine do A.R.I.S.

Determina o que merece processamento, atribuindo a cada evento uma
pontuação de prioridade determinística. Não usa machine learning para
calcular prioridade: o objetivo é confiabilidade e previsibilidade.

Fatores considerados:
    urgência, relevância, confiança, contexto, fonte, intenção do
    operador e custo computacional estimado.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

from core.neural.events import (
    EVENT_CAMERA,
    EVENT_FILESYSTEM,
    EVENT_HARDWARE,
    EVENT_MICROPHONE,
    EVENT_NETWORK,
    EVENT_SCREEN_CHANGED,
    EVENT_SYSTEM_ALERT,
    EVENT_SYSTEM_METRIC,
    EVENT_TIMER_FINISHED,
    EVENT_USER_MESSAGE,
    EVENT_VISION_ERROR_DETECTED,
    EVENT_VISION_SCREEN_ANALYZED,
    EVENT_VISION_TEXT_DETECTED,
    EVENT_VOICE_COMMAND,
    Event,
)
from utils.logger import Logger


class AttentionLevel(StrEnum):
    """Níveis de atenção para um estímulo percebido.

    CRITICAL: exige resposta imediata.
    HIGH:     relevante e deve ser processado.
    NORMAL:   processável, mas não prioritário.
    LOW:      notável, ignora-se a menos que haja motivo.
    IGNORE:   ruído de fundo.
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    IGNORE = "IGNORE"


# Limiares de pontuação para cada nível (do mais alto para o mais baixo).
LEVEL_THRESHOLDS: tuple[tuple[AttentionLevel, float], ...] = (
    (AttentionLevel.CRITICAL, 0.75),
    (AttentionLevel.HIGH, 0.60),
    (AttentionLevel.NORMAL, 0.40),
    (AttentionLevel.LOW, 0.20),
)


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
        EVENT_CAMERA: 0.5,
        EVENT_MICROPHONE: 0.5,
        EVENT_FILESYSTEM: 0.45,
        EVENT_NETWORK: 0.5,
        EVENT_SYSTEM_METRIC: 0.45,
        EVENT_VISION_ERROR_DETECTED: 0.7,
        EVENT_VISION_SCREEN_ANALYZED: 0.5,
        EVENT_VISION_TEXT_DETECTED: 0.45,
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
        self._attention_log: deque[dict] = deque(maxlen=50)

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
        if event.event_type in (EVENT_SCREEN_CHANGED, EVENT_VISION_SCREEN_ANALYZED, EVENT_VISION_TEXT_DETECTED) or payload_length > 2000:
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
        score = self.score(event, user_intent)
        self.note(score)
        return score

    def get_weights(self) -> dict[str, float]:
        return dict(self._weights)

    # ── Classificação (níveis) ───────────────────────────────

    def level(self, score: float) -> AttentionLevel:
        """Traduz uma pontuação em nível de atenção."""
        for level, threshold in LEVEL_THRESHOLDS:
            if score >= threshold:
                return level
        return AttentionLevel.IGNORE

    def classify(self, event: Event, user_intent: str | None = None) -> tuple[AttentionScore, AttentionLevel]:
        """Pontua um evento e retorna (score, nível de atenção)."""
        scored = self.score(event, user_intent)
        return scored, self.level(scored.score)

    # ── Log de atenção (memória recente do que chamou atenção) ──

    def note(self, score: AttentionScore) -> None:
        """Registra uma pontuação no log de atenção."""
        self._attention_log.append({
            "event_id": score.event.event_id,
            "timestamp": score.event.timestamp,
            "event_type": score.event.event_type,
            "source": score.event.source,
            "score": score.score,
            "level": self.level(score.score).value,
            "priority": score.event.priority,
            "text": score.event.text[:120],
        })

    def recent_attention(self, limit: int = 10) -> list[dict]:
        """Registros de atenção mais recentes (mais novos primeiro)."""
        return list(self._attention_log)[-limit:][::-1]

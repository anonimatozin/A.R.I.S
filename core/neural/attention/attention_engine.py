"""Attention Engine do A.R.I.S.

Determina o que merece processamento, atribuindo a cada evento uma
pontuação de prioridade determinística. Não usa machine learning para
calcular prioridade: o objetivo é confiabilidade e previsibilidade.

Fatores considerados:
    urgência, relevância, confiança, contexto, fonte, intenção do
    operador, custo computacional estimado, importância semântica,
    novidade, repetição e impacto.

Agregação:
    Eventos repetitivos (mesmo tipo, texto idêntico, janela curta)
    são fundidos em um único score representativo, evitando processamento
    desnecessário.
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


@dataclass
class AggregatedEvent:
    """Resultado da agregação de eventos repetitivos."""
    representative: Event
    count: int = 1
    events: list[Event] = field(default_factory=list)
    score: AttentionScore | None = None
    level: AttentionLevel = AttentionLevel.IGNORE


class AttentionEngine:
    """Motor de atenção determinístico."""

    # Pesos padrão por fator (soma ~1.0 com os novos fatores)
    WEIGHTS = {
        "urgency": 0.25,
        "relevance": 0.20,
        "confidence": 0.10,
        "source": 0.08,
        "user_intent": 0.15,
        "importance": 0.10,
        "novelty": 0.07,
        "repetition": 0.05,
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

    # Parâmetros de agregação
    AGGREGATION_WINDOW_SECONDS = 30.0
    AGGREGATION_TEXT_THRESHOLD = 0.95  # similaridade mínima para considerar "mesmo texto"

    @classmethod
    def with_defaults(cls, logger: Logger | None = None) -> AttentionEngine:
        return cls(logger=logger)

    def __init__(self, weights: dict[str, float] | None = None, logger: Logger | None = None) -> None:
        self._logger = logger
        self._weights = dict(self.WEIGHTS)
        if weights:
            for key, value in weights.items():
                if key in self._weights:
                    self._weights[key] = value
        self._attention_log: deque[dict] = deque(maxlen=50)
        self._recent_event_keys: deque[tuple[str, str]] = deque(maxlen=100)

    # ── Fatores originais ─────────────────────────────────────

    def _urgency(self, event: Event) -> float:
        """Urgência a partir da prioridade da fonte (0-100 → 0-1)."""
        return min(1.0, event.priority / 100.0)

    def _relevance(self, event: Event, user_intent: str | None = None) -> float:
        """Relevância em relação à intenção/tarefa corrente."""
        if event.event_type in (EVENT_USER_MESSAGE, EVENT_VOICE_COMMAND):
            return 1.0
        if user_intent:
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
        if event.event_type in (
            EVENT_SCREEN_CHANGED, EVENT_VISION_SCREEN_ANALYZED, EVENT_VISION_TEXT_DETECTED
        ) or payload_length > 2000:
            return self.COST_PENALTY
        return None

    # ── Novos fatores ─────────────────────────────────────────

    def _importance(self, event: Event) -> float:
        """Importância semântica extraída do payload.

        Prioridade 100 → 1.0, prioridade 50 → 0.5, etc.
        Eventos de alerta/sistema recebem bonus.
        """
        base = min(1.0, event.priority / 100.0)
        if event.event_type == EVENT_SYSTEM_ALERT:
            base = min(1.0, base + 0.3)
        elif event.event_type in (EVENT_VISION_ERROR_DETECTED, EVENT_HARDWARE):
            base = min(1.0, base + 0.15)
        return base

    def _novelty(self, event: Event) -> float:
        """Novidade: quão novo é este tipo de evento na janela recente.

        1.0 = completamente novo, 0.0 = visto muitas vezes recentemente.
        """
        key = (event.event_type, event.text[:60])
        count = sum(1 for k in self._recent_event_keys if k == key)
        if count == 0:
            return 1.0
        if count == 1:
            return 0.6
        if count <= 3:
            return 0.3
        return 0.1

    def _repetition(self, event: Event) -> float:
        """Penalidade por repetição exata (mesmo tipo + texto idêntico).

        Retorna 1.0 (sem penalidade) ou 0.0 (penalidade máxima).
        Eventos idênticos consecutivos recebem penalidade alta.
        """
        key = (event.event_type, event.text[:60])
        if not self._recent_event_keys:
            return 1.0
        last_key = self._recent_event_keys[-1]
        if last_key == key:
            return 0.0
        recent_count = sum(1 for k in self._recent_event_keys if k == key)
        if recent_count >= 2:
            return 0.2
        return 1.0

    # ── Pontuação ────────────────────────────────────────────

    def score(self, event: Event, user_intent: str | None = None) -> AttentionScore:
        """Calcula a pontuação de atenção de um evento (puro, sem efeito colateral)."""
        urgency = self._urgency(event)
        relevance = self._relevance(event, user_intent)
        confidence = self._confidence(event)
        source = self._source(event)
        user_intent_factor = 1.0 if event.event_type in (
            EVENT_USER_MESSAGE, EVENT_VOICE_COMMAND, EVENT_SYSTEM_ALERT) else 0.5
        importance = self._importance(event)
        novelty = self._novelty(event)
        repetition = self._repetition(event)

        factors = {
            "urgency": urgency,
            "relevance": relevance,
            "confidence": confidence,
            "source": source,
            "user_intent": user_intent_factor,
            "importance": importance,
            "novelty": novelty,
            "repetition": repetition,
        }

        score = (
            self._weights["urgency"] * urgency
            + self._weights["relevance"] * relevance
            + self._weights["confidence"] * confidence
            + self._weights["source"] * source
            + self._weights["user_intent"] * user_intent_factor
            + self._weights["importance"] * importance
            + self._weights["novelty"] * novelty
            + self._weights["repetition"] * repetition
        )

        cost = self._cost(event)
        if cost is not None:
            score -= cost
            factors["cost_penalty"] = -cost

        return AttentionScore(
            event=event,
            score=round(max(0.0, min(1.0, score)), 3),
            factors=factors,
        )

    def evaluate(self, events: list[Event], user_intent: str | None = None,
                 top: int = 5) -> list[AttentionScore]:
        """Avalia vários eventos, retornando os mais importantes."""
        scored = [self.score(e, user_intent) for e in events]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top]

    def should_process(self, event: Event, threshold: float = 0.15,
                       user_intent: str | None = None) -> AttentionScore:
        """Retorna o score e decide se o evento merece processamento.

        Registra o evento (observe) para novelty/repetition e loga no
        attention_log. Chamar apenas uma vez por evento real, no entry
        point do pipeline.
        """
        scored = self.score(event, user_intent)
        self.observe(scored)
        return scored

    def observe(self, scored: AttentionScore) -> None:
        """Registra um evento observado: atualiza novelty/repetition + log.

        Chamar UMA VEZ por evento real, no ponto onde o evento entra
        no sistema (ex: NeuralCore.process, AttentionBridge).
        Não chamar em queries sob demanda (workspace, evaluate, classify).
        """
        self._register_event(scored.event)
        self.note(scored)

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

    # ── Agregação de eventos repetitivos ──────────────────────

    def aggregate_events(
        self,
        events: list[Event],
        user_intent: str | None = None,
    ) -> list[AggregatedEvent]:
        """Agrupa eventos repetitivos e retorna representantes.

        Eventos do mesmo tipo com texto muito similar (>= 95%) dentro
        de uma janela de 30 segundos são fundidos em um único
        AggregatedEvent com contagem.
        """
        if not events:
            return []

        aggregated: list[AggregatedEvent] = []
        used: set[int] = set()

        for i, event in enumerate(events):
            if i in used:
                continue

            group: list[Event] = [event]
            for j in range(i + 1, len(events)):
                if j in used:
                    continue
                other = events[j]
                if self._are_similar(event, other):
                    group.append(other)
                    used.add(j)

            used.add(i)

            if len(group) == 1:
                score, lvl = self.classify(event, user_intent)
                aggregated.append(AggregatedEvent(
                    representative=event,
                    count=1,
                    events=group,
                    score=score,
                    level=lvl,
                ))
            else:
                best = max(group, key=lambda e: e.priority)
                score, lvl = self.classify(best, user_intent)
                aggregated.append(AggregatedEvent(
                    representative=best,
                    count=len(group),
                    events=group,
                    score=score,
                    level=lvl,
                ))

        return aggregated

    def _are_similar(self, a: Event, b: Event) -> bool:
        """Dois eventos são similares para fins de agregação."""
        if a.event_type != b.event_type:
            return False
        text_a = a.text[:80].lower().strip()
        text_b = b.text[:80].lower().strip()
        if text_a == text_b:
            return True
        if not text_a or not text_b:
            return a.event_type == b.event_type
        shorter = min(len(text_a), len(text_b))
        if shorter == 0:
            return True
        matches = sum(1 for ca, cb in zip(text_a, text_b) if ca == cb)
        return (matches / shorter) >= self.AGGREGATION_TEXT_THRESHOLD

    # ── Registro de eventos vistos (para novelty/repetition) ──

    def _register_event(self, event: Event) -> None:
        """Registra evento visto para cálculo de novidade/repetição."""
        key = (event.event_type, event.text[:60])
        self._recent_event_keys.append(key)

    # ── Log de atenção ────────────────────────────────────────

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

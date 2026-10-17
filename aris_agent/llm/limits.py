"""Limitador de taxa por provedor (requisições/minuto, tokens/minuto e dia).

Relógio injetável: ``clock`` (monotônico, para esperas) e ``wall`` (época,
para a janela de dia). Os testes injetam relógios falsos — nenhum ``sleep``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from .settings import RateLimits

log = logging.getLogger("aris.agent.llm.limits")

_MINUTE = 60.0


def day_key(timestamp: float) -> str:
    """Chave do dia local (``YYYY-MM-DD``) para uma época em segundos."""
    return datetime.fromtimestamp(timestamp).date().isoformat()


def seconds_until_next_day(timestamp: float) -> float:
    """Segundos até a próxima meia-noite local a partir de uma época."""
    moment = datetime.fromtimestamp(timestamp)
    midnight = (moment + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(0.0, (midnight - moment).total_seconds())


@dataclass
class _MinuteWindow:
    """Contadores da janela fixa de minuto de um provedor."""

    window: int
    requests: int
    tokens: int


class RateLimiter:
    """Janelas fixas de minuto + janela de dia, por provedor."""

    def __init__(
        self,
        *,
        clock=None,
        wall=None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._wall = wall or time.time
        self._lock = threading.Lock()
        self._limits: dict[str, RateLimits] = {}
        self._minute: dict[str, _MinuteWindow] = {}
        self._day: dict[str, tuple[str, int]] = {}

    def set_limits(self, name: str, limits: RateLimits | None) -> None:
        with self._lock:
            self._limits[name] = limits or RateLimits()

    def _limits_for(self, name: str) -> RateLimits:
        return self._limits.get(name) or RateLimits()

    def _minute_counters(self, name: str, now: float) -> _MinuteWindow:
        window = int(now // _MINUTE)
        state = self._minute.get(name)
        if state is None or state.window != window:
            state = _MinuteWindow(window=window, requests=0, tokens=0)
            self._minute[name] = state
        return state

    def _day_counters(self, name: str) -> tuple[str, int]:
        key = day_key(self._wall())
        state = self._day.get(name)
        if state is None or state[0] != key:
            state = (key, 0)
            self._day[name] = state
        return state

    def wait_time(self, name: str, tokens: int = 0) -> float:
        """Segundos até o pedido caber no orçamento; ``0.0`` = pode ir agora.

        Pedido maior que a janela não bloqueia (esperar não resolveria).
        """
        tokens = max(0, int(tokens))
        with self._lock:
            limits = self._limits_for(name)
            now = self._clock()
            waits: list[float] = []
            minute = self._minute_counters(name, now)
            minute_wait = (minute.window + 1) * _MINUTE - now

            rpm = limits.requests_per_minute
            if rpm and minute.requests >= rpm:
                waits.append(minute_wait)

            tpm = limits.tokens_per_minute
            if tpm and tokens < tpm and minute.tokens + tokens > tpm:
                waits.append(minute_wait)

            tpd = limits.tokens_per_day
            if tpd and tokens < tpd:
                day_key_value, day_tokens = self._day_counters(name)
                if day_tokens + tokens > tpd:
                    waits.append(seconds_until_next_day(self._wall()))
                    log.debug(
                        "limite diário do provedor %r atingido (janela %s)",
                        name,
                        day_key_value,
                    )

        return max(waits) if waits else 0.0

    def record_request(self, name: str) -> None:
        with self._lock:
            now = self._clock()
            minute = self._minute_counters(name, now)
            minute.requests += 1

    def record_tokens(self, name: str, tokens: int) -> None:
        tokens = max(0, int(tokens))
        with self._lock:
            now = self._clock()
            minute = self._minute_counters(name, now)
            minute.tokens += tokens
            key, day_tokens = self._day_counters(name)
            self._day[name] = (key, day_tokens + tokens)

    def seed_day_tokens(self, name: str, tokens: int) -> None:
        """Soma tokens já usados hoje (vindos do arquivo de estatísticas)."""
        tokens = max(0, int(tokens))
        if not tokens:
            return
        with self._lock:
            key, day_tokens = self._day_counters(name)
            self._day[name] = (key, day_tokens + tokens)

    def snapshot(self) -> dict:
        """Contadores atuais por provedor (para ``router.stats()``)."""
        with self._lock:
            now = self._clock()
            out: dict[str, dict] = {}
            for name in sorted(set(self._limits) | set(self._minute) | set(self._day)):
                minute = self._minute_counters(name, now)
                key, day_tokens = self._day_counters(name)
                out[name] = {
                    "requests_minute": minute.requests,
                    "tokens_minute": minute.tokens,
                    "day": key,
                    "tokens_day": day_tokens,
                }
            return out

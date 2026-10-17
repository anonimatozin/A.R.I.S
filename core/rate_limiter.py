"""Rate Limiter do A.R.I.S.

Controle de taxa de chamadas para APIs externas.
Previne estouro de quota em uso intenso.
"""

import time
from collections import deque


class RateLimiter:
    """Limitador de taxa de chamadas.

    Usa janela deslizante para contar chamadas por período.

    Exemplo:
        limiter = RateLimiter(max_calls=30, period_seconds=60)
        if limiter.allow():
            # fazer chamada API
        else:
            # quota estourada, usar fallback
    """

    def __init__(self, max_calls: int, period_seconds: int, name: str = "default"):
        self.max_calls = max_calls
        self.period = period_seconds
        self.name = name
        self._calls: deque = deque()
        self._blocked_until: float | None = None

    def allow(self) -> bool:
        """Verifica se uma chamada é permitida."""
        now = time.time()

        # Bloqueio temporal (após rate limit hit)
        if self._blocked_until and now < self._blocked_until:
            return False
        self._blocked_until = None

        # Limpar chamadas antigas da janela
        while self._calls and now - self._calls[0] > self.period:
            self._calls.popleft()

        if len(self._calls) < self.max_calls:
            self._calls.append(now)
            return True

        # Rate limit atingido — bloquear por 10 segundos
        self._blocked_until = now + 10
        return False

    @property
    def remaining(self) -> int:
        """Chamadas restantes na janela atual."""
        now = time.time()
        while self._calls and now - self._calls[0] > self.period:
            self._calls.popleft()
        return max(0, self.max_calls - len(self._calls))

    @property
    def is_limited(self) -> bool:
        """Se está atualmente bloqueado."""
        if self._blocked_until and time.time() < self._blocked_until:
            return True
        return False

    def get_status(self) -> dict:
        """Retorna status do rate limiter."""
        now = time.time()
        while self._calls and now - self._calls[0] > self.period:
            self._calls.popleft()
        return {
            "name": self.name,
            "max_calls": self.max_calls,
            "period_seconds": self.period,
            "used": len(self._calls),
            "remaining": self.remaining,
            "is_limited": self.is_limited,
        }

    def __repr__(self) -> str:
        return f"RateLimiter({self.name}: {self.remaining}/{self.max_calls} em {self.period}s)"


# ── Limiters pré-configurados ───────────────────────────────

# Groq: tier gratuito permite ~30 req/min
groq_limiter = RateLimiter(max_calls=30, period_seconds=60, name="groq")

# SerpAPI: tier gratuito permite ~100 req/mês (mas ~5/min é seguro)
serpapi_limiter = RateLimiter(max_calls=5, period_seconds=60, name="serpapi")

# Gemini (se configurado): 60 req/min no tier gratuito
gemini_limiter = RateLimiter(max_calls=60, period_seconds=60, name="gemini")

# Ollama local: sem limite real, mas evitar sobrecarga
ollama_limiter = RateLimiter(max_calls=20, period_seconds=60, name="ollama")

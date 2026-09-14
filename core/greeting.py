"""Saudação contextual e clima do A.R.I.S.

Fornece saudação baseada no horário (timezone configurável) e
informações de clima via Open-Meteo (grátis, sem API key).

Dependências:
- zoneinfo (stdlib) para timezone
- requests (já no projeto) para HTTP
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

# ── Constants ────────────────────────────────────────────────

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_TIMEOUT = 5  # seconds
_WEATHER_CACHE_TTL = 1800  # 30 minutes

# WMO Weather interpretation codes → pt-BR
# https://open-meteo.com/en/docs#weathervariables
_WMO_CODES: dict[int, str] = {
    0: "céu limpo",
    1: "céu quase limpo",
    2: "parcialmente nublado",
    3: "nublado",
    45: "nevoeiro",
    48: "nevoeiro gelado",
    51: "chuva leve",
    53: "chuva moderada",
    55: "chuva forte",
    56: "chuva gelada leve",
    57: "chuva gelada forte",
    61: "chuva fraca",
    63: "chuva moderada",
    65: "chuva forte",
    66: "chuva gelada fraca",
    67: "chuva gelada forte",
    71: "neve fraca",
    73: "neve moderada",
    75: "neve forte",
    77: "granizo",
    80: "pancadas de chuva leves",
    81: "pancadas de chuva moderadas",
    82: "pancadas de chuva fortes",
    85: "pancadas de neve leves",
    86: "pancadas de neve fortes",
    95: "tempestade",
    96: "tempestade com granizo leve",
    99: "tempestade com granizo forte",
}


# ── Weather Cache ────────────────────────────────────────────


class _WeatherCache:
    """Cache em memória com TTL para dados de clima."""

    def __init__(self, ttl: int = _WEATHER_CACHE_TTL) -> None:
        self._ttl = ttl
        self._data: dict[str, Any] | None = None
        self._timestamp: float = 0.0

    def get(self) -> dict[str, Any] | None:
        if self._data is None:
            return None
        if time.time() - self._timestamp > self._ttl:
            return None
        return self._data

    def set(self, data: dict[str, Any]) -> None:
        self._data = data
        self._timestamp = time.time()


# ── Greeting Service ────────────────────────────────────────


class GreetingService:
    """Serviço de saudação contextual + clima.

    - get_greeting(now) retorna "Bom dia"/"Boa tarde"/"Boa noite"
    - get_weather() retorna dados de clima ou None (fallback)
    - compose_greeting(now) combina saudação + clima
    """

    def __init__(
        self,
        timezone: str = "America/Sao_Paulo",
        latitude: float = -23.55,
        longitude: float = -46.63,
        city: str = "São Paulo",
        cooldown_hours: int = 4,
        logger: Any = None,
    ) -> None:
        self._tz = ZoneInfo(timezone)
        self._lat = latitude
        self._lon = longitude
        self._city = city
        self._cooldown_hours = cooldown_hours
        self._logger = logger
        self._weather_cache = _WeatherCache()
        self._last_greeted_at: datetime | None = None

    # ── Saudação ─────────────────────────────────────────────

    def get_greeting(self, now: datetime | None = None) -> str:
        """Retorna saudação baseada no horário.

        Limites configuráveis (valores default):
            05:00–11:59 → "Bom dia"
            12:00–17:59 → "Boa tarde"
            18:00–04:59 → "Boa noite"
        """
        if now is None:
            now = datetime.now(self._tz)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=self._tz)

        hour = now.hour
        if 5 <= hour < 12:
            return "Bom dia"
        elif 12 <= hour < 18:
            return "Boa tarde"
        else:
            return "Boa noite"

    def should_greet(self, now: datetime | None = None) -> bool:
        """Verifica se deve saudar (cooldown-based).

        Retorna True se:
        - Nunca saudou, OU
        - Última saudação foi há mais de cooldown_hours
        """
        if self._last_greeted_at is None:
            return True
        if now is None:
            now = datetime.now(self._tz)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=self._tz)
        elapsed = now - self._last_greeted_at
        return elapsed > timedelta(hours=self._cooldown_hours)

    def register_greeting(self, now: datetime | None = None) -> None:
        """Registra que uma saudação foi enviada."""
        if now is None:
            now = datetime.now(self._tz)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=self._tz)
        self._last_greeted_at = now

    # ── Clima ────────────────────────────────────────────────

    def get_weather(self) -> dict[str, Any] | None:
        """Obtém clima atual via Open-Meteo.

        Returns:
            dict com keys: temperature, humidity, description, wind_speed
            ou None se falhar (sem internet, timeout, etc.)
        """
        cached = self._weather_cache.get()
        if cached is not None:
            return cached

        try:
            resp = requests.get(
                _OPEN_METEO_URL,
                params={
                    "latitude": self._lat,
                    "longitude": self._lon,
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                    "timezone": "auto",
                },
                timeout=_OPEN_METEO_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            current = data.get("current", {})

            weather = {
                "temperature": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
                "description": _WMO_CODES.get(
                    current.get("weather_code", -1), "indefinido"
                ),
                "wind_speed": current.get("wind_speed_10m"),
            }
            self._weather_cache.set(weather)
            return weather

        except Exception as e:
            if self._logger:
                self._logger.debug(f"GreetingService: falha ao obter clima ({e})")
            return None

    # ── Composição ───────────────────────────────────────────

    def compose_greeting(
        self,
        now: datetime | None = None,
        include_weather: bool = True,
    ) -> str:
        """Compõe saudação final: saudação + clima (se disponível).

        Formato: "Bom dia! Agora em {cidade} estão {temp}°C com {condição}."
        Fallback sem clima: "Bom dia!"
        """
        greeting = self.get_greeting(now)
        parts = [greeting]

        if include_weather:
            weather = self.get_weather()
            if weather and weather.get("temperature") is not None:
                temp = weather["temperature"]
                desc = weather["description"]
                parts.append(
                    f"Agora em {self._city} estão {temp}°C com {desc}."
                )

        return " ".join(parts)

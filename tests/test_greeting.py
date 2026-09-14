"""Testes do GreetingService (saudação contextual + clima).

Cobre:
- Limites de horário (8 boundary tests)
- Timezone explícito
- Lógica de cooldown (não saudar de novo em < 4h)
- Parser do Open-Meteo com JSON fixture
- Cache: segunda chamada dentro do TTL não faz request
- Timeout/falha HTTP → None, sem exception
- Composição final: saudação com clima e sem clima
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from core.greeting import GreetingService, _WeatherCache, _WMO_CODES


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def service():
    return GreetingService(
        timezone="America/Sao_Paulo",
        latitude=-23.55,
        longitude=-46.63,
        city="São Paulo",
        cooldown_hours=4,
    )


@pytest.fixture
def tz():
    return ZoneInfo("America/Sao_Paulo")


# ── Saudação por horário ────────────────────────────────────

class TestGreetingByHour:
    def test_04_59_is_noite(self, service, tz):
        now = datetime(2026, 9, 13, 4, 59, tzinfo=tz)
        assert service.get_greeting(now) == "Boa noite"

    def test_05_00_is_bom_dia(self, service, tz):
        now = datetime(2026, 9, 13, 5, 0, tzinfo=tz)
        assert service.get_greeting(now) == "Bom dia"

    def test_11_59_is_bom_dia(self, service, tz):
        now = datetime(2026, 9, 13, 11, 59, tzinfo=tz)
        assert service.get_greeting(now) == "Bom dia"

    def test_12_00_is_boa_tarde(self, service, tz):
        now = datetime(2026, 9, 13, 12, 0, tzinfo=tz)
        assert service.get_greeting(now) == "Boa tarde"

    def test_17_59_is_boa_tarde(self, service, tz):
        now = datetime(2026, 9, 13, 17, 59, tzinfo=tz)
        assert service.get_greeting(now) == "Boa tarde"

    def test_18_00_is_boa_noite(self, service, tz):
        now = datetime(2026, 9, 13, 18, 0, tzinfo=tz)
        assert service.get_greeting(now) == "Boa noite"

    def test_23_59_is_boa_noite(self, service, tz):
        now = datetime(2026, 9, 13, 23, 59, tzinfo=tz)
        assert service.get_greeting(now) == "Boa noite"

    def test_00_00_is_boa_noite(self, service, tz):
        now = datetime(2026, 9, 13, 0, 0, tzinfo=tz)
        assert service.get_greeting(now) == "Boa noite"


# ── Timezone ────────────────────────────────────────────────

class TestTimezone:
    def test_explicit_timezone(self):
        # 14:00 em São Paulo = 17:00 em UTC (horário de verão) ou 18:00 (padrão)
        svc = GreetingService(timezone="America/Sao_Paulo")
        now = datetime(2026, 9, 13, 14, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        greeting = svc.get_greeting(now)
        assert greeting == "Boa tarde"

    def test_naive_datetime_gets_timezone(self, service, tz):
        now = datetime(2026, 9, 13, 14, 0)  # naive
        greeting = service.get_greeting(now)
        # Should be treated as São Paulo time
        assert greeting == "Boa tarde"


# ── Cooldown ────────────────────────────────────────────────

class TestCooldown:
    def test_first_greeting_always_allowed(self, service):
        assert service.should_greet()

    def test_within_cooldown_returns_false(self, service, tz):
        now = datetime(2026, 9, 13, 10, 0, tzinfo=tz)
        service.register_greeting(now)
        # 2 hours later — still within 4h cooldown
        later = now + timedelta(hours=2)
        assert not service.should_greet(later)

    def test_after_cooldown_returns_true(self, service, tz):
        now = datetime(2026, 9, 13, 10, 0, tzinfo=tz)
        service.register_greeting(now)
        # 5 hours later — past 4h cooldown
        later = now + timedelta(hours=5)
        assert service.should_greet(later)

    def test_exact_cooldown_boundary(self, service, tz):
        now = datetime(2026, 9, 13, 10, 0, tzinfo=tz)
        service.register_greeting(now)
        # Exactly 4 hours — not yet (> not >=)
        later = now + timedelta(hours=4)
        assert not service.should_greet(later)
        # 4 hours + 1 second — allowed
        later2 = now + timedelta(hours=4, seconds=1)
        assert service.should_greet(later2)

    def test_register_greeting_updates_timestamp(self, service, tz):
        now = datetime(2026, 9, 13, 10, 0, tzinfo=tz)
        assert service._last_greeted_at is None
        service.register_greeting(now)
        assert service._last_greeted_at == now


# ── Weather Cache ───────────────────────────────────────────

class TestWeatherCache:
    def test_empty_cache_returns_none(self):
        cache = _WeatherCache(ttl=60)
        assert cache.get() is None

    def test_set_and_get(self):
        cache = _WeatherCache(ttl=60)
        data = {"temperature": 22.0}
        cache.set(data)
        assert cache.get() == data

    def test_cache_expires(self):
        cache = _WeatherCache(ttl=0)
        cache.set({"temperature": 22.0})
        # Manually backdate the timestamp to force expiration
        cache._timestamp = time.time() - 1
        assert cache.get() is None

    def test_cache_within_ttl(self):
        cache = _WeatherCache(ttl=3600)
        cache.set({"temperature": 22.0})
        assert cache.get() == {"temperature": 22.0}


# ── Weather Parser ──────────────────────────────────────────

class TestWeatherParser:
    def test_wmo_code_0_is_clear(self):
        assert _WMO_CODES[0] == "céu limpo"

    def test_wmo_code_61_is_rain(self):
        assert _WMO_CODES[61] == "chuva fraca"

    def test_wmo_code_95_is_storm(self):
        assert _WMO_CODES[95] == "tempestade"

    def test_unknown_code_returns_indefinido(self):
        assert _WMO_CODES.get(999, "indefinido") == "indefinido"

    @patch("core.greeting.requests.get")
    def test_get_weather_parses_response(self, mock_get, service):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "current": {
                "temperature_2m": 22.5,
                "relative_humidity_2m": 65,
                "weather_code": 0,
                "wind_speed_10m": 12.3,
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        weather = service.get_weather()
        assert weather is not None
        assert weather["temperature"] == 22.5
        assert weather["humidity"] == 65
        assert weather["description"] == "céu limpo"
        assert weather["wind_speed"] == 12.3

    @patch("core.greeting.requests.get")
    def test_get_weather_http_error_returns_none(self, mock_get, service):
        mock_get.side_effect = Exception("connection error")
        assert service.get_weather() is None

    @patch("core.greeting.requests.get")
    def test_get_weather_timeout_returns_none(self, mock_get, service):
        import requests
        mock_get.side_effect = requests.Timeout("timeout")
        assert service.get_weather() is None


# ── Weather Cache + HTTP ────────────────────────────────────

class TestWeatherCacheIntegration:
    @patch("core.greeting.requests.get")
    def test_second_call_uses_cache(self, mock_get, service):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "current": {
                "temperature_2m": 22.0,
                "relative_humidity_2m": 60,
                "weather_code": 1,
                "wind_speed_10m": 10.0,
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # First call — hits HTTP
        w1 = service.get_weather()
        assert mock_get.call_count == 1

        # Second call — uses cache
        w2 = service.get_weather()
        assert mock_get.call_count == 1  # still 1
        assert w1 == w2


# ── Composição Final ────────────────────────────────────────

class TestComposeGreeting:
    @patch("core.greeting.requests.get")
    def test_compose_with_weather(self, mock_get, service, tz):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "current": {
                "temperature_2m": 25.0,
                "relative_humidity_2m": 70,
                "weather_code": 2,
                "wind_speed_10m": 8.0,
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        now = datetime(2026, 9, 13, 10, 0, tzinfo=tz)
        result = service.compose_greeting(now, include_weather=True)
        assert "Bom dia" in result
        assert "25" in result
        assert "São Paulo" in result
        assert "parcialmente nublado" in result

    def test_compose_without_weather(self, service, tz):
        now = datetime(2026, 9, 13, 14, 0, tzinfo=tz)
        result = service.compose_greeting(now, include_weather=False)
        assert result == "Boa tarde"

    @patch("core.greeting.requests.get")
    def test_compose_fallback_no_weather_available(self, mock_get, service, tz):
        mock_get.side_effect = Exception("offline")
        now = datetime(2026, 9, 13, 10, 0, tzinfo=tz)
        result = service.compose_greeting(now, include_weather=True)
        # Should still have greeting even without weather
        assert result == "Bom dia"


# ── Integração should_greet + compose ───────────────────────

class TestFullFlow:
    def test_first_greeting_then_cooldown(self, service, tz):
        now1 = datetime(2026, 9, 13, 10, 0, tzinfo=tz)

        # First interaction — should greet
        assert service.should_greet(now1)
        greeting1 = service.compose_greeting(now1, include_weather=False)
        assert "Bom dia" in greeting1
        service.register_greeting(now1)

        # Second interaction 1 hour later — should NOT greet
        now2 = now1 + timedelta(hours=1)
        assert not service.should_greet(now2)

        # Third interaction 5 hours later — should greet again
        now3 = now1 + timedelta(hours=5)
        assert service.should_greet(now3)

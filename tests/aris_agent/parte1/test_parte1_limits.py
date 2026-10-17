"""Testes do limitador de taxa, circuit breaker e estatísticas (relógio falso)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from aris_agent.contract.types import Usage
from aris_agent.llm.circuit import CircuitBreaker
from aris_agent.llm.limits import RateLimiter, day_key, seconds_until_next_day
from aris_agent.llm.settings import RateLimits
from aris_agent.llm.stats import UsageStats


class FakeClock:
    """Relógio monotônico falso: avança só quando mandam."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeWall:
    """Relógio de época falso (para a janela de dia)."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------- limitador


def test_rpm_bloqueia_na_janela_e_libera_na_seguinte() -> None:
    clock = FakeClock(60.0)  # exatamente no início de um minuto
    limiter = RateLimiter(clock=clock, wall=FakeWall())
    limiter.set_limits("a", RateLimits(requests_per_minute=2))

    assert limiter.wait_time("a") == 0.0
    limiter.record_request("a")
    limiter.record_request("a")
    esperado = limiter.wait_time("a")
    assert esperado == pytest.approx(60.0)
    clock.advance(esperado)
    assert limiter.wait_time("a") == 0.0


def test_tpm_observa_quantidade_de_tokens() -> None:
    limiter = RateLimiter(clock=FakeClock(0.0), wall=FakeWall())
    limiter.set_limits("a", RateLimits(tokens_per_minute=100))

    limiter.record_tokens("a", 90)
    assert limiter.wait_time("a", 5) == 0.0
    assert limiter.wait_time("a", 20) == pytest.approx(60.0)


def test_pedido_maior_que_a_janela_nao_bloqueia() -> None:
    limiter = RateLimiter(clock=FakeClock(0.0), wall=FakeWall())
    limiter.set_limits("a", RateLimits(tokens_per_minute=100, tokens_per_day=100))
    assert limiter.wait_time("a", 500) == 0.0


def test_tpd_com_relógio_de_parede_e_seed() -> None:
    wall = FakeWall()
    limiter = RateLimiter(clock=FakeClock(0.0), wall=wall)
    limiter.set_limits("a", RateLimits(tokens_per_day=1000))
    limiter.seed_day_tokens("a", 950)

    assert limiter.wait_time("a", 100) > 0
    assert limiter.wait_time("a", 100) == pytest.approx(
        seconds_until_next_day(wall()), abs=1.0
    )
    assert limiter.wait_time("a", 10) == 0.0

    wall.advance(86_400)  # passou o dia
    assert limiter.wait_time("a", 100) == 0.0


def test_sem_limites_sempre_libera() -> None:
    limiter = RateLimiter(clock=FakeClock(), wall=FakeWall())
    limiter.record_request("a")
    limiter.record_tokens("a", 10_000)
    assert limiter.wait_time("a", 10_000) == 0.0
    assert limiter.snapshot() == {
        "a": {"requests_minute": 1, "tokens_minute": 10_000, "day": day_key(1_700_000_000.0), "tokens_day": 10_000}
    }


def test_janela_de_dia_muda_na_meia_noite_local() -> None:
    agora = datetime.now()
    amanha = (agora + timedelta(days=1)).date().isoformat()
    assert day_key((agora + timedelta(hours=23)).timestamp()) != day_key(agora.timestamp())
    assert day_key((agora + timedelta(days=1)).timestamp()) == amanha


# ---------------------------------------------------------- circuit breaker


def test_circuit_abre_no_limite_e_libera_prova() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(clock=clock, failure_threshold=3, cooldown_s=30.0)

    assert breaker.allow("a") is True
    breaker.failure("a")
    breaker.failure("a")
    assert breaker.state("a") == "closed"
    breaker.failure("a")
    assert breaker.state("a") == "open"
    assert breaker.allow("a") is False

    clock.advance(30.0)
    assert breaker.state("a") == "half_open"
    assert breaker.allow("a") is True  # uma única prova
    assert breaker.allow("a") is False  # só uma por janela

    breaker.success("a")
    assert breaker.state("a") == "closed"
    assert breaker.allow("a") is True


def test_prova_com_falha_reabre_imediatamente() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(clock=clock, failure_threshold=1, cooldown_s=10.0)
    breaker.failure("a")
    clock.advance(10.0)
    assert breaker.allow("a") is True
    breaker.failure("a")  # prova falhou
    assert breaker.state("a") == "open"
    assert breaker.allow("a") is False


def test_auth_abre_de_imediato() -> None:
    breaker = CircuitBreaker(clock=FakeClock(), failure_threshold=5, cooldown_s=60.0)
    breaker.failure("a", immediate=True)
    assert breaker.state("a") == "open"
    assert breaker.allow("a") is False
    assert breaker.snapshot() == {"a": "open"}


def test_success_zera_contagem() -> None:
    breaker = CircuitBreaker(clock=FakeClock(), failure_threshold=2, cooldown_s=5.0)
    breaker.failure("a")
    breaker.success("a")
    breaker.failure("a")
    assert breaker.state("a") == "closed"


# ------------------------------------------------------------------ estatísticas


def test_stats_grava_atomico_e_recarrega(tmp_path) -> None:
    path = tmp_path / "llm" / "usage.json"
    stats = UsageStats(path)
    stats.record("groq", "modelo-a", Usage(prompt_tokens=10, completion_tokens=5))
    stats.record("groq", "modelo-a", Usage(prompt_tokens=2, completion_tokens=1))
    stats.record("ollama", "modelo-b", Usage(prompt_tokens=7, completion_tokens=3))
    stats.save()

    assert path.is_file()
    assert not path.with_name(path.name + ".tmp").exists()
    bruto = json.loads(path.read_text(encoding="utf-8"))
    assert bruto["providers"]["groq"]["requests"] == 2
    assert bruto["providers"]["groq"]["prompt_tokens"] == 12
    assert bruto["providers"]["groq"]["models"]["modelo-a"]["completion_tokens"] == 6
    dia = day_key(datetime.now().timestamp())
    assert bruto["days"][dia]["ollama"]["prompt_tokens"] == 7

    recarregado = UsageStats(path)
    recarregado.load()
    assert recarregado.snapshot() == stats.snapshot()
    assert recarregado.day_tokens("groq") == 18


def test_stats_arquivo_ausente_ou_corrompido_nao_levanta(tmp_path) -> None:
    ausente = UsageStats(tmp_path / "nada.json")
    ausente.load()
    assert ausente.snapshot() == {"providers": {}, "days": {}}

    corrompido = tmp_path / "corrompido.json"
    corrompido.write_text("{isso não é json", encoding="utf-8", errors="replace")
    stats = UsageStats(corrompido)
    stats.load()
    assert stats.snapshot() == {"providers": {}, "days": {}}


def test_stats_snapshot_e_copia_independente(tmp_path) -> None:
    stats = UsageStats(tmp_path / "u.json")
    stats.record("a", "m", Usage(prompt_tokens=1, completion_tokens=1))
    copia = stats.snapshot()
    copia["providers"]["a"]["prompt_tokens"] = 999
    assert stats.snapshot()["providers"]["a"]["prompt_tokens"] == 1

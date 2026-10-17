"""Testes do ``LLMRouter``: cadeias, fallback, circuito, limitador e stats."""

from __future__ import annotations

import inspect
import logging
from collections import deque

import pytest
from test_parte1_fake_server import FakeOpenAIServer, completion, error

from aris_agent.contract.errors import ProviderError
from aris_agent.contract.protocols import LLMClient
from aris_agent.contract.types import ChatMessage, LLMResponse, Usage
from aris_agent.llm.circuit import CircuitBreaker
from aris_agent.llm.limits import RateLimiter
from aris_agent.llm.provider import OpenAICompatProvider
from aris_agent.llm.router import LLMRouter, estimate_request_tokens
from aris_agent.llm.settings import ProviderConfig, parse_settings
from aris_agent.llm.stats import UsageStats


class Clock:
    """Relógio compartilhado: ``sleep`` só avança o tempo (sem espera real)."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    @property
    def sleeps(self) -> list[float]:
        return getattr(self, "_sleeps", [])

    def sleep_rec(self, seconds: float) -> None:
        self._sleeps = self.sleeps + [seconds]
        self.now += seconds


class Wall:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def ok(provider: str, model: str, text: str = "resposta", prompt: int = 10, completion: int = 5):
    return LLMResponse(
        message=ChatMessage(role="assistant", content=text),
        usage=Usage(prompt_tokens=prompt, completion_tokens=completion),
        provider=provider,
        model=model,
    )


class Stub:
    """Provedor falso para testar a lógica do roteador sem HTTP."""

    def __init__(self, name: str, results, *, enabled: bool = True) -> None:
        self.name = name
        self.config = ProviderConfig(
            name=name, base_url=f"http://{name}/v1", models=(f"{name}-modelo",)
        )
        self.enabled = enabled
        self._results = deque(results)
        self.calls = 0

    def status(self) -> str | None:
        if self.enabled:
            return None
        return f"variável CHAVE_{self.name.upper()} ausente ou vazia"

    def chat(self, messages, tools=None, *, model=None, max_tokens=1024, temperature=0.3):
        self.calls += 1
        if not self._results:
            raise AssertionError(f"stub {self.name} sem roteiro")
        item = self._results.popleft()
        if isinstance(item, Exception):
            raise item
        return item


def make_settings(extra: dict | None = None):
    base = {
        "providers": {
            "a": {"base_url": "http://a/v1", "models": ["ma"]},
            "b": {"base_url": "http://b/v1", "models": ["mb"]},
        },
        "chains": {
            "easy": ["a:ma"],
            "normal": ["a:ma", "b:mb"],
            "hard": ["b:mb"],
        },
    }
    if extra:
        base.update(extra)
    return parse_settings(base)


def make_router(settings, providers, tmp_path, *, clock=None, **kwargs):
    clock = clock or Clock()
    wall = kwargs.pop("wall", None) or Wall()
    limiter = kwargs.pop("limiter", None) or RateLimiter(clock=clock, wall=wall)
    breaker = kwargs.pop("breaker", None) or CircuitBreaker(
        clock=clock,
        failure_threshold=settings.failure_threshold,
        cooldown_s=settings.cooldown_s,
    )
    stats = kwargs.pop("stats", None) or UsageStats(tmp_path / "usage.json", wall=wall)
    return (
        LLMRouter(
            settings,
            providers=providers,
            stats=stats,
            limiter=limiter,
            breaker=breaker,
            sleeper=kwargs.pop("sleeper", clock.sleep_rec),
            clock=clock,
            wall=wall,
        ),
        clock,
    )


def messages():
    return [ChatMessage(role="user", content="olá")]


# ------------------------------------------------------------- contrato


def test_roteador_implementa_o_protocolo(tmp_path) -> None:
    router, _ = make_router(
        make_settings(), {"a": Stub("a", []), "b": Stub("b", [])}, tmp_path
    )
    assert isinstance(router, LLMClient)

    params = inspect.signature(router.chat).parameters
    assert list(params) == ["messages", "tools", "difficulty", "max_tokens", "temperature"]
    assert params["messages"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params["tools"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for name in ("difficulty", "max_tokens", "temperature"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["difficulty"].default == "normal"
    assert params["max_tokens"].default == 1024
    assert params["temperature"].default == 0.3
    assert params["tools"].default is None


def test_estimativa_de_tokens() -> None:
    msgs = [ChatMessage(role="user", content="x" * 40)]
    assert estimate_request_tokens(msgs, None, 100) == 110


# ------------------------------------------------------------- cadeias


def test_difficulty_escolhe_a_cadeia(tmp_path) -> None:
    a = Stub("a", [ok("a", "ma")])
    b = Stub("b", [ok("b", "mb")])
    router, _ = make_router(make_settings(), {"a": a, "b": b}, tmp_path)

    assert router.chat(messages(), difficulty="easy").provider == "a"
    assert router.chat(messages(), difficulty="hard").provider == "b"
    assert a.calls == 1 and b.calls == 1


def test_cadeia_cai_para_o_proximo_provedor(tmp_path) -> None:
    a = Stub("a", [ProviderError("servidor em manutenção", kind="server")])
    b = Stub("b", [ok("b", "mb", text="depois do fallback")])
    router, _ = make_router(make_settings(), {"a": a, "b": b}, tmp_path)

    response = router.chat(messages(), difficulty="normal")
    assert response.provider == "b"
    assert response.message.content == "depois do fallback"
    assert a.calls == 1 and b.calls == 1
    assert router.last_used == ("b", "mb")


def test_todos_falham_levanta_resumo_sem_segredos(tmp_path) -> None:
    a = Stub("a", [ProviderError("limite atingido", kind="rate_limit")])
    b = Stub("b", [ProviderError("sem rede", kind="network")])
    router, _ = make_router(make_settings(), {"a": a, "b": b}, tmp_path)

    with pytest.raises(ProviderError) as excinfo:
        router.chat(messages())

    text = str(excinfo.value)
    assert "a:ma=rate_limit" in text
    assert "b:mb=network" in text
    assert "todos os provedores falharam" in text
    assert "Bearer" not in text and "gsk_" not in text and "Authorization" not in text
    assert excinfo.value.kind == "server"  # tipos misturados → genérico


def test_cadeia_com_provedor_desconhecido(tmp_path) -> None:
    settings = parse_settings(
        {
            "providers": {"a": {"base_url": "http://a/v1", "models": ["ma"]}},
            "chains": {"normal": ["fantasma:m", "a:ma"]},
        }
    )
    a = Stub("a", [ok("a", "ma")])
    router, _ = make_router(settings, {"a": a}, tmp_path)
    assert router.chat(messages()).provider == "a"


def test_provedor_desativado_e_pulado_com_aviso(tmp_path, caplog) -> None:
    a = Stub("a", [], enabled=False)
    b = Stub("b", [ok("b", "mb")])
    router, _ = make_router(make_settings(), {"a": a, "b": b}, tmp_path)

    with caplog.at_level(logging.WARNING):
        response = router.chat(messages())

    assert response.provider == "b"
    assert a.calls == 0
    assert any("CHAVE_A" in record.message for record in caplog.records)


def test_cadeia_sem_nenhum_provedor_ativo(tmp_path) -> None:
    a = Stub("a", [], enabled=False)
    b = Stub("b", [], enabled=False)
    router, _ = make_router(make_settings(), {"a": a, "b": b}, tmp_path)

    with pytest.raises(ProviderError) as excinfo:
        router.chat(messages())

    assert "desativado" in str(excinfo.value)
    assert excinfo.value.kind == "bad_request"
    assert a.calls == 0 and b.calls == 0


def test_sem_cadeia_nenhuma_levanta_bad_request(tmp_path) -> None:
    router, _ = make_router(parse_settings({}), {}, tmp_path)
    with pytest.raises(ProviderError) as excinfo:
        router.chat(messages())
    assert excinfo.value.kind == "bad_request"
    assert "aris_agent.json" in str(excinfo.value)


# ------------------------------------------------------- circuit breaker


def test_circuit_breaker_pula_o_provedor_com_falhas(tmp_path) -> None:
    settings = parse_settings(
        {
            "providers": {
                "a": {"base_url": "http://a/v1", "models": ["ma"]},
                "b": {"base_url": "http://b/v1", "models": ["mb"]},
            },
            "chains": {"normal": ["a:ma", "b:mb"]},
            "failure_threshold": 1,
            "cooldown_s": 600,
        }
    )
    a = Stub("a", [ProviderError("explode", kind="server")])
    b = Stub("b", [ok("b", "mb"), ok("b", "mb")])
    router, _ = make_router(settings, {"a": a, "b": b}, tmp_path)

    assert router.chat(messages()).provider == "b"
    assert router.chat(messages()).provider == "b"
    assert a.calls == 1  # circuito aberto depois da primeira falha
    assert b.calls == 2
    assert router.stats()["circuits"]["a"] == "open"


def test_auth_abre_o_circuito_de_imediato(tmp_path) -> None:
    settings = parse_settings(
        {
            "providers": {
                "a": {"base_url": "http://a/v1", "models": ["ma"]},
                "b": {"base_url": "http://b/v1", "models": ["mb"]},
            },
            "chains": {"normal": ["a:ma", "b:mb"]},
            "failure_threshold": 9,
        }
    )
    a = Stub("a", [ProviderError("chave inválida", kind="auth")])
    b = Stub("b", [ok("b", "mb"), ok("b", "mb")])
    router, _ = make_router(settings, {"a": a, "b": b}, tmp_path)

    router.chat(messages())
    router.chat(messages())
    assert a.calls == 1
    assert router.stats()["circuits"]["a"] == "open"


# ------------------------------------------------------------- limitador


def test_limite_prefere_o_proximo_provedor_sem_esperar(tmp_path) -> None:
    settings = parse_settings(
        {
            "providers": {
                "a": {
                    "base_url": "http://a/v1",
                    "models": ["ma"],
                    "limits": {"requests_per_minute": 1},
                },
                "b": {"base_url": "http://b/v1", "models": ["mb"]},
            },
            "chains": {"normal": ["a:ma", "b:mb"]},
        }
    )
    a = Stub("a", [ok("a", "ma"), ok("a", "ma")])
    b = Stub("b", [ok("b", "mb"), ok("b", "mb")])
    router, clock = make_router(settings, {"a": a, "b": b}, tmp_path)

    assert router.chat(messages()).provider == "a"
    assert router.chat(messages()).provider == "b"
    assert a.calls == 1
    assert b.calls == 1
    assert clock.sleeps == []  # nem um segundo de espera


def test_limite_espera_quando_nao_ha_alternativa(tmp_path) -> None:
    settings = parse_settings(
        {
            "providers": {
                "a": {
                    "base_url": "http://a/v1",
                    "models": ["ma"],
                    "limits": {"requests_per_minute": 1},
                },
            },
            "chains": {"normal": ["a:ma"]},
            "max_wait_s": 120,
        }
    )
    a = Stub("a", [ok("a", "ma"), ok("a", "ma")])
    router, clock = make_router(settings, {"a": a}, tmp_path)

    assert router.chat(messages()).provider == "a"
    assert router.chat(messages()).provider == "a"
    assert a.calls == 2
    assert clock.sleeps and clock.sleeps[0] == pytest.approx(60.0, abs=1.0)


def test_limite_curto_sem_alternativa_falha_em_vez_de_esperar_muito(tmp_path) -> None:
    settings = parse_settings(
        {
            "providers": {
                "a": {
                    "base_url": "http://a/v1",
                    "models": ["ma"],
                    "limits": {"requests_per_minute": 1},
                },
            },
            "chains": {"normal": ["a:ma"]},
            "max_wait_s": 5,
        }
    )
    a = Stub("a", [ok("a", "ma")])
    router, clock = make_router(settings, {"a": a}, tmp_path)

    router.chat(messages())
    with pytest.raises(ProviderError) as excinfo:
        router.chat(messages())
    assert "rate_limit" in str(excinfo.value)
    assert clock.sleeps == []
    assert a.calls == 1


# ------------------------------------------------------------- stats


def test_stats_conta_tokens_e_exposto(tmp_path) -> None:
    a = Stub("a", [ok("a", "ma", prompt=30, completion=12)])
    router, _ = make_router(make_settings(), {"a": a}, tmp_path)

    router.chat(messages())

    stats = router.stats()
    assert stats["usage"]["providers"]["a"]["prompt_tokens"] == 30
    assert stats["usage"]["providers"]["a"]["completion_tokens"] == 12
    assert stats["usage"]["providers"]["a"]["models"]["ma"]["requests"] == 1
    assert stats["usage"]["days"]  # tem o dia de hoje
    assert stats["providers"]["a"]["ativo"] is True
    assert stats["chains"]["normal"] == ["a:ma", "b:mb"]
    assert stats["last_used"] == ["a", "ma"]
    assert stats["limits"]["a"]["requests_minute"] == 1
    assert (tmp_path / "usage.json").is_file()


def test_seed_de_tokens_do_dia_vem_do_arquivo(tmp_path) -> None:
    wall = Wall()
    path = tmp_path / "usage.json"
    stats = UsageStats(path, wall=wall)
    stats.record("a", "ma", Usage(prompt_tokens=100, completion_tokens=50))
    stats.save()

    settings = parse_settings(
        {
            "providers": {
                "a": {
                    "base_url": "http://a/v1",
                    "models": ["ma"],
                    "limits": {"tokens_per_day": 1000},
                },
            },
            "chains": {"normal": ["a:ma"]},
        }
    )
    a = Stub("a", [ok("a", "ma")])
    router, _ = make_router(settings, {"a": a}, tmp_path, wall=wall, stats=stats)

    assert router.stats()["limits"]["a"]["tokens_day"] == 150


# ------------------------------------------------------- integração HTTP


def test_fallback_real_com_dois_servidores_falsos(tmp_path) -> None:
    with FakeOpenAIServer() as server_a, FakeOpenAIServer() as server_b:
        server_a.enqueue(error(500, "erro no provedor a"))
        server_b.enqueue(payload=completion("ok do provedor b", model="modelo-b"))

        settings = parse_settings(
            {
                "providers": {
                    "primeiro": {
                        "base_url": server_a.base_url,
                        "models": ["ma"],
                        "max_attempts": 1,
                    },
                    "segundo": {"base_url": server_b.base_url, "models": ["mb"]},
                },
                "chains": {"normal": ["primeiro:ma", "segundo:mb"]},
            }
        )
        router, _ = make_router(
            settings,
            {
                "primeiro": OpenAICompatProvider(settings.providers["primeiro"], env={}),
                "segundo": OpenAICompatProvider(settings.providers["segundo"], env={}),
            },
            tmp_path,
        )

        response = router.chat(messages())

    assert response.provider == "segundo"
    assert response.model == "modelo-b"
    assert response.message.content == "ok do provedor b"
    assert server_a.request_count == 1
    assert server_b.request_count == 1
    assert router.last_used == ("segundo", "modelo-b")  # modelo veio do servidor

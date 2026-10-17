"""Parte 3: política anti-SSRF (esquemas, hosts locais, IPs privados, DNS)."""

from __future__ import annotations

import ipaddress
import socket

import pytest
from test_parte3_utils import make_ctx

from aris_agent.tools.web.settings import WebSettings, web_settings
from aris_agent.tools.web.ssrf import SsrfBlockedError, check_url

BLOQUEADAS = [
    "",
    "file:///C:/Windows/System32/drivers/etc/hosts",
    "ftp://arquivo.example.com/a.zip",
    "javascript:alert(1)",
    "data:text/html,<h1>oi</h1>",
    "gopher://example.com/",
    "http://localhost:8000/admin",
    "http://foo.localhost/",
    "http://127.0.0.1/",
    "http://127.1.2.3:9000/x",
    "http://0.0.0.0/",
    "http://10.0.0.5/",
    "http://172.16.0.1/",
    "http://192.168.1.1/router",
    "http://169.254.169.254/latest/meta-data/",
    "http://100.64.0.1/",
    "http://[::1]/",
    "http://[fe80::1]/",
    "http://[fc00::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://224.0.0.1/",
    "http://user:senha@example.com/",
    "http://example.com:99999/",
    "http:///caminho/sem/host",
]


@pytest.mark.parametrize("url", BLOQUEADAS)
def test_urls_bloqueadas(url: str) -> None:
    with pytest.raises(SsrfBlockedError):
        check_url(url, WebSettings())


def test_test_allow_local_so_libera_loopback() -> None:
    liberado = WebSettings(test_allow_local=True)
    assert check_url("http://127.0.0.1:8000/x?a=1", liberado).startswith("http://127.0.0.1:8000/")
    assert check_url("http://[::1]/", liberado) == "http://[::1]/", "loopback IPv6 também liberado"
    for proibida in ("http://169.254.169.254/", "http://10.0.0.1/", "http://[fc00::1]/"):
        with pytest.raises(SsrfBlockedError):
            check_url(proibida, liberado)
    with pytest.raises(SsrfBlockedError):
        check_url("file:///C:/x", liberado)


def _fake_dns(resposta: str):
    def fake(host, port, type=0, **_kw):  # noqa: A002 - assinatura do getaddrinfo
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resposta, port))]

    return fake


def test_host_que_resolve_para_privado_e_bloqueado(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns("10.1.2.3"))
    with pytest.raises(SsrfBlockedError) as exc:
        check_url("http://interno.example.com/pag", WebSettings())
    assert "rede privada" in str(exc.value)


def test_host_que_resolve_para_publico_passa(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns("93.184.216.34"))
    url = check_url("http://Exemplo.COM", WebSettings())
    assert url == "http://exemplo.com/"


def test_host_que_resolve_para_loopback_com_flag(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns("127.0.0.1"))
    assert check_url("http://app.example.com/", WebSettings(test_allow_local=True))
    with pytest.raises(SsrfBlockedError):
        check_url("http://app.example.com/", WebSettings())


def test_flag_nao_libera_privado_via_dns(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns("169.254.169.254"))
    with pytest.raises(SsrfBlockedError) as exc:
        check_url("http://app.example.com/", WebSettings(test_allow_local=True))
    assert "link-local" in str(exc.value)


def test_falha_de_dns_e_bloqueio_fail_closed(monkeypatch) -> None:
    def quebra(*_a, **_kw):
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(socket, "getaddrinfo", quebra)
    with pytest.raises(SsrfBlockedError) as exc:
        check_url("http://host-que-nao-existe.example/", WebSettings())
    assert "não foi possível resolver" in str(exc.value)


def test_dns_e_cacheado(monkeypatch) -> None:
    chamadas: list[str] = []

    def conta(host, port, type=0, **_kw):  # noqa: A002
        chamadas.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", conta)
    cache: dict = {}
    check_url("http://exemplo.com/a", WebSettings(), cache)
    check_url("http://exemplo.com/b", WebSettings(), cache)
    assert chamadas == ["exemplo.com"]


def test_normalizacao_da_url(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns("93.184.216.34"))
    assert check_url("https://Exemplo.COM/p/q?x=1#f", WebSettings()) == "https://exemplo.com/p/q?x=1#f"
    assert check_url("https://exemplo.com", WebSettings()) == "https://exemplo.com/"
    assert (
        check_url("http://exemplo.com:8080/x", WebSettings()) == "http://exemplo.com:8080/x"
    )


def test_ipv6_publico_passa(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns("2606:4700:4700::1111"))
    assert check_url("http://[2606:4700:4700::1111]/", WebSettings())


def test_endereco_publico_nao_confundido_com_privado() -> None:
    assert ipaddress.ip_address("8.8.8.8").is_global
    from aris_agent.tools.web.ssrf import _blocked_reason

    assert _blocked_reason(ipaddress.ip_address("8.8.8.8")) is None
    assert _blocked_reason(ipaddress.ip_address("10.0.0.1")) is not None
    assert _blocked_reason(ipaddress.ip_address("::ffff:169.254.169.254")) is not None


def test_flag_padrao_vem_da_configuracao(tmp_path) -> None:
    assert web_settings(make_ctx(tmp_path, allow_local=False).config).test_allow_local is False
    assert web_settings(make_ctx(tmp_path, allow_local=True).config).test_allow_local is True

"""Proteção SSRF: valida URL, resolve DNS e barra redes locais/privadas."""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlsplit, urlunsplit

from .settings import WebSettings

log = logging.getLogger("aris.agent.tools.web.ssrf")

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Nomes que nunca resolvem para a internet pública.
_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})

_DNS_CACHE_MAX = 512


class SsrfBlockedError(Exception):
    """URL recusada pela política de rede (esquema/destino proibido)."""


def _blocked_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Devolve o motivo do bloqueio ou ``None`` se o IP for público."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 vira 127.0.0.1
    if ip.is_unspecified:
        return "IP indefinido (0.0.0.0/::)"
    if ip.is_loopback:
        return "loopback (127.0.0.0/8, ::1)"
    if ip.is_link_local:
        return "link-local (169.254.0.0/16, fe80::/10) — inclui metadados de nuvem"
    if ip.is_private:
        return "rede privada (10/8, 172.16/12, 192.168/16, fc00::/7...)"
    if ip.is_multicast:
        return "multicast"
    if ip.is_reserved:
        return "intervalo reservado"
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return "rede compartilhada (100.64.0.0/10)"
    return None


def _resolve_ips(host: str, port: int, cache: dict | None) -> list:
    """Resolve ``host`` em IPs (com cache simples); levanta ``SsrfBlockedError`` se falhar."""
    key = host.lower().rstrip(".")
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return [ipaddress.ip_address(ip) for ip in hit]
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as exc:
        raise SsrfBlockedError(f"não foi possível resolver o host {key!r}: {exc}") from exc
    seen: dict[str, object] = {}
    for info in infos:
        addr = info[4][0]
        try:
            seen[addr] = ipaddress.ip_address(addr)
        except ValueError:
            log.debug("endereço DNS inválido ignorado: %r", addr)
    ips = list(seen.values())
    if not ips:
        raise SsrfBlockedError(f"o host {key!r} não resolveu para nenhum IP")
    if cache is not None:
        if len(cache) >= _DNS_CACHE_MAX:
            cache.clear()
        cache[key] = [str(ip) for ip in ips]
    return ips


def check_url(url: str, settings: WebSettings, cache: dict | None = None) -> str:
    """Valida ``url`` contra a política anti-SSRF e devolve a URL normalizada.

    Blocos: esquema que não seja http(s), usuário/senha na URL, host local,
    IP literal ou nome que resolva para loopback/link-local/privado/multicast/
    reservado. ``settings.test_allow_local`` (somente testes) libera loopback.
    Levanta :class:`SsrfBlockedError` quando a URL é recusada.
    """
    raw = str(url or "").strip()
    if not raw:
        raise SsrfBlockedError("URL vazia")
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise SsrfBlockedError(f"URL inválida: {exc}") from exc
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SsrfBlockedError(f"esquema não permitido: {scheme or '(sem esquema)'} (só http/https)")
    if parts.username is not None or parts.password is not None:
        raise SsrfBlockedError("URL com usuário/senha não é permitida")
    try:
        port = parts.port  # pode levantar ValueError em porta inválida
    except ValueError as exc:
        raise SsrfBlockedError(f"porta inválida na URL: {exc}") from exc
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise SsrfBlockedError("URL sem host")
    if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
        if not (settings.test_allow_local and host in _LOCAL_HOSTNAMES):
            raise SsrfBlockedError(f"host local proibido: {host}")
    effective_port = port if port is not None else (443 if scheme == "https" else 80)

    # IP literal: checa direto, sem DNS.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        reason = _blocked_reason(literal)
        if reason and not (settings.test_allow_local and literal.is_loopback):
            raise SsrfBlockedError(f"endereço proibido ({reason}): {host}")
    else:
        for ip in _resolve_ips(host, effective_port, cache):
            reason = _blocked_reason(ip)
            if reason and not (settings.test_allow_local and ip.is_loopback):
                raise SsrfBlockedError(f"host {host!r} resolve para endereço proibido ({reason})")

    netloc = f"[{host}]" if ":" in host and not host.startswith("[") else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, parts.fragment))

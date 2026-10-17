"""Cliente HTTP com limites rígidos e redirecionamentos revalidados (anti-SSRF)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests

from ...contract.utils import redact_secrets
from .settings import WebSettings
from .ssrf import SsrfBlockedError, check_url

log = logging.getLogger("aris.agent.tools.web.http_client")

_CHUNK = 65536
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class FetchError(Exception):
    """Falha ao baixar uma URL (rede, HTTP, limite ou política)."""


@dataclass
class FetchResult:
    """Resultado de um download limitado."""

    url: str  # URL final (após redirecionamentos)
    status: int
    content_type: str
    body: bytes
    redirects: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Corpo decodificado (melhor esforço)."""
        return self.body.decode("utf-8", errors="replace")


def fetch(url: str, settings: WebSettings, *, max_bytes: int | None = None, cancel=None) -> FetchResult:
    """Baixa ``url`` respeitando timeout, limite de bytes e de redirecionamentos.

    Cada salto de redirecionamento passa por :func:`check_url` de novo: um
    redirect para IP privado/link-local é barrado na hora.
    """
    limit = int(max_bytes if max_bytes is not None else settings.max_download_bytes)
    if limit <= 0:
        raise FetchError("limite de tamanho inválido")
    session = requests.Session()
    session.headers["User-Agent"] = settings.user_agent
    current = url
    redirects: list[str] = []
    cache: dict = {}
    try:
        for hop in range(settings.max_redirects + 1):
            try:
                current = check_url(current, settings, cache)
            except SsrfBlockedError as exc:
                raise FetchError(f"URL recusada: {exc}") from exc
            if cancel is not None and cancel.is_set():
                raise FetchError("cancelado pelo chamador")
            try:
                resp = session.get(
                    current,
                    allow_redirects=False,
                    timeout=(settings.connect_timeout_s, settings.timeout_s),
                    stream=True,
                )
            except requests.Timeout as exc:
                raise FetchError(f"timeout ao acessar {redact_secrets(current)}") from exc
            except requests.RequestException as exc:
                raise FetchError(
                    f"falha de rede ao acessar {redact_secrets(current)}: {exc}"
                ) from exc
            with resp:
                if resp.status_code in _REDIRECT_STATUSES:
                    location = resp.headers.get("Location")
                    if not location:
                        raise FetchError(f"HTTP {resp.status_code} sem Location em {redact_secrets(current)}")
                    if hop >= settings.max_redirects:
                        raise FetchError(
                            f"mais de {settings.max_redirects} redirecionamentos "
                            f"({len(redirects) + 1}º: {redact_secrets(location)})"
                        )
                    nxt = urljoin(current, location)
                    log.debug("redirect %s -> %s", redact_secrets(current), redact_secrets(nxt))
                    redirects.append(current)
                    current = nxt
                    continue
                if resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code} em {redact_secrets(current)}")
                declared = resp.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > limit:
                    raise FetchError(f"conteúdo excede o limite de {limit} bytes")
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_content(chunk_size=_CHUNK):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > limit:
                        raise FetchError(f"conteúdo excede o limite de {limit} bytes")
                    chunks.append(chunk)
                    if cancel is not None and cancel.is_set():
                        raise FetchError("cancelado pelo chamador")
                return FetchResult(
                    url=current,
                    status=resp.status_code,
                    content_type=(resp.headers.get("Content-Type") or "").split(";")[0].strip().lower(),
                    body=b"".join(chunks),
                    redirects=redirects,
                )
        raise FetchError(f"mais de {settings.max_redirects} redirecionamentos")
    finally:
        session.close()

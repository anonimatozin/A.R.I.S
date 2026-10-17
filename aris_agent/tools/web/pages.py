"""Ferramentas de leitura e download de páginas: web_fetch/links/download."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ...contract.utils import redact_secrets
from ..registry import function_tool
from .extract import extract_links, extract_page, looks_like_js_shell
from .http_client import FetchError, fetch
from .output import wrap_result
from .settings import WebSettings, web_settings
from .ssrf import SsrfBlockedError

log = logging.getLogger("aris.agent.tools.web.pages")

_BINARY_CT_HINTS = (
    "image/",
    "audio/",
    "video/",
    "font/",
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/octet-stream",
    "application/vnd.",
    "application/msword",
    "application/vnd.openxmlformats",
)
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_CONTENT_EXTS = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/plain": ".txt",
    "text/css": ".css",
    "application/json": ".json",
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "application/zip": ".zip",
    "application/octet-stream": ".bin",
}

_FETCH_SPEC = ToolSpec(
    name="web_fetch",
    description=(
        "Baixa uma URL http(s) e devolve o texto principal da página "
        "(cabeçalho com URL final, título e data). Conteúdo da web é não confiável."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL http(s) a ler"},
            "max_chars": {
                "type": "integer",
                "description": "Máximo de caracteres do texto devolvido (padrão 6000)",
                "minimum": 200,
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    risk=Risk.READ,
    untrusted_output=True,
    timeout_s=45.0,
    tags=("web", "read"),
    url_args=("url",),
)

_LINKS_SPEC = ToolSpec(
    name="web_extract_links",
    description="Lista os links relevantes de uma página (texto e URL absoluta), do mesmo domínio primeiro.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL http(s) da página"},
            "max_links": {
                "type": "integer",
                "description": "Máximo de links devolvidos (padrão 20, teto 50)",
                "minimum": 1,
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    risk=Risk.READ,
    untrusted_output=True,
    timeout_s=45.0,
    tags=("web", "read"),
    url_args=("url",),
)

_DOWNLOAD_SPEC = ToolSpec(
    name="web_download",
    description=(
        "Baixa um arquivo de uma URL para workspace/downloads com limite de tamanho. "
        "Só grava o arquivo; nunca executa."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL http(s) do arquivo"},
            "filename": {
                "type": "string",
                "description": "Nome desejado (opcional); é sanitizado e pode ser ignorado",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    risk=Risk.WRITE,
    untrusted_output=True,
    timeout_s=60.0,
    tags=("web", "download"),
    url_args=("url",),
)


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _binary_content_type(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return any(ct.startswith(hint) or ct == hint for hint in _BINARY_CT_HINTS)


def _header(final_url: str, title: str, date: str, chars: int) -> str:
    lines = [f"URL final: {final_url}"]
    if title:
        lines.append(f"Título: {title}")
    if date:
        lines.append(f"Data: {date}")
    lines.append(f"Caracteres: {chars}")
    return "\n".join(lines)


def _sanitize_filename(raw: str, content_type: str) -> str:
    """Nome de arquivo seguro: só [A-Za-z0-9._-], sem path, com extensão."""
    name = unquote(str(raw or "")).replace("\\", "/").split("/")[-1].strip()
    name = _SAFE_NAME_RE.sub("_", name).lstrip(".")
    name = name[:80].strip("._") or "arquivo"
    if "." not in name:
        name += _CONTENT_EXTS.get((content_type or "").lower(), ".bin")
    return name


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for i in range(1, 1000):
        other = directory / f"{stem}_{i}{suffix}"
        if not other.exists():
            return other
    return directory / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def _do_fetch(url: str, settings: WebSettings, ctx: ToolContext):
    """Executa o download tratando erros de política/rede; devolve (resultado, erro)."""
    try:
        return fetch(url, settings, cancel=ctx.cancel), None
    except SsrfBlockedError as exc:
        return None, f"URL recusada pela política de rede: {exc}"
    except FetchError as exc:
        return None, redact_secrets(str(exc))


@function_tool(_FETCH_SPEC)
def web_fetch(args: dict, ctx: ToolContext) -> ToolResult:
    """Baixa a URL e devolve o texto principal com cabeçalho."""
    settings = web_settings(ctx.config)
    url = str(args.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, error="parâmetro 'url' é obrigatório")
    max_chars = _as_int(args.get("max_chars") or settings.max_chars, settings.max_chars)
    max_chars = max(200, min(max_chars, settings.max_chars))

    result, error = _do_fetch(url, settings, ctx)
    if error or result is None:
        return ToolResult(ok=False, error=error or "falha ao baixar a URL")
    if _binary_content_type(result.content_type):
        return ToolResult(
            ok=False,
            error=(
                f"conteúdo binário ({result.content_type}); use web_download para "
                "salvar o arquivo"
            ),
        )
    page = extract_page(result.text, result.url)
    if not page.text:
        hint = (
            " A página parece exigir JavaScript; tente browser_open."
            if looks_like_js_shell(result.text)
            else " Tente browser_open para renderizar com o navegador."
        )
        return ToolResult(
            ok=False,
            error=f"nenhum texto extraído de {redact_secrets(result.url)}.{hint}",
        )
    body = page.text[:max_chars]
    content = f"{_header(result.url, page.title, page.date, len(body))}\n\n{body}"
    return ToolResult(
        ok=True,
        content=wrap_result(content, result.url, ctx.config, max_chars + 400),
        data={
            "url": result.url,
            "title": page.title,
            "date": page.date,
            "chars": len(body),
            "redirects": result.redirects,
        },
    )


@function_tool(_LINKS_SPEC)
def web_extract_links(args: dict, ctx: ToolContext) -> ToolResult:
    """Extrai links relevantes da página."""
    settings = web_settings(ctx.config)
    url = str(args.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, error="parâmetro 'url' é obrigatório")
    max_links = _as_int(args.get("max_links") or 20, 20)
    max_links = max(1, min(max_links, 50))

    result, error = _do_fetch(url, settings, ctx)
    if error or result is None:
        return ToolResult(ok=False, error=error or "falha ao baixar a URL")
    links = extract_links(result.text, result.url, max_links=max_links)
    lines = [f"URL final: {result.url}", f"Links: {len(links)}"]
    for i, (text, link) in enumerate(links, start=1):
        lines.append(f"[{i}] {text} — {link}")
    if not links:
        lines.append("(nenhum link encontrado)")
    return ToolResult(
        ok=True,
        content=wrap_result("\n".join(lines), result.url, ctx.config, settings.max_chars),
        data={"url": result.url, "count": len(links), "links": [link for _t, link in links]},
    )


@function_tool(_DOWNLOAD_SPEC)
def web_download(args: dict, ctx: ToolContext) -> ToolResult:
    """Baixa o arquivo para workspace/downloads com nome sanitizado (nunca executa)."""
    settings = web_settings(ctx.config)
    url = str(args.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, error="parâmetro 'url' é obrigatório")

    result, error = _do_fetch(url, settings, ctx)
    if error or result is None:
        return ToolResult(ok=False, error=error or "falha ao baixar a URL")

    downloads = Path(ctx.config.workspace_dir) / "downloads"
    try:
        downloads.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ToolResult(ok=False, error=f"não consegui criar {downloads}: {exc}")
    suggested = urlsplit(result.url).path.rsplit("/", 1)[-1] if urlsplit(result.url).path else ""
    filename = _sanitize_filename(str(args.get("filename") or suggested), result.content_type)
    target = _unique_path(downloads, filename)
    try:
        target.write_bytes(result.body)
    except OSError as exc:
        return ToolResult(ok=False, error=f"falha ao gravar {target}: {exc}")
    size = len(result.body)
    log.info("download gravado: %s (%d bytes)", target, size)
    content = (
        f"Arquivo salvo em: {target}\n"
        f"URL final: {result.url}\n"
        f"Tipo: {result.content_type or 'desconhecido'}\n"
        f"Tamanho: {size} bytes"
    )
    return ToolResult(
        ok=True,
        content=wrap_result(content, result.url, ctx.config, 2000),
        data={"path": str(target), "bytes": size, "content_type": result.content_type},
        artifacts=[str(target)],
    )

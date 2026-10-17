"""Utilitários das ferramentas do PC: caminhos, saída, processos e ambiente.

Nenhuma função daqui decide política de segurança (isso é da Parte 5); aqui só
garantimos resolução segura de caminho, limites de saída e timeout real.
"""

from __future__ import annotations

import functools
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...contract.types import ToolContext, ToolResult
from ...contract.utils import truncate_text, wrap_untrusted

log = logging.getLogger("aris.agent.tools.pc.helpers")

DEFAULT_MAX_CHARS = 8000

# Chaves de ambiente que nunca devem ir para o subprocesso de pc_python_run.
_SENSITIVE_ENV_RE = re.compile(
    r"(?:_KEY$|^KEY$|TOKEN|SECRET|PASSWORD|PASSWD|CHAVE|SENHA)", re.IGNORECASE
)


class PathRefusedError(ValueError):
    """Caminho recusado (escape de raiz, UNC, unidade relativa, inexistente...)."""


def schema(properties: dict, required: tuple | list = ()) -> dict:
    """JSON Schema ``object`` pronto para ``ToolSpec.parameters``."""
    out: dict = {"type": "object", "properties": dict(properties), "additionalProperties": False}
    if required:
        out["required"] = list(required)
    return out


def err(msg: str) -> ToolResult:
    """Ferramenta falhou: ``ok=False`` com a mensagem (sempre truncada)."""
    return ToolResult(ok=False, error=truncate_text(str(msg), 2000))


def ok_result(content: str = "", *, data: Any = None, artifacts: list | None = None) -> ToolResult:
    """Ferramenta ok: ``content`` vai ao LLM (já truncado por quem chama)."""
    return ToolResult(ok=True, content=content, data=data, artifacts=list(artifacts or []))


def max_chars(ctx: ToolContext) -> int:
    """Limite de caracteres da saída para o LLM (config ``max_tool_chars``)."""
    try:
        value = int(getattr(ctx.config, "max_tool_chars", DEFAULT_MAX_CHARS) or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else DEFAULT_MAX_CHARS


def out(ctx: ToolContext, text: str, *, untrusted: bool = False, source: str = "") -> str:
    """Trunca a saída no limite do contexto; envolve conteúdo não confiável se pedido."""
    limit = max_chars(ctx)
    if untrusted:
        overhead = len(wrap_untrusted("", source)) + 2
        body = truncate_text(text, max(200, limit - overhead))
        return wrap_untrusted(body, source)
    return truncate_text(text, limit)


def bounded_int(args: dict, key: str, default: int, lo: int, hi: int) -> int:
    """Lê um inteiro dos argumentos, sempre limitado a ``[lo, hi]`` (default se inválido)."""
    raw = args.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def bounded_float(args: dict, key: str, default: float, lo: float, hi: float) -> float:
    """Lê um número dos argumentos, sempre limitado a ``[lo, hi]`` (default se inválido)."""
    raw = args.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return max(lo, min(hi, value))


def as_bool(value: Any, default: bool) -> bool:
    """Converte bool/``"true"``/``1``/``"sim"`` em bool; default se não reconhecer."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "sim", "s"}:
        return True
    if text in {"0", "false", "no", "off", "nao", "não", "n"}:
        return False
    return default


def allowed_bases(ctx: ToolContext) -> list[Path]:
    """Raízes dentro das quais os caminhos dos LLMs podem cair (resolvidas)."""
    bases: list[Path] = []
    roots = getattr(ctx.config, "allowed_roots", None) or [ctx.config.workspace_dir]
    for root in roots:
        bases.append(Path(root).expanduser().resolve())
    bases.append(Path(ctx.workdir).expanduser().resolve())
    dedup: list[Path] = []
    seen: set[str] = set()
    for base in bases:
        key = os.path.normcase(str(base))
        if key not in seen:
            seen.add(key)
            dedup.append(base)
    return dedup


def _within(path: Path, base: Path) -> bool:
    try:
        return path.is_relative_to(base)
    except (OSError, ValueError):  # pragma: no cover - defensivo
        return False


def resolve_path(
    raw: Any,
    ctx: ToolContext,
    *,
    arg: str = "path",
    must_exist: bool = False,
    allow_dir: bool = True,
) -> Path:
    """Resolve ``raw`` (expanduser + resolve) e recusa sair das raízes permitidas.

    Levanta :class:`PathRefusedError` com o caminho resolvido no erro, para o LLM
    entender onde o caminho parou.
    """
    if raw is None or not str(raw).strip():
        raise PathRefusedError(f"{arg}: caminho vazio")
    text = str(raw)
    if text.startswith("\\\\") or text.startswith("//"):
        raise PathRefusedError(f"{arg}: caminho de rede (UNC) não é permitido: {text}")
    candidate = Path(text).expanduser()
    if candidate.drive and not candidate.is_absolute():
        raise PathRefusedError(f"{arg}: caminho relativo a unidade ({text}) não é permitido")
    if not candidate.is_absolute():
        candidate = Path(ctx.workdir) / candidate
    resolved = candidate.resolve()
    if not any(_within(resolved, base) for base in allowed_bases(ctx)):
        raise PathRefusedError(f"{arg}: fora das raízes permitidas; caminho resolvido: {resolved}")
    if must_exist and not resolved.exists():
        raise PathRefusedError(f"{arg}: não existe: {resolved}")
    if not allow_dir and resolved.is_dir():
        raise PathRefusedError(f"{arg}: é uma pasta, não um arquivo: {resolved}")
    return resolved


def fmt_size(num: float) -> str:
    """Tamanho em unidades legíveis (B/KB/MB/GB), com vírgula decimal."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{value:.1f} TB"  # pragma: no cover - inalcançável


def fmt_ts(timestamp: float) -> str:
    """Data/hora local ``AAAA-MM-DD HH:MM``."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def decode_bytes(data: bytes) -> str:
    """Decodifica bytes tentando UTF-8 e caindo para CP1252/latin-1."""
    if not data:
        return ""
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")  # pragma: no cover - latin-1 nunca falha


def filter_env(base: dict | None = None) -> dict:
    """Cópia do ambiente removindo variáveis com credenciais (``*_KEY``, ``*TOKEN*``...)."""
    source = dict(os.environ if base is None else base)
    return {k: v for k, v in source.items() if not _SENSITIVE_ENV_RE.search(k)}


def kill_tree(proc: subprocess.Popen) -> None:
    """Mata o processo e os filhos (Windows: ``taskkill /T /F``). Nunca lança."""
    try:
        if proc.poll() is None and os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
    except Exception as exc:  # noqa: BLE001 - morte de processo não pode estourar
        log.debug("taskkill falhou (%s); tentando psutil/kill", exc)
        try:
            import psutil

            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception:  # noqa: BLE001
                    pass
            parent.kill()
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
    try:
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def communicate(
    proc: subprocess.Popen, timeout_s: float, cancel: Any
) -> tuple[bytes, bytes, int | None, str | None]:
    """Espera o processo com timeout e cancelamento.

    Devolve ``(stdout, stderr, returncode, problema)`` em que ``problema`` é
    ``"timeout"``, ``"cancelado"`` ou ``None``. No problema, o processo (e os
    filhos) é morto e a saída parcial é coletada.
    """
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while True:
        if cancel is not None and cancel.is_set():
            kill_tree(proc)
            return _reap_partial(proc), b"", None, "cancelado"
        rest = deadline - time.monotonic()
        if rest <= 0:
            kill_tree(proc)
            return _reap_partial(proc), b"", None, "timeout"
        try:
            stdout, stderr = proc.communicate(timeout=min(0.2, rest))
            return stdout or b"", stderr or b"", proc.returncode, None
        except subprocess.TimeoutExpired:
            continue
        except (OSError, ValueError) as exc:  # pragma: no cover - pipes quebradas
            log.warning("communicate falhou: %s", exc)
            return b"", b"", proc.returncode, str(exc)


def _reap_partial(proc: subprocess.Popen) -> bytes:
    """Coleta o que deu tempo de ler depois de matar o processo."""
    try:
        stdout, _stderr = proc.communicate(timeout=5)
        return stdout or b""
    except Exception:  # noqa: BLE001
        return b""


def guarded(fn: Callable[[dict, ToolContext], ToolResult]) -> Callable[[dict, ToolContext], ToolResult]:
    """Converte ``PathRefusedError``/``OSError``/``ValueError`` comuns em ``ToolResult``.

    Qualquer outra exceção é capturada pelo ``FunctionTool`` do registro.
    """

    @functools.wraps(fn)
    def wrapper(args: dict, ctx: ToolContext) -> ToolResult:
        try:
            return fn(args, ctx)
        except PathRefusedError as exc:
            log.info("%s recusou caminho: %s", fn.__name__, exc)
            return err(str(exc))
        except OSError as exc:
            detail = exc.strerror or str(exc)
            log.info("%s falhou em %s: %s", fn.__name__, getattr(exc, "filename", ""), detail)
            return err(f"erro de sistema: {detail} ({getattr(exc, 'filename', '') or 'sem arquivo'})")
        except (UnicodeDecodeError, TimeoutError) as exc:
            return err(f"{type(exc).__name__}: {exc}")

    return wrapper

"""Ferramentas de arquivos: listar, ler, buscar, escrever, mover e apagar (Lixeira)."""

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import time
from pathlib import Path

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import (
    allowed_bases,
    as_bool,
    bounded_int,
    decode_bytes,
    err,
    fmt_size,
    fmt_ts,
    guarded,
    ok_result,
    out,
    resolve_path,
    schema,
)

log = logging.getLogger("aris.agent.tools.pc.files")

try:
    from send2trash import send2trash
except ImportError:  # pragma: no cover - dependência opcional ausente
    send2trash = None  # type: ignore[assignment]

_SNIFF_BYTES = 64 * 1024
_MAX_READ_BYTES = 4_000_000
_MAX_SEARCH_FILE_BYTES = 256 * 1024
_MAX_SCAN_FILES = 5000

SPEC_LIST_DIR = ToolSpec(
    name="pc_list_dir",
    description="Lista o conteúdo de uma pasta (arquivos/pastas, tamanho, data), com limite de itens.",
    parameters=schema(
        {
            "path": {"type": "string", "description": "Pasta a listar (padrão: pasta de trabalho)."},
            "limit": {
                "type": "integer",
                "description": "Máximo de itens (padrão 200, até 1000).",
                "minimum": 1,
                "maximum": 1000,
            },
        }
    ),
    risk=Risk.READ,
    tags=("pc", "files"),
    path_args=("path",),
    timeout_s=15.0,
)

SPEC_READ_FILE = ToolSpec(
    name="pc_read_file",
    description="Lê um arquivo texto (codificação detectada), com offset/limit de linhas. Avisa se for binário.",
    parameters=schema(
        {
            "path": {"type": "string", "description": "Arquivo a ler."},
            "offset": {
                "type": "integer",
                "description": "Primeira linha a mostrar (padrão 1).",
                "minimum": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Quantidade de linhas (padrão 400, até 5000).",
                "minimum": 1,
                "maximum": 5000,
            },
        },
        required=("path",),
    ),
    risk=Risk.READ,
    untrusted_output=True,
    tags=("pc", "files"),
    path_args=("path",),
    timeout_s=20.0,
)

SPEC_SEARCH_FILES = ToolSpec(
    name="pc_search_files",
    description="Busca arquivos por nome (glob) e opcionalmente por conteúdo dentro de uma pasta.",
    parameters=schema(
        {
            "root": {"type": "string", "description": "Pasta raiz da busca (padrão: pasta de trabalho)."},
            "pattern": {"type": "string", "description": "Glob do nome, ex.: *.py (padrão *)."},
            "contains": {"type": "string", "description": "Texto a localizar no conteúdo (sem distinção de maiúsculas)."},
            "max_results": {
                "type": "integer",
                "description": "Máximo de resultados (padrão 50, até 500).",
                "minimum": 1,
                "maximum": 500,
            },
            "max_depth": {
                "type": "integer",
                "description": "Profundidade máxima de subpastas (padrão 6, até 32).",
                "minimum": 1,
                "maximum": 32,
            },
        }
    ),
    risk=Risk.READ,
    untrusted_output=True,
    tags=("pc", "files"),
    path_args=("root",),
    timeout_s=60.0,
)

SPEC_WRITE_FILE = ToolSpec(
    name="pc_write_file",
    description="Cria ou sobrescreve um arquivo texto; se já existir, faz backup .bak com timestamp antes.",
    parameters=schema(
        {
            "path": {"type": "string", "description": "Arquivo a escrever (pastas pai são criadas)."},
            "content": {"type": "string", "description": "Conteúdo textual a gravar."},
            "encoding": {"type": "string", "description": "Codificação (padrão utf-8)."},
            "backup": {
                "type": "boolean",
                "description": "Fazer backup .bak antes de sobrescrever (padrão true).",
            },
        },
        required=("path", "content"),
    ),
    risk=Risk.WRITE,
    tags=("pc", "files"),
    path_args=("path",),
    timeout_s=30.0,
)

SPEC_MOVE_FILE = ToolSpec(
    name="pc_move_file",
    description="Move ou renomeia arquivo/pasta; não sobrescreve o destino sem overwrite=true.",
    parameters=schema(
        {
            "source": {"type": "string", "description": "Caminho de origem."},
            "destination": {"type": "string", "description": "Caminho de destino (arquivo completo)."},
            "overwrite": {
                "type": "boolean",
                "description": "Substituir destino existente (padrão false).",
            },
        },
        required=("source", "destination"),
    ),
    risk=Risk.WRITE,
    tags=("pc", "files"),
    path_args=("source", "destination"),
    timeout_s=30.0,
)

SPEC_DELETE_FILE = ToolSpec(
    name="pc_delete_file",
    description="Move arquivo ou pasta para a Lixeira (send2trash); nunca apaga permanentemente.",
    parameters=schema(
        {"path": {"type": "string", "description": "Arquivo ou pasta a enviar para a Lixeira."}},
        required=("path",),
    ),
    risk=Risk.DESTRUCTIVE,
    tags=("pc", "files"),
    path_args=("path",),
    timeout_s=30.0,
)


@function_tool(SPEC_LIST_DIR)
@guarded
def pc_list_dir(args: dict, ctx: ToolContext) -> ToolResult:
    """Lista uma pasta com nome, tipo, tamanho e data."""
    raw = args.get("path")
    folder = resolve_path(raw if raw else str(ctx.workdir), ctx, arg="path", must_exist=True)
    if not folder.is_dir():
        return err(f"não é uma pasta: {folder}")
    limit = bounded_int(args, "limit", 200, 1, 1000)
    entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    total = len(entries)
    lines: list[str] = []
    for entry in entries[:limit]:
        try:
            stat = entry.stat()
        except OSError:
            lines.append(f"[?] {entry.name} (sem permissão)")
            continue
        if entry.is_dir():
            lines.append(f"[D] {entry.name}/  {fmt_ts(stat.st_mtime)}")
        else:
            lines.append(f"[F] {entry.name}  {fmt_size(stat.st_size)}  {fmt_ts(stat.st_mtime)}")
    header = f"{folder} — {total} item(ns)"
    body = "\n".join(lines) if lines else "(pasta vazia)"
    if total > limit:
        body += f"\n[... mais {total - limit} item(ns) omitidos; use limit maior ou entre na pasta]"
    data = {"path": str(folder), "total": total, "shown": min(total, limit)}
    return ok_result(out(ctx, f"{header}\n{body}"), data=data)


@function_tool(SPEC_READ_FILE)
@guarded
def pc_read_file(args: dict, ctx: ToolContext) -> ToolResult:
    """Lê arquivo texto com detecção de codificação, limite de bytes e offset/limit."""
    path = resolve_path(args.get("path"), ctx, arg="path", must_exist=True, allow_dir=False)
    offset = bounded_int(args, "offset", 1, 1, 10_000_000)
    limit = bounded_int(args, "limit", 400, 1, 5000)
    stat = path.stat()
    with path.open("rb") as handle:
        head = handle.read(_SNIFF_BYTES)
    if b"\x00" in head:
        return ok_result(
            out(
                ctx,
                f"aviso: {path.name} parece arquivo binário ({fmt_size(stat.st_size)}); "
                "conteúdo não exibido. Use outra ferramenta se precisar analisá-lo.",
            ),
            data={"path": str(path), "binary": True, "size": stat.st_size},
        )
    encoding = _detect_encoding(head)
    if encoding.startswith("utf-16"):
        lines = _read_utf16_lines(path, encoding)
        truncated = stat.st_size > _MAX_READ_BYTES
        selecionadas = lines[offset - 1 : offset - 1 + limit]
        numeros = list(range(offset, offset + len(selecionadas)))
    else:
        selecionadas, numeros, truncated = _read_lines_scanned(path, encoding, offset, limit)
    if not selecionadas:
        return ok_result(
            out(ctx, f"{path}: nenhuma linha a partir de {offset} (arquivo com {_count_lines(path)} linha(s))."),
            data={"path": str(path), "lines": [], "offset": offset},
        )
    body = "\n".join(f"{n:6d} | {line}" for n, line in zip(numeros, selecionadas, strict=False))
    header = f"{path} — linhas {numeros[0]}..{numeros[-1]}"
    if truncated:
        header += " (aviso: leitura limitada a ~4 MB)"
    return ok_result(
        out(ctx, f"{header}\n{body}", untrusted=True, source=str(path)),
        data={"path": str(path), "lines": selecionadas, "offset": offset},
    )


def _detect_encoding(head: bytes) -> str:
    """Detecta BOM e decide entre utf-8-sig/utf-16/cp1252."""
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if head.startswith(b"\xfe\xff"):
        return "utf-16-be"
    try:
        head.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def _read_utf16_lines(path: Path, encoding: str) -> list[str]:
    """Lê arquivo UTF-16 (limitado a ~4 MB) e devolve as linhas."""
    with path.open("rb") as handle:
        raw = handle.read(_MAX_READ_BYTES)
    bom = 2 if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else 0
    return raw[bom:].decode(encoding, errors="replace").splitlines()


def _read_lines_scanned(
    path: Path, encoding: str, offset: int, limit: int
) -> tuple[list[str], list[int], bool]:
    """Varre o arquivo por linhas em binário, sem carregar tudo na memória."""
    lines: list[str] = []
    numbers: list[int] = []
    read_bytes = 0
    truncated = False
    with path.open("rb") as handle:
        for number, raw_line in enumerate(handle, start=1):
            read_bytes += len(raw_line)
            if read_bytes > _MAX_READ_BYTES:
                truncated = True
                break
            if number < offset:
                continue
            lines.append(decode_bytes(raw_line).rstrip("\r\n"))
            numbers.append(number)
            if len(lines) >= limit:
                break
    return lines, numbers, truncated


def _count_lines(path: Path) -> int:
    """Conta linhas (com teto) só para a mensagem de 'nenhuma linha'."""
    count = 0
    try:
        with path.open("rb") as handle:
            for _ in handle:
                count += 1
                if count > _MAX_READ_BYTES:
                    break
    except OSError:  # pragma: no cover - defensivo
        return -1
    return count


@function_tool(SPEC_SEARCH_FILES)
@guarded
def pc_search_files(args: dict, ctx: ToolContext) -> ToolResult:
    """Busca por nome (glob) e por conteúdo, com limites de profundidade e resultados."""
    raw = args.get("root")
    root = resolve_path(raw if raw else str(ctx.workdir), ctx, arg="root", must_exist=True)
    if not root.is_dir():
        return err(f"não é uma pasta: {root}")
    pattern = str(args.get("pattern") or "*").strip() or "*"
    contains = args.get("contains")
    contains = str(contains) if contains else None
    max_results = bounded_int(args, "max_results", 50, 1, 500)
    max_depth = bounded_int(args, "max_depth", 6, 1, 32)

    results: list[dict] = []
    scanned = 0
    stop = False
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= max_depth:
            dirnames.clear()
        dirnames.sort()
        for name in sorted(filenames):
            scanned += 1
            if scanned > _MAX_SCAN_FILES or len(results) >= max_results:
                stop = True
                break
            if not fnmatch.fnmatch(name.lower(), pattern.lower()):
                continue
            candidate = Path(dirpath) / name
            if not _safe_result(candidate, root):
                continue
            entry: dict = {"path": str(candidate.relative_to(root)), "size": _size(candidate)}
            if contains:
                snippet = _content_snippet(candidate, contains)
                if snippet is None:
                    continue
                entry["snippet"] = snippet
            results.append(entry)
        if stop:
            break

    if not results:
        return ok_result(
            out(ctx, f"Nenhum resultado em {root} para pattern={pattern!r}"
                + (f" contains={contains!r}" if contains else ".")),
            data={"results": [], "scanned": scanned},
        )
    lines = []
    for item in results:
        line = f"{item['path']}  ({fmt_size(item['size'])})"
        if "snippet" in item:
            line += f"\n    {item['snippet']}"
        lines.append(line)
    note = ""
    if len(results) >= max_results or scanned > _MAX_SCAN_FILES:
        note = "\n[... busca interrompida no limite; estreite pattern/contains ou suba max_results]"
    return ok_result(
        out(ctx, f"{len(results)} resultado(s) em {root} (varridos {scanned} arquivo(s)):\n"
            + "\n".join(lines) + note),
        data={"results": results, "scanned": scanned},
    )


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _safe_result(path: Path, root: Path) -> bool:
    """Ignora entradas cujo caminho resolvido saia da raiz (links simbólicos)."""
    try:
        resolved = path.resolve()
        base = root.resolve()
    except OSError:  # pragma: no cover - defensivo
        return False
    return resolved.is_relative_to(base)


def _content_snippet(path: Path, needle: str) -> str | None:
    """Primeiras linhas com o texto procurado, ou ``None`` se não houver/binário."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_SEARCH_FILE_BYTES)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    text = decode_bytes(raw)
    wanted = needle.lower()
    for line in text.splitlines():
        if wanted in line.lower():
            stripped = line.strip()
            return stripped if len(stripped) <= 200 else stripped[:197] + "..."
    return None


@function_tool(SPEC_WRITE_FILE)
@guarded
def pc_write_file(args: dict, ctx: ToolContext) -> ToolResult:
    """Grava texto; sobrescreve com backup .bak timestampado por padrão."""
    path = resolve_path(args.get("path"), ctx, arg="path")
    content = args.get("content")
    if not isinstance(content, str):
        return err("content precisa ser uma string (o texto a gravar)")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    try:
        content.encode(encoding)
    except (LookupError, UnicodeEncodeError) as exc:
        return err(f"codificação inválida ou conteúdo incompatível ({encoding}): {exc}")
    if path.exists() and path.is_dir():
        return err(f"o destino é uma pasta: {path}")
    backup_path: Path | None = None
    if path.exists() and as_bool(args.get("backup"), True):
        backup_path = _backup_of(path)
        shutil.copy2(path, backup_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding, newline="")
    size = path.stat().st_size
    data = {"path": str(path), "bytes": size, "backup": str(backup_path) if backup_path else None}
    msg = f"gravado {path} ({fmt_size(size)})"
    if backup_path:
        msg += f"\nbackup: {backup_path.name}"
    return ok_result(msg, data=data, artifacts=[str(path)])


def _backup_of(path: Path) -> Path:
    """Cria ``arquivo.aaaammdd-hhmmss.bak`` sem colidir no mesmo segundo."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.{stamp}-{counter}.bak")
        counter += 1
    return backup


@function_tool(SPEC_MOVE_FILE)
@guarded
def pc_move_file(args: dict, ctx: ToolContext) -> ToolResult:
    """Move/renomeia; destino existente só com overwrite=true."""
    source = resolve_path(args.get("source"), ctx, arg="source", must_exist=True)
    destination = resolve_path(args.get("destination"), ctx, arg="destination")
    if destination.is_dir():
        return err(f"o destino é uma pasta; informe o caminho completo do arquivo: {destination}")
    if source.resolve() == destination.resolve():
        return err(f"origem e destino são o mesmo caminho: {source}")
    overwrite = as_bool(args.get("overwrite"), False)
    if destination.exists() and not overwrite:
        return err(f"o destino já existe: {destination} (use overwrite=true para substituir)")
    if destination.exists():
        if destination.is_file():
            destination.unlink()
        else:
            shutil.rmtree(destination)
    shutil.move(str(source), str(destination))
    return ok_result(
        f"movido: {source} -> {destination}",
        data={"source": str(source), "destination": str(destination)},
        artifacts=[str(destination)],
    )


@function_tool(SPEC_DELETE_FILE)
@guarded
def pc_delete_file(args: dict, ctx: ToolContext) -> ToolResult:
    """Envia para a Lixeira (nunca exclusão permanente)."""
    path = resolve_path(args.get("path"), ctx, arg="path", must_exist=True)
    for base in allowed_bases(ctx):
        if path.resolve() == base:
            return err(f"não posso enviar a própria raiz permitida para a Lixeira: {path}")
    if send2trash is None:
        return err("dependência send2trash não instalada (requirements/parte2.txt)")
    try:
        send2trash(str(path))
    except Exception as exc:  # noqa: BLE001 - biblioteca lança exceções próprias
        return err(f"não consegui mover para a Lixeira: {exc}")
    return ok_result(
        f"movido para a Lixeira: {path}",
        data={"path": str(path)},
    )

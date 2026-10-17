"""Resolução e contenção de caminhos no Windows.

Regras importantes:
* ``Path.resolve()`` resolve ``..`` e links simbólicos **antes** de comparar;
* comparação com ``allowed_roots`` nunca é prefixo de string bruto
  (``C:\\ws`` não contém ``C:\\ws_evil``);
* nomes reservados (CON, NUL, COM1...), namespace ``\\\\.\\`` e caminhos de
  dispositivo são tratados como negação absoluta.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("aris.agent.safety.paths")

# Nome reservado do Windows, com ou sem extensão (CON.txt também é reservado).
_DEVICE_NAME_RE = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)", re.IGNORECASE)
_WILDCARD_RE = re.compile(r"[*?]")

# Tokens que parecem caminho absoluto (unidade ou UNC) dentro de um comando.
# O '*' final permite capturar também a raiz pura ("c:\\"), que é alvo protegido.
_COMMAND_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\s\"'<>|;&]*")


def strip_extended_prefix(value: str) -> str:
    """Remove os prefixos ``\\\\?\\`` e ``\\\\.\\`` de um caminho literal."""
    if value.startswith("\\\\?\\UNC\\") or value.startswith("\\\\?\\unc\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\") or value.startswith("\\\\.\\"):
        return value[4:]
    return value


def device_reason(value: str) -> str | None:
    """Motivo de negação se o valor for nome reservado / namespace de dispositivo."""
    raw = str(value)
    if raw.startswith("\\\\.\\"):
        return "namespace de dispositivo (\\\\.\\)"
    cleaned = strip_extended_prefix(raw)
    for part in re.split(r"[\\/]+", cleaned):
        if part and _DEVICE_NAME_RE.match(part):
            return f"nome reservado do Windows ({part.split('.')[0].upper()})"
    return None


def resolve_path(value: str, base_dir: Path) -> Path:
    """Resolve ``value`` (relativa a ``base_dir``) com ``..``, symlinks e UNC."""
    raw = strip_extended_prefix(str(value).strip())
    path = Path(raw)
    if not path.is_absolute():
        path = Path(base_dir) / path
    try:
        return path.resolve()
    except OSError as exc:  # pragma: no cover - raro (loop de symlink, etc.)
        log.warning("não consegui resolver %r (%s); usando caminho absoluto simples", value, exc)
        return Path(os.path.abspath(str(path)))


def norm_case(path: Path | str) -> Path:
    """Normaliza separador/caixa para comparação segura no Windows."""
    return Path(os.path.normcase(str(path)))


def is_within(child: Path, root: Path) -> bool:
    """True se ``child`` está dentro de (ou é) ``root``, por partes de caminho."""
    c = norm_case(child)
    r = norm_case(root)
    return c == r or c.is_relative_to(r)


def all_within(paths: list[Path], roots: list[Path]) -> bool:
    """True se todos os caminhos estão em alguma raiz permitida (lista vazia = False)."""
    if not paths:
        return False
    return all(any(is_within(p, root) for root in roots) for p in paths)


def resolved_roots(config) -> list[Path]:
    """``allowed_roots`` resolvidos (symlinks/``..`` normalizados)."""
    out: list[Path] = []
    for root in getattr(config, "allowed_roots", []) or []:
        try:
            out.append(Path(root).resolve())
        except OSError:  # pragma: no cover - defensivo
            out.append(Path(root))
    return out


def sensitive_path_reason(path: Path) -> str | None:
    """Motivo de negação absoluta se o caminho tocar um cofre de credenciais."""
    text = str(path).lower().replace("/", "\\")
    parts = [p.lower() for p in re.split(r"[\\/]+", str(path)) if p]
    if not parts:
        return None
    base = parts[-1]

    for folder in (".ssh", ".aws", ".azure", ".gnupg", ".kube"):
        if folder in parts:
            return f"pasta de credenciais ({folder})"
    if base.startswith(".env"):
        return "arquivo .env (credenciais do projeto)"
    if base in {".npmrc", ".netrc", ".pgpass", ".git-credentials", "ntuser.dat"}:
        return f"arquivo de credenciais ({base})"
    if base.endswith((".pfx", ".p12", ".ppk", ".kdbx", ".pem", ".key")):
        return f"chave/cofre ({base})"
    for fragment in (
        "\\google\\chrome\\user data\\",
        "\\microsoft\\edge\\user data\\",
        "\\mozilla\\firefox\\profiles\\",
        "\\bravesoftware\\",
        "\\microsoft\\credentials\\",
        "\\microsoft\\vault\\",
        "\\microsoft\\protect\\",
    ):
        if fragment in text:
            return f"cofre de credenciais ({fragment.strip(chr(92))})"
    if "\\system32\\config\\" in text and base in {"sam", "security", "system", "software"}:
        return f"cofre de segredos do registro ({base.upper()})"
    return None


def protected_target_reason(path: Path) -> str | None:
    """Motivo de negação para alvos de escrita/destruição em área protegida.

    Cobre raiz de disco, raiz de compartilhamento UNC, pastas de sistema e a
    pasta do usuário inteira (fora ou dentro de ``allowed_roots``: apagar a
    raiz que contém o workspace também é negado).
    """
    p = norm_case(path)
    if p.parent == p:
        return "raiz de disco ou compartilhamento"
    for system in _system_dirs():
        if p == system or p.is_relative_to(system):
            return "pasta de sistema"
    home = norm_case(Path.home())
    if p == home:
        return "pasta do usuário"
    users_root = norm_case(Path.home().parent)
    if p == users_root:
        return "pasta de usuários"
    return None


def _system_dirs() -> list[Path]:
    """Pastas de sistema do Windows (normalizadas), com fallbacks portáveis."""
    candidates: list[Path] = []
    windir = os.environ.get("windir") or os.environ.get("SystemRoot") or r"C:\Windows"
    candidates.append(Path(windir))
    candidates.append(Path(windir) / "System32")
    candidates.append(Path(windir) / "SysWOW64")
    for key, fallback in (
        ("ProgramFiles", r"C:\Program Files"),
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ("ProgramData", r"C:\ProgramData"),
    ):
        candidates.append(Path(os.environ.get(key) or fallback))
    out: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(norm_case(candidate))
        if key not in seen:
            seen.add(key)
            out.append(norm_case(candidate))
    return out


def command_paths(text: str) -> list[Path]:
    """Caminhos absolutos (unidade/UNC) mencionados no texto de um comando."""
    found: list[Path] = []
    for match in _COMMAND_PATH_RE.finditer(text):
        token = match.group(0).strip().strip('"').rstrip(",;)")
        if len(token) < 3:
            continue
        try:
            found.append(Path(strip_extended_prefix(token)).resolve())
        except OSError:  # pragma: no cover - defensivo
            found.append(Path(strip_extended_prefix(token)))
    return found


def split_wildcard_prefix(raw: str) -> tuple[str, bool]:
    """Separa o prefixo real de um caminho com curinga: ``('C:\\dir/', True)``."""
    match = _WILDCARD_RE.search(raw)
    if not match:
        return raw, False
    return raw[: match.start()], True


def count_files(path: Path, cap: int = 500) -> int | None:
    """Conta arquivos de uma pasta (com teto) para a pré-visualização."""
    try:
        if not path.is_dir():
            return None
        total = 0
        for entry in path.rglob("*"):
            if entry.is_file():
                total += 1
                if total >= cap:
                    return cap
        return total
    except OSError as exc:
        log.debug("não consegui contar %s: %s", path, exc)
        return None

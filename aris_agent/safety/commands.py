"""Normalização de comandos e negações absolutas.

O texto é **normalizado** (caixa, aspas, crases, carets, variáveis ``%x%`` e
``$env:x``, wrappers ``cmd /c`` / ``powershell -c``) antes de comparar, para
dificultar contornos simples. Reduz o risco, mas **não é barreira perfeita**
(ver ``README.md``, seção "Limitações conhecidas").
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

# ---------------------------------------------------------------- normalização


def _env_value(name: str) -> str:
    """Valor praticável de uma variável de ambiente do Windows (ou marcador)."""
    key = name.lower()
    if key in ("windir", "systemroot"):
        return os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    if key == "systemdrive":
        return os.environ.get("SystemDrive") or "C:"
    if key == "userprofile":
        return os.environ.get("USERPROFILE") or str(Path.home())
    if key in ("temp", "tmp"):
        return os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
    if key == "appdata":
        return os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    if key == "localappdata":
        return os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    if key == "programdata":
        return os.environ.get("ProgramData") or r"C:\ProgramData"
    if key == "programfiles":
        return os.environ.get("ProgramFiles") or r"C:\Program Files"
    if key == "programfiles(x86)":
        return os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    if key in ("homedrive", "homepath"):
        return os.environ.get("HOMEDRIVE", "C:") + os.environ.get("HOMEPATH", "")
    return "__env__"


def normalize_command(text: str) -> str:
    """Normaliza um comando para comparação: caixa, aspas, escapes, variáveis."""
    out = str(text)
    out = re.sub(
        r"%([A-Za-z_][A-Za-z0-9_]*)%",
        lambda m: _env_value(m.group(1)),
        out,
    )
    out = re.sub(
        r"\$env:([A-Za-z_][A-Za-z0-9_]*)",
        lambda m: _env_value(m.group(1)),
        out,
        flags=re.IGNORECASE,
    )
    # Escape de cmd (^x) e de PowerShell (`x) não podem esconder letras.
    out = out.replace("^", "").replace("`", "")
    # Aspas removidas por completo: "fo rmat" não protege; fo"rmat" vira format.
    out = out.replace('"', "").replace("'", "")
    out = out.replace("\r\n", ";").replace("\n", ";").replace("\r", ";")
    out = out.lower()
    return re.sub(r"\s+", " ", out).strip()


def split_segments(text: str) -> list[str]:
    """Divide em segmentos por ``|``, ``;``, ``&``, ``&&`` (encadeamentos)."""
    parts = re.split(r"\s*(?:&&|&|\||;)\s*", text)
    return [p.strip() for p in parts if p.strip()]


_CMD_WRAPPERS = {"cmd", "cmd.exe", "cmd32"}
_PS_WRAPPERS = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
_PS_FLAGS = {"-c", "/c", "-command", "/command", "-enc", "-encodedcommand"}
_UNIX_WRAPPERS = {"sh", "bash", "zsh"}
_INTERPRETERS = {"python", "python3", "py"}


def strip_wrappers(segment: str, depth: int = 4) -> str:
    """Remove wrappers ``cmd /c``, ``powershell -c``, ``start``, ``sh -c``... recursivamente."""
    current = segment
    for _ in range(depth):
        tokens = current.split()
        if not tokens:
            break
        head = tokens[0]
        if head in ("start", "call", "invoke-expression", "iex"):
            current = " ".join(tokens[1:])
            continue
        if head in _CMD_WRAPPERS:
            flag = next(
                (i for i, tok in enumerate(tokens[1:7], start=1) if tok in ("/c", "/k", "-c", "-k")),
                None,
            )
            if flag is None:
                break
            current = " ".join(tokens[flag + 1 :])
            continue
        if head in _PS_WRAPPERS:
            flag = next(
                (i for i, tok in enumerate(tokens[1:8], start=1) if tok in _PS_FLAGS),
                None,
            )
            if flag is None:
                break
            current = " ".join(tokens[flag + 1 :])
            continue
        if head in _UNIX_WRAPPERS and len(tokens) > 1 and tokens[1] == "-c":
            current = " ".join(tokens[2:])
            continue
        break
    return current


def first_program(segment: str) -> str:
    """Primeiro token de um segmento, sem diretório e sem extensão (``C:\\Windows\\format.com`` -> ``format``)."""
    tokens = segment.split()
    if not tokens:
        return ""
    base = re.split(r"[\\/]", tokens[0])[-1]
    for ext in (".exe", ".com", ".bat", ".cmd", ".ps1"):
        if base.endswith(ext):
            base = base[: -len(ext)]
    return base


# --------------------------------------------------------------- negações

# Programas proibidos quando aparecem na posição de comando de um segmento.
_DENIED_PROGRAMS = frozenset(
    {
        "format",
        "format-volume",
        "diskpart",
        "bcdedit",
        "initialize-disk",
        "clear-disk",
        "new-partition",
        "remove-partition",
        "resize-partition",
        "cmdkey",
        "vaultcmd",
        "mimikatz",
    }
)

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # PowerShell ofuscado / base64
    (
        re.compile(r"(?:^|\s)-{1,2}(?:e|enc|encodedcommand)\s+[a-z0-9+/=]{16,}"),
        "PowerShell com -EncodedCommand (comando ofuscado em base64)",
    ),
    (
        re.compile(r"frombase64string[^;]{0,200}(?:iex|invoke-expression)|(?:iex|invoke-expression)[^;]{0,200}frombase64string"),
        "execução de payload base64 (FromBase64String + iex)",
    ),
    # Baixar e executar
    (
        re.compile(
            r"(?:iwr|invoke-webrequest|invoke-restmethod|irm|curl|wget|start-bitstransfer|certutil)"
            r"[^;|]*\|\s*(?:iex|invoke-expression)\b"
        ),
        "baixar e executar (requisição pipada para iex)",
    ),
    (
        re.compile(r"(?:curl|wget|iwr|invoke-webrequest)[^;|]*\|\s*(?:sh|bash|zsh|python3?|pwsh|powershell)\b"),
        "baixar e executar (curl/wget | sh)",
    ),
    # Desativar proteções
    (
        re.compile(r"set-mppreference\b[^;]*\s-disable\w*"),
        "desativar/proteções do Microsoft Defender (Set-MpPreference -Disable...)",
    ),
    (
        re.compile(r"(?:sc\s+(?:stop|config)|net\s+stop)\s+windefend\b"),
        "parar o serviço do Windows Defender",
    ),
    (
        re.compile(r"netsh\s+advfirewall\b[^;]*\bstate\s+off\b|netsh\s+advfirewall\s+set\b[^;]*\boff\b"),
        "desativar o firewall (netsh advfirewall ... off)",
    ),
    (
        re.compile(r"set-netfirewallprofile\b[^;]*-enabled\s+(?:false|0)\b"),
        "desativar o firewall (Set-NetFirewallProfile -Enabled False)",
    ),
    (
        re.compile(r"disableantispyware"),
        "desativar o Defender via registro (DisableAntiSpyware)",
    ),
    # Política de execução global
    (
        re.compile(
            r"set-executionpolicy\b(?![^;]*\s-scope\s+(?:process|currentuser)\b)[^;]*"
        ),
        "alterar a política de execução globalmente (Set-ExecutionPolicy fora de -Scope Process/CurrentUser)",
    ),
    # Registro: apagar chaves em HKLM
    (
        re.compile(r"\breg(?:\.exe)?\s+delete\b[^;]*(?:hklm|hkey_local_machine)"),
        "apagar chaves do registro em HKLM",
    ),
    (
        re.compile(r"remove-item\b[^;]*hklm:"),
        "apagar chaves do registro em HKLM (Remove-Item HKLM:)",
    ),
    # Cofres de credenciais
    (re.compile(r"(?:^|[\s;&|])cmdkey(?:\s|$)"), "gerenciador de credenciais (cmdkey)"),
    (re.compile(r"\bvaultcmd\b"), "cofre de credenciais do Windows (vaultcmd)"),
    (re.compile(r"\bmimikatz\b|\bsekurlsa\b"), "roubo de credenciais (mimikatz/sekurlsa)"),
)

# Marcadores que tornam um comando DESTRUTIVO (para efeito de confirmação forte).
_DESTRUCTIVE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:^|\s)(?:del|erase)(?:\s|$)"), "apaga arquivos (del/erase)"),
    (re.compile(r"(?:^|\s)(?:rd|rmdir)(?:\s|$)"), "apaga pastas (rd/rmdir)"),
    (re.compile(r"(?:^|\s)rm(?:\s|$)"), "apaga arquivos/pastas (rm)"),
    (re.compile(r"\bremove-item\b"), "Remove-Item"),
    (re.compile(r"\bclear-(?:content|item)\b"), "Clear-Content/Clear-Item"),
    (re.compile(r"\breg\s+delete\b"), "apagar chave de registro (reg delete)"),
    (re.compile(r"(?:^|\s)(?:taskkill|shutdown|logoff)(?:\s|$)"), "finalizar processos/sessão"),
    (re.compile(r"\bstop-process\b"), "finalizar processo (Stop-Process)"),
    (re.compile(r"\bstop-service\b"), "parar serviço (Stop-Service)"),
    (re.compile(r"(?:^|\s)(?:net|sc)\s+stop(?:\s|$)"), "parar serviço (net/sc stop)"),
    (re.compile(r"\brestart-computer\b"), "reiniciar o computador"),
    (re.compile(r"(?:^|\s)move(?:\s|$)"), "move/apaga origem (move)"),
)


def denied_command_reason(raw: str) -> str | None:
    """Motivo de negação absoluta do comando, ou ``None`` se não for proibido."""
    text = normalize_command(raw)
    if not text:
        return None
    for pattern, reason in _RULES:
        if pattern.search(text):
            return reason
    for segment in split_segments(text):
        program = first_program(strip_wrappers(segment))
        if program in _DENIED_PROGRAMS:
            return f"comando proibido: {program}"
    return None


def destructive_command_reason(raw: str) -> str | None:
    """Motivo que torna o comando destrutivo (risco efetivo vira DESTRUCTIVE)."""
    text = normalize_command(raw)
    if not text:
        return None
    for pattern, reason in _DESTRUCTIVE_RULES:
        if pattern.search(text):
            return reason
    return None


def is_allowlisted_command(raw: str, entries: tuple[str, ...]) -> bool:
    """O comando casa com a lista de permissões (1º token ou prefixo com espaço)."""
    text = normalize_command(raw)
    if not text:
        return False
    tokens = text.split()
    first = tokens[0]
    for entry in entries:
        entry = entry.strip().lower()
        if not entry:
            continue
        if " " in entry:
            if text == entry or text.startswith(entry + " "):
                return True
        elif first == entry:
            return True
    return False


def balanced_segments_ok(raw: str, allowed: tuple[str, ...]) -> bool:
    """Todos os segmentos começam por um verbo seguro do modo balanced?"""
    text = normalize_command(raw)
    if not text:
        return False
    verbs = {entry.split(" ")[0] for entry in allowed}
    for segment in split_segments(text):
        program = first_program(strip_wrappers(segment))
        if not program or program not in verbs:
            return False
    return True

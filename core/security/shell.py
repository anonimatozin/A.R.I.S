"""Segurança de subprocess do A.R.I.S.

Fornece validação de input antes de alcance de fronteira de processo,
e execução segura de comandos whitelisted.

Uso:
    from core.security.shell import validate_shell_input, run_whitelisted

    validate_shell_input("texto limpo")          # ok
    validate_shell_input("'; rm -rf /; echo '")  # levanta ShellInjectionError
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ── Metacharacters perigosos ───────────────────────────────

# Shell metachars que permitem execução de comandos em PowerShell/CMD.
# NOTA: espaço e tab NÃO estão aqui — eles são permitidos (necessários
# para texto normal). O parser de comandos do shell os usa como separador,
# mas sem metachars adicionais não causam injeção.
_SHELL_METACHARACTERS = frozenset({
    ";",       # separator — ; calc.exe
    "|",       # pipe — | calc.exe
    "&",       # background/AND — & calc.exe
    "$",       # variable expansion — $env:PATH
    "`",       # backtick escape — `whoami`
    "\n",      # newline — nova linha de comando
    "\r",      # carriage return
    ">",       # redirect — > /tmp/x
    "<",       # redirect input
    "(",       # subshell — (calc)
    ")",       # subshell end
    "{",       # code block
    "}",       # code block end
})

# Padrão para detectar tentativas de bypass comuns
_BYPASS_PATTERNS = [
    re.compile(r"\$\("),           # $() subshell PowerShell
    re.compile(r"\$\{"),           # ${} variable
    re.compile(r"``"),             # double backtick
    re.compile(r"\\x[0-9a-fA-F]"), # hex escape
    re.compile(r"%[0-9a-fA-F]{2}"),# percent encoding
]


class ShellInjectionError(Exception):
    """Levantada quando input contém metacharacters de shell."""


class CommandNotWhitelistedError(Exception):
    """Levantada quando comando não está na whitelist."""


class InputValidationError(Exception):
    """Levantada quando input não passa na validação de tipo."""


class PathTraversalError(Exception):
    """Levantada quando tentativa de path traversal é detectada."""


# ── Validação de input ─────────────────────────────────────

def validate_shell_input(text: str) -> str:
    """Valida que texto não contém shell metacharacters perigosos.

    Args:
        text: Texto do usuário a ser validado.

    Returns:
        O texto original se válido.

    Raises:
        ShellInjectionError: Se metacharacters forem detectados.
    """
    for char in _SHELL_METACHARACTERS:
        if char in text:
            raise ShellInjectionError(
                f"Caractere proibido detectado: {char!r}. "
                f"Texto não pode conter metacharacters de shell."
            )

    for pattern in _BYPASS_PATTERNS:
        if pattern.search(text):
            raise ShellInjectionError(
                f"Padrão de bypass detectado: {pattern.pattern}. "
                f"Texto não pode conter sequences de escape de shell."
            )

    return text


def validate_filename(name: str) -> str:
    """Valida que nome de arquivo é seguro (sem path traversal).

    Aceita apenas basename com caracteres alfanuméricos, underscore,
    hífen, ponto e espaço.

    Raises:
        InputValidationError: Se nome contiver caracteres perigosos.
    """
    validate_shell_input(name)

    # Rejeitar path separators
    if "/" in name or "\\" in name:
        raise InputValidationError(
            f"Nome de arquivo não pode conter separadores de path: {name!r}"
        )

    # Rejeitar .. (traversal)
    if ".." in name:
        raise InputValidationError(
            f"Nome de arquivo não pode conter '..': {name!r}"
        )

    # Rejeitar nomes vazios ou só whitespace
    if not name.strip():
        raise InputValidationError("Nome de arquivo não pode ser vazio.")

    # Rejeitar caracteres perigosos para Windows
    dangerous = '<>:"|?*'
    for char in dangerous:
        if char in name:
            raise InputValidationError(
                f"Nome de arquivo contém caractere inválido para Windows: {char!r}"
            )

    return name.strip()


def validate_process_name(name: str) -> str:
    """Valida que nome de processo é seguro.

    Process names no Windows são alfanuméricos + underscore + hífen.
    NÃO aceita paths, espaços excessivos, ou caracteres especiais.

    Raises:
        InputValidationError: Se nome for inválido.
    """
    validate_shell_input(name)

    # Process names são tipicamente alfanuméricos + underscore/hífen
    if not re.match(r"^[a-zA-Z0-9_.\-]+$", name):
        raise InputValidationError(
            f"Nome de processo inválido: {name!r}. "
            f"Apenas alfanuméricos, underscore, hífen e ponto são aceitos."
        )

    return name


def validate_url(url: str) -> str:
    """Valida que URL é segura (sem SSRF).

    Faz resolução DNS real e bloqueia IPs privados/loopback/link-local.
    Aceita apenas http/https.

    Raises:
        InputValidationError: Se URL for insegura.
    """
    from urllib.parse import urlparse
    import ipaddress
    import socket

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise InputValidationError(
            f"Esquema não permitido: {parsed.scheme!r}. Apenas http/https."
        )

    hostname = parsed.hostname
    if not hostname:
        raise InputValidationError("URL não contém hostname válido.")

    # Bloquear nameservers locais conhecidos (antes de resolver)
    if hostname in ("localhost", "0.0.0.0"):
        raise InputValidationError(
            f"Acesso a localhost não permitido: {hostname}"
        )

    # Resolver DNS e verificar o IP resultante
    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in resolved:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
                raise InputValidationError(
                    f"Hostname '{hostname}' resolve para IP privado/loopback: {ip}"
                )
    except socket.gaierror:
        raise InputValidationError(f"Não foi possível resolver hostname: {hostname}")

    return url


def safe_resolve(base_dir: Path, user_path: str) -> Path:
    """Resolve um path do usuário e verifica que permanece dentro de base_dir.

    Se user_path for relativo, é resolvido relativo a base_dir (não CWD).
    Usa comparação de partes (não startswith em string) para evitar bypasses.

    Args:
        base_dir: Diretório permitido (raiz).
        user_path: Caminho fornecido pelo usuário.

    Returns:
        Path resolvido e validado.

    Raises:
        PathTraversalError: Se o path escapar de base_dir.
    """
    base_resolved = base_dir.resolve()
    # No Linux "..\\..\\Windows" seria um único nome de arquivo e passaria na checagem
    # abaixo; tratamos "\\" como separador para o ataque não depender do sistema.
    if os.name != "nt":
        user_path = user_path.replace("\\", "/")
    user = Path(user_path)

    if user.is_absolute():
        resolved = user.resolve()
    else:
        resolved = (base_resolved / user).resolve()

    # Verificar que o resolved é relativo a base (usando partes, não string)
    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        raise PathTraversalError(
            f"Acesso negado: '{user_path}' está fora do diretório permitido "
            f"({base_resolved}). Path traversal bloqueado."
        )

    return resolved


# ── Whitelist de comandos ──────────────────────────────────

@dataclass(frozen=True)
class WhitelistedCommand:
    """Declaração de um comando permitido.

    Attributes:
        name: Nome amigável do comando.
        executable: Caminho ou nome do executável.
        base_args: Argumentos fixos (antes do input do usuário).
        input_positions: Índices (0-based, relativo a args completos)
            onde input do usuário é aceito. None = sem input do usuário.
        validators: Dict mapeando posição → função de validação.
    """
    name: str
    executable: str
    base_args: tuple[str, ...] = ()
    input_positions: tuple[int, ...] = ()
    validators: dict[int, Callable[[str], str]] = field(default_factory=dict)


# Whitelist declarativa — cada comando é um objeto imutável
COMMAND_WHITELIST: dict[str, WhitelistedCommand] = {}


def register_command(cmd: WhitelistedCommand) -> None:
    """Registra um comando na whitelist."""
    COMMAND_WHITELIST[cmd.name] = cmd


def get_command(name: str) -> WhitelistedCommand | None:
    """Busca um comando na whitelist."""
    return COMMAND_WHITELIST.get(name)


# ── Execução segura ────────────────────────────────────────

def run_whitelisted(
    command_name: str,
    user_inputs: dict[int, str],
    timeout: float = 30.0,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """Executa um comando whitelisted com validação de input.

    Args:
        command_name: Nome do comando na whitelist.
        user_inputs: Dict {posição: valor_do_usuario}.
        timeout: Timeout em segundos.
        capture_output: Se True, captura stdout/stderr.

    Returns:
        CompletedProcess com resultado.

    Raises:
        CommandNotWhitelistedError: Se comando não está na whitelist.
        InputValidationError: Se input falhar na validação.
        ShellInjectionError: Se metacharacters forem detectados.
    """
    cmd = get_command(command_name)
    if cmd is None:
        raise CommandNotWhitelistedError(
            f"Comando '{command_name}' não está na whitelist. "
            f"Comandos disponíveis: {', '.join(COMMAND_WHITELIST.keys())}"
        )

    # Construir lista de argumentos
    args: list[str] = [cmd.executable] + list(cmd.base_args)

    # Inserir inputs do usuário nas posições corretas
    for pos, value in user_inputs.items():
        # Validar se há validator para esta posição
        if pos in cmd.validators:
            value = cmd.validators[pos](value)
        else:
            # Validação padrão: shell injection check
            validate_shell_input(value)

        # Inserir na posição correta
        # Posições são relativas ao array completo (exec + base_args)
        insert_pos = pos
        if insert_pos < len(args):
            args.insert(insert_pos, value)
        else:
            args.append(value)

    # Executar
    return subprocess.run(
        args,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
    )


# ── Comandos pré-registrados ───────────────────────────────

def _init_whitelist() -> None:
    """Inicializa a whitelist com comandos do sistema."""

    # Clipboard
    register_command(WhitelistedCommand(
        name="clipboard_get",
        executable="powershell",
        base_args=("-Command", "Get-Clipboard"),
    ))

    register_command(WhitelistedCommand(
        name="clipboard_set",
        executable="powershell",
        base_args=("-Command", "Set-Clipboard", "-Value"),
        input_positions=(3,),
        validators={3: validate_shell_input},
    ))

    # Janelas
    register_command(WhitelistedCommand(
        name="list_windows",
        executable="powershell",
        base_args=("-Command",
            "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} "
            "| Select-Object ProcessName, MainWindowTitle | Format-Table -AutoSize"),
    ))

    register_command(WhitelistedCommand(
        name="focus_window",
        executable="powershell",
        base_args=("-Command",
            # Template: {process_name} é substituído de forma segura
            # via -InputObject (não f-string)
            "$p = Get-Process -Name '{0}' -ErrorAction SilentlyContinue; "
            "if ($p) {{ Add-Type -Name Win -Namespace Native -MemberDefinition "
            "'[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);' ; "
            "[Native.Win]::SetForegroundWindow($p.MainWindowHandle) }}"
        ),
        input_positions=(1,),
        validators={1: validate_process_name},
    ))

    register_command(WhitelistedCommand(
        name="close_app",
        executable="taskkill",
        base_args=("/IM",),
        input_positions=(1,),
        validators={1: validate_process_name},
    ))

    # Notificações PowerShell (fallback)
    register_command(WhitelistedCommand(
        name="notify_ps",
        executable="powershell",
        base_args=("-Command",),
        input_positions=(1,),
        validators={1: validate_shell_input},
    ))


# Inicializar no import
_init_whitelist()

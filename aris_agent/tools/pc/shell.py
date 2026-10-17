"""Execução de comandos (PowerShell/cmd no Windows, sh/bash no POSIX) e de código Python em subprocesso."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import (
    bounded_float,
    communicate,
    decode_bytes,
    err,
    filter_env,
    guarded,
    ok_result,
    out,
    resolve_path,
    schema,
)

log = logging.getLogger("aris.agent.tools.pc.shell")

SPEC_RUN_COMMAND = ToolSpec(
    name="pc_run_command",
    description=(
        "Executa um comando no shell do sistema (PowerShell/cmd no Windows, "
        "sh/bash no Linux/macOS) e devolve saída, erro e código de retorno."
    ),
    parameters=schema(
        {
            "command": {"type": "string", "description": "Comando a executar (texto literal)."},
            "shell": {
                "type": "string",
                "enum": ["powershell", "cmd", "sh", "bash"],
                "description": "Interpretador (padrão: powershell no Windows, sh no POSIX).",
            },
            "cwd": {"type": "string", "description": "Pasta de trabalho do comando."},
            "timeout_s": {
                "type": "number",
                "description": "Limite em segundos (padrão 30, até 300).",
                "minimum": 1,
                "maximum": 300,
            },
        },
        required=("command",),
    ),
    risk=Risk.EXEC,
    tags=("pc", "shell"),
    path_args=("cwd",),
    command_arg="command",
    timeout_s=60.0,
)

SPEC_PYTHON_RUN = ToolSpec(
    name="pc_python_run",
    description=(
        "Executa código Python em subprocesso isolado (pasta temporária, modo -I, "
        "sem variáveis sensíveis no ambiente), com timeout."
    ),
    parameters=schema(
        {
            "code": {"type": "string", "description": "Código Python completo a executar."},
            "timeout_s": {
                "type": "number",
                "description": "Limite em segundos (padrão 30, até 300).",
                "minimum": 1,
                "maximum": 300,
            },
        },
        required=("code",),
    ),
    risk=Risk.EXEC,
    tags=("pc", "shell", "code"),
    command_arg="code",
    timeout_s=45.0,
)

_POWERSHELL_ARGS = ("powershell", "-NoProfile", "-NonInteractive", "-Command")


def _finish(
    ctx: ToolContext,
    stdout: bytes,
    stderr: bytes,
    returncode: int | None,
    problema: str | None,
    timeout_s: float,
) -> ToolResult:
    """Monta o ToolResult comum dos dois subprocessos."""
    texto_out = decode_bytes(stdout).strip()
    texto_err = decode_bytes(stderr).strip()
    if problema == "timeout":
        parcial = (texto_out + "\n" + texto_err).strip()
        sufixo = f"\nsaída parcial: {parcial[:500]}" if parcial else ""
        return err(f"timeout após {timeout_s:g}s; processo (e filhos) morto.{sufixo}")
    if problema == "cancelado":
        return err(f"cancelado pelo agente após {timeout_s:g}s; processo (e filhos) morto.")
    if problema:
        return err(f"falha ao executar: {problema}")

    partes = [f"código de saída: {returncode}"]
    partes.append("--- saída ---\n" + (texto_out or "(vazio)"))
    if texto_err:
        partes.append("--- erro ---\n" + texto_err)
    return ok_result(
        out(ctx, "\n".join(partes)),
        data={
            "returncode": returncode,
            "stdout": texto_out,
            "stderr": texto_err,
        },
    )


def _rmtree_retry(path: Path) -> None:
    """Remove a pasta temporária; o Windows ainda segura handles logo após o kill."""
    for tentativa in range(20):
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            if tentativa == 19:
                log.warning("não consegui remover %s: %s", path, exc)
                shutil.rmtree(path, ignore_errors=True)
                return
            time.sleep(0.25)


@function_tool(SPEC_RUN_COMMAND)
@guarded
def pc_run_command(args: dict, ctx: ToolContext) -> ToolResult:
    """Executa comando em PowerShell/cmd com cwd, timeout e árvore de processos morta."""
    command = str(args.get("command") or "").strip()
    if not command:
        return err("command vazio")

    # cwd primeiro: a guarda de raízes vale antes de qualquer interpretador.
    cwd: str | None = None
    raw_cwd = args.get("cwd")
    if raw_cwd:
        folder = resolve_path(raw_cwd, ctx, arg="cwd", must_exist=True)
        if not folder.is_dir():
            return err(f"cwd não é uma pasta: {folder}")
        cwd = str(folder)

    default_shell = "powershell" if os.name == "nt" else "sh"
    shell = str(args.get("shell") or default_shell).strip().lower()
    validos = {"powershell", "cmd"} if os.name == "nt" else {"sh", "bash"}
    if shell not in validos:
        if os.name == "nt":
            return err(f"shell desconhecido: {shell!r} (use powershell ou cmd)")
        return err(
            f"shell indisponível: {shell!r} (neste sistema use {' ou '.join(sorted(validos))})"
        )
    timeout_s = bounded_float(args, "timeout_s", 30.0, 1.0, 300.0)

    if shell in {"sh", "bash"}:
        exe = shutil.which(shell) or f"/bin/{shell}"
        popen_args = [exe, "-c", command]
    elif shell == "cmd":
        # cmd entende a linha de comando como texto: passa como uma string só.
        cmdline = f'cmd /d /s /c "{command}"'
        popen_args = cmdline
    else:
        popen_args = [*_POWERSHELL_ARGS, command]

    log.info("pc_run_command [%s]: %s", shell, command[:200])
    try:
        proc = subprocess.Popen(  # execução é a finalidade desta ferramenta
            popen_args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        return err(
            f"não consegui iniciar o {shell} ({exc}). "
            "O executável pode estar bloqueado por política/AppLocker do Windows."
        )
    stdout, stderr, returncode, problema = communicate(proc, timeout_s, ctx.cancel)
    return _finish(ctx, stdout, stderr, returncode, problema, timeout_s)


@function_tool(SPEC_PYTHON_RUN)
@guarded
def pc_python_run(args: dict, ctx: ToolContext) -> ToolResult:
    """Roda código Python isolado: pasta temporária, ``-I -B -X utf8``, ambiente filtrado."""
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        return err("code vazio")
    timeout_s = bounded_float(args, "timeout_s", 30.0, 1.0, 300.0)

    tmp = Path(tempfile.mkdtemp(prefix="aris_py_"))
    try:
        script = tmp / "script.py"
        script.write_text(code, encoding="utf-8")
        env = filter_env()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [sys.executable, "-I", "-B", "-X", "utf8", str(script)],
            cwd=str(tmp),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        stdout, stderr, returncode, problema = communicate(proc, timeout_s, ctx.cancel)
    finally:
        _rmtree_retry(tmp)
    return _finish(ctx, stdout, stderr, returncode, problema, timeout_s)

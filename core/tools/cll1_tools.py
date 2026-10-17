"""CLL1 Tools — ferramentas que executam no CLL1 (edge device).

Todas passam por SecurityGate + audit. Credenciais nunca vao pro LLM.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any


def _run_cmd(cmd: str, timeout: int = 30) -> dict[str, Any]:
    """Executa comando no CLL1 e retorna resultado (sem shell exposto)."""
    import shlex as _shlex
    try:
        start = time.time()
        try:
            argv = _shlex.split(cmd, posix=True)
        except Exception:
            return {"ok": False, "error": "Parse error",
                    "duration_ms": 0, "returncode": -1, "stdout": "", "stderr": ""}
        if not argv:
            return {"ok": False, "error": "Empty command",
                    "duration_ms": 0, "returncode": -1, "stdout": "", "stderr": ""}
        for tok in argv[1:]:
            if tok in (";", "&&", "||", "|", "`", ">", "<", "$", "$("):
                return {"ok": False, "error": "Shell metacharacter not allowed",
                        "duration_ms": 0, "returncode": -1, "stdout": "", "stderr": ""}
            if "$(" in tok or "`" in tok:
                return {"ok": False, "error": "Shell expansion not allowed",
                        "duration_ms": 0, "returncode": -1, "stdout": "", "stderr": ""}
        if argv[0].lower() == "echo":
            return {"ok": True, "stdout": " ".join(argv[1:]),
                    "stderr": "", "returncode": 0,
                    "duration_ms": int((time.time() - start) * 1000)}
        result = subprocess.run(
            argv, shell=False, capture_output=True, text=True, timeout=timeout
        )
        duration = int((time.time() - start) * 1000)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
            "duration_ms": duration,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "duration_ms": timeout * 1000}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Status ────────────────────────────────────────────────────

def cll1_status() -> dict[str, Any]:
    """Status geral do CLL1."""
    return _run_cmd("sv status cll1-main")


def cll1_system_info() -> dict[str, Any]:
    """Informacoes do sistema."""
    return _run_cmd("uname -a")


def cll1_uptime() -> dict[str, Any]:
    """Uptime do sistema."""
    return _run_cmd("uptime")


def cll1_disk() -> dict[str, Any]:
    """Uso de disco."""
    return _run_cmd("df -h /")


def cll1_memory() -> dict[str, Any]:
    """Uso de memoria."""
    return _run_cmd("free -h")


def cll1_cpu() -> dict[str, Any]:
    """Uso de CPU."""
    return _run_cmd("top -bn1 | head -5")


def cll1_network() -> dict[str, Any]:
    """Info de rede."""
    return _run_cmd("ip addr show wlan0 2>/dev/null || ip addr show")


# ── Processos ─────────────────────────────────────────────────

def cll1_process_list() -> dict[str, Any]:
    """Lista processos."""
    return _run_cmd("ps aux --sort=-%mem | head -20")


def cll1_process_status(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Status de um processo especifico."""
    pid = (params or {}).get("pid", "")
    if not pid:
        return {"ok": False, "error": "pid required"}
    return _run_cmd(f"ps -p {pid} -o pid,ppid,cmd,%mem,%cpu")


def cll1_process_stop(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Para um processo (HIGH - requer confirmacao)."""
    pid = (params or {}).get("pid", "")
    signal = (params or {}).get("signal", "TERM")
    if not pid:
        return {"ok": False, "error": "pid required"}
    return _run_cmd(f"kill -{signal} {pid}")


# ── Servicos ──────────────────────────────────────────────────

def cll1_service_list() -> dict[str, Any]:
    """Lista servicos."""
    return _run_cmd("sv status /var/run/service/*")


def cll1_service_status(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Status de um servico."""
    svc = (params or {}).get("service", "cll1-main")
    return _run_cmd(f"sv status {svc}")


def cll1_service_restart(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reinicia um servico (HIGH - requer confirmacao)."""
    svc = (params or {}).get("service", "cll1-main")
    return _run_cmd(f"sv restart {svc}")


# ── Arquivos ──────────────────────────────────────────────────

def cll1_list_files(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lista arquivos em um diretorio."""
    path = (params or {}).get("path", ".")
    return _run_cmd(f"ls -la {path}")


def cll1_read_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Le um arquivo."""
    path = (params or {}).get("path", "")
    if not path:
        return {"ok": False, "error": "path required"}
    return _run_cmd(f"cat {path}")


def cll1_write_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Escreve em um arquivo (MODERATE)."""
    params = params or {}
    path = params.get("path", "")
    content = params.get("content", "")
    if not path:
        return {"ok": False, "error": "path required"}
    import shlex
    escaped = shlex.quote(content)
    return _run_cmd(f"echo {escaped} > {path}")


def cll1_edit_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Edita um arquivo (MODERATE)."""
    params = params or {}
    path = params.get("path", "")
    old = params.get("old", "")
    new = params.get("new", "")
    if not path or not old:
        return {"ok": False, "error": "path and old required"}
    import shlex
    old_esc = shlex.quote(old)
    new_esc = shlex.quote(new)
    return _run_cmd(f"sed -i 's/{old_esc}/{new_esc}/g' {path}")


def cll1_create_directory(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cria um diretorio (MODERATE)."""
    path = (params or {}).get("path", "")
    if not path:
        return {"ok": False, "error": "path required"}
    return _run_cmd(f"mkdir -p {path}")


def cll1_copy_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Copia um arquivo (MODERATE)."""
    params = params or {}
    src = params.get("source", "")
    dst = params.get("destination", "")
    if not src or not dst:
        return {"ok": False, "error": "source and destination required"}
    return _run_cmd(f"cp {src} {dst}")


def cll1_move_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Move um arquivo (MODERATE)."""
    params = params or {}
    src = params.get("source", "")
    dst = params.get("destination", "")
    if not src or not dst:
        return {"ok": False, "error": "source and destination required"}
    return _run_cmd(f"mv {src} {dst}")


def cll1_search_files(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Busca arquivos por nome/conteudo."""
    params = params or {}
    pattern = params.get("pattern", "")
    path = params.get("path", ".")
    if not pattern:
        return {"ok": False, "error": "pattern required"}
    return _run_cmd(f"find {path} -name '*{pattern}*' -type f 2>/dev/null | head -20")


# ── Terminal & Logs ───────────────────────────────────────────

def cll1_terminal(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa comando no terminal seguro do CLL1 (HIGH)."""
    cmd = (params or {}).get("command", "")
    if not cmd:
        return {"ok": False, "error": "command required"}
    return _run_cmd(cmd, timeout=60)


def cll1_logs(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Le logs do CLL1."""
    params = params or {}
    log_file = params.get("file", "cll1.log")
    lines = params.get("lines", 50)
    log_dir = os.path.expanduser("~/cll1/logs")
    log_path = os.path.join(log_dir, log_file)
    return _run_cmd(f"tail -n {lines} {log_path} 2>/dev/null || echo 'Log not found'")


def cll1_logs_search(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Busca nos logs."""
    params = params or {}
    query = params.get("query", "")
    log_file = params.get("file", "cll1.log")
    if not query:
        return {"ok": False, "error": "query required"}
    log_dir = os.path.expanduser("~/cll1/logs")
    log_path = os.path.join(log_dir, log_file)
    import shlex
    return _run_cmd(f"grep -i {shlex.quote(query)} {log_path} 2>/dev/null | tail -20")


# ── Tool Registry ─────────────────────────────────────────────

CLL1_TOOLS: dict[str, dict[str, Any]] = {
    "cll1_status": {"fn": cll1_status, "permission": "safe", "description": "Status geral do CLL1"},
    "cll1_system_info": {"fn": cll1_system_info, "permission": "safe", "description": "Info do sistema"},
    "cll1_uptime": {"fn": cll1_uptime, "permission": "safe", "description": "Uptime do CLL1"},
    "cll1_disk": {"fn": cll1_disk, "permission": "safe", "description": "Uso de disco"},
    "cll1_memory": {"fn": cll1_memory, "permission": "safe", "description": "Uso de memoria"},
    "cll1_cpu": {"fn": cll1_cpu, "permission": "safe", "description": "Uso de CPU"},
    "cll1_network": {"fn": cll1_network, "permission": "safe", "description": "Rede do CLL1"},
    "cll1_process_list": {"fn": cll1_process_list, "permission": "safe", "description": "Lista processos"},
    "cll1_process_status": {"fn": cll1_process_status, "permission": "safe", "description": "Status processo"},
    "cll1_process_stop": {"fn": cll1_process_stop, "permission": "high", "description": "Parar processo"},
    "cll1_service_list": {"fn": cll1_service_list, "permission": "safe", "description": "Lista servicos"},
    "cll1_service_status": {"fn": cll1_service_status, "permission": "safe", "description": "Status servico"},
    "cll1_service_restart": {"fn": cll1_service_restart, "permission": "high", "description": "Reiniciar servico"},
    "cll1_list_files": {"fn": cll1_list_files, "permission": "safe", "description": "Listar arquivos"},
    "cll1_read_file": {"fn": cll1_read_file, "permission": "safe", "description": "Ler arquivo"},
    "cll1_write_file": {"fn": cll1_write_file, "permission": "moderate", "description": "Escrever arquivo"},
    "cll1_edit_file": {"fn": cll1_edit_file, "permission": "moderate", "description": "Editar arquivo"},
    "cll1_create_directory": {"fn": cll1_create_directory, "permission": "moderate", "description": "Criar diretorio"},
    "cll1_copy_file": {"fn": cll1_copy_file, "permission": "moderate", "description": "Copiar arquivo"},
    "cll1_move_file": {"fn": cll1_move_file, "permission": "moderate", "description": "Mover arquivo"},
    "cll1_search_files": {"fn": cll1_search_files, "permission": "safe", "description": "Buscar arquivos"},
    "cll1_terminal": {"fn": cll1_terminal, "permission": "high", "description": "Terminal seguro"},
    "cll1_logs": {"fn": cll1_logs, "permission": "safe", "description": "Logs do CLL1"},
    "cll1_logs_search": {"fn": cll1_logs_search, "permission": "safe", "description": "Buscar nos logs"},
    "cll1_service_restart": {"fn": cll1_service_restart, "permission": "high", "description": "Reiniciar servico"},
}


def execute_cll1_tool(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa uma tool do CLL1 pelo nome."""
    tool = CLL1_TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": f"Unknown CLL1 tool: {name}"}
    fn = tool["fn"]
    try:
        return fn(params)
    except Exception as e:
        return {"ok": False, "error": str(e)}

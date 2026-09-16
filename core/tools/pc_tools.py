"""PC Tools — ferramentas que executam no PC Windows.

Sandbox/path protection obrigatorio. Path traversal bloqueado pelo SecurityGate.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time
from typing import Any


def _safe_path(base: str, path: str) -> str | None:
    """Verifica se o path e seguro (sem traversal)."""
    try:
        resolved = os.path.normpath(os.path.join(base, path))
        if not resolved.startswith(os.path.normpath(base)):
            return None
        return resolved
    except Exception:
        return None


def _run_cmd(cmd: str, timeout: int = 30, cwd: str | None = None) -> dict[str, Any]:
    """Executa comando no PC."""
    try:
        start = time.time()
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd
        )
        duration = int((time.time() - start) * 1000)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip()[:5000],
            "stderr": result.stderr.strip()[:2000],
            "returncode": result.returncode,
            "duration_ms": duration,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Arquivos ──────────────────────────────────────────────────

def pc_list_files(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lista arquivos no PC."""
    params = params or {}
    path = params.get("path", ".")
    try:
        entries = []
        for entry in os.scandir(path):
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return {"ok": True, "files": entries, "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pc_read_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Le arquivo do PC."""
    params = params or {}
    path = params.get("path", "")
    if not path:
        return {"ok": False, "error": "path required"}
    try:
        encoding = params.get("encoding", "utf-8")
        with open(path, encoding=encoding, errors="replace") as f:
            content = f.read(100000)  # max 100KB
        return {"ok": True, "content": content, "size": len(content)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pc_write_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Escreve arquivo no PC (MODERATE)."""
    params = params or {}
    path = params.get("path", "")
    content = params.get("content", "")
    if not path:
        return {"ok": False, "error": "path required"}
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "size": len(content)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pc_edit_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Edita arquivo no PC — substitui old por new (MODERATE)."""
    params = params or {}
    path = params.get("path", "")
    old = params.get("old", "")
    new = params.get("new", "")
    if not path or not old:
        return {"ok": False, "error": "path and old required"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if old not in content:
            return {"ok": False, "error": "old text not found in file"}
        content = content.replace(old, new, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "replaced": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pc_create_directory(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cria diretorio no PC (MODERATE)."""
    params = params or {}
    path = params.get("path", "")
    if not path:
        return {"ok": False, "error": "path required"}
    try:
        os.makedirs(path, exist_ok=True)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pc_search_files(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Busca arquivos por padrao no PC."""
    params = params or {}
    pattern = params.get("pattern", "*")
    path = params.get("path", ".")
    max_results = params.get("max_results", 50)
    try:
        search = os.path.join(path, "**", pattern)
        matches = glob.glob(search, recursive=True)[:max_results]
        files = []
        for m in matches:
            try:
                stat = os.stat(m)
                files.append({
                    "path": m,
                    "name": os.path.basename(m),
                    "size": stat.st_size,
                    "is_dir": os.path.isdir(m),
                })
            except Exception:
                files.append({"path": m, "name": os.path.basename(m)})
        return {"ok": True, "files": files, "count": len(files)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pc_copy_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Copia arquivo no PC (MODERATE)."""
    params = params or {}
    src = params.get("source", "")
    dst = params.get("destination", "")
    if not src or not dst:
        return {"ok": False, "error": "source and destination required"}
    try:
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pc_move_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Move arquivo no PC (MODERATE)."""
    params = params or {}
    src = params.get("source", "")
    dst = params.get("destination", "")
    if not src or not dst:
        return {"ok": False, "error": "source and destination required"}
    try:
        shutil.move(src, dst)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def pc_delete_file(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deleta arquivo no PC (HIGH - requer confirmacao)."""
    params = params or {}
    path = params.get("path", "")
    if not path:
        return {"ok": False, "error": "path required"}
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Terminal & Sistema ────────────────────────────────────────

def pc_run_command(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa comando no PC (HIGH)."""
    params = params or {}
    cmd = params.get("command", "")
    if not cmd:
        return {"ok": False, "error": "command required"}
    timeout = min(int(params.get("timeout", 30)), 120)
    cwd = params.get("cwd")
    return _run_cmd(cmd, timeout=timeout, cwd=cwd)


def pc_processes() -> dict[str, Any]:
    """Lista processos do PC."""
    return _run_cmd("tasklist /FO CSV /NH", timeout=10)


def pc_services() -> dict[str, Any]:
    """Lista servicos do PC."""
    return _run_cmd("net start", timeout=10)


def pc_logs(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Le logs do PC."""
    params = params or {}
    log_name = params.get("log", "Application")
    count = params.get("count", 50)
    return _run_cmd(
        f'powershell -Command "Get-EventLog -LogName {log_name} -Newest {count} | Select-Object TimeGenerated,EntryType,Message | ConvertTo-Json"',
        timeout=15,
    )


def pc_system_status() -> dict[str, Any]:
    """Status do PC."""
    return _run_cmd(
        'powershell -Command "Get-ComputerInfo | Select-Object CsName,WindowsVersion,OsArchitecture,CsTotalPhysicalMemory | ConvertTo-Json"',
        timeout=15,
    )


# ── PC Control (Phase H) ──────────────────────────────────────

from core.tools.pc_control import get_pc_control


def pc_shutdown(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Desliga o PC (CRITICAL - requer confirmacao)."""
    return get_pc_control().pc_shutdown(params)


def pc_restart(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reinicia o PC (CRITICAL - requer confirmacao)."""
    return get_pc_control().pc_restart(params)


def pc_lock(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bloqueia o PC (HIGH)."""
    return get_pc_control().pc_lock(params)


def pc_sleep(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Suspender o PC (HIGH)."""
    return get_pc_control().pc_sleep(params)


# ── Tool Registry ─────────────────────────────────────────────

PC_TOOLS: dict[str, dict[str, Any]] = {
    "pc_list_files": {"fn": pc_list_files, "permission": "safe", "description": "Listar arquivos PC"},
    "pc_read_file": {"fn": pc_read_file, "permission": "safe", "description": "Ler arquivo PC"},
    "pc_write_file": {"fn": pc_write_file, "permission": "moderate", "description": "Escrever arquivo PC"},
    "pc_edit_file": {"fn": pc_edit_file, "permission": "moderate", "description": "Editar arquivo PC"},
    "pc_create_directory": {"fn": pc_create_directory, "permission": "moderate", "description": "Criar diretorio PC"},
    "pc_search_files": {"fn": pc_search_files, "permission": "safe", "description": "Buscar arquivos PC"},
    "pc_copy_file": {"fn": pc_copy_file, "permission": "moderate", "description": "Copiar arquivo PC"},
    "pc_move_file": {"fn": pc_move_file, "permission": "moderate", "description": "Mover arquivo PC"},
    "pc_delete_file": {"fn": pc_delete_file, "permission": "high", "description": "Deletar arquivo PC"},
    "pc_run_command": {"fn": pc_run_command, "permission": "high", "description": "Executar comando PC"},
    "pc_processes": {"fn": pc_processes, "permission": "safe", "description": "Processos do PC"},
    "pc_services": {"fn": pc_services, "permission": "safe", "description": "Servicos do PC"},
    "pc_logs": {"fn": pc_logs, "permission": "safe", "description": "Logs do PC"},
    "pc_system_status": {"fn": pc_system_status, "permission": "safe", "description": "Status do PC"},
    "pc_shutdown": {"fn": pc_shutdown, "permission": "critical", "description": "Desligar PC"},
    "pc_restart": {"fn": pc_restart, "permission": "critical", "description": "Reiniciar PC"},
    "pc_lock": {"fn": pc_lock, "permission": "high", "description": "Bloquear PC"},
    "pc_sleep": {"fn": pc_sleep, "permission": "high", "description": "Suspender PC"},
}


def execute_pc_tool(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa uma tool do PC pelo nome."""
    tool = PC_TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": f"Unknown PC tool: {name}"}
    fn = tool["fn"]
    try:
        if name in ("pc_processes", "pc_services", "pc_system_status"):
            return fn()
        return fn(params)
    except Exception as e:
        return {"ok": False, "error": str(e)}

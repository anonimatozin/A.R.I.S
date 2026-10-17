"""Project Tools — ferramentas para trabalhar no projeto A.R.I.S.

read, write, edit, grep/search, glob/list, terminal, test, git status, git diff.
Disponiveis via AgentLoop para tarefas tipo "analise meu projeto".
"""

from __future__ import annotations

import glob
import os
import subprocess
import time
from typing import Any


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(cmd: str, timeout: int = 30, cwd: str | None = None) -> dict[str, Any]:
    import shlex as _shlex
    try:
        start = time.time()
        try:
            argv = _shlex.split(cmd, posix=True)
        except Exception:
            return {"ok": False, "error": "Parse error", "duration_ms": 0}
        if not argv:
            return {"ok": False, "error": "Empty command", "duration_ms": 0}
        for tok in argv[1:]:
            if tok in (";", "&&", "||", "|", "`", ">", "<", "$", "$("):
                return {"ok": False, "error": "Shell metacharacter not allowed", "duration_ms": 0}
            if "$(" in tok or "`" in tok:
                return {"ok": False, "error": "Shell expansion not allowed", "duration_ms": 0}
        if argv[0].lower() == "echo":
            return {"ok": True, "stdout": " ".join(argv[1:])[:5000], "stderr": "",
                    "duration_ms": int((time.time() - start) * 1000)}
        result = subprocess.run(
            argv, shell=False, capture_output=True, text=True,
            timeout=timeout, cwd=cwd or PROJECT_ROOT,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip()[:5000],
            "stderr": result.stderr.strip()[:2000],
            "duration_ms": int((time.time() - start) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def project_read(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Le arquivo do projeto."""
    params = params or {}
    path = params.get("path", "")
    if not path:
        return {"ok": False, "error": "path required"}
    try:
        full = os.path.join(PROJECT_ROOT, path) if not os.path.isabs(path) else path
        with open(full, encoding="utf-8", errors="replace") as f:
            content = f.read(100000)
        return {"ok": True, "content": content, "size": len(content), "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def project_write(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Escreve arquivo do projeto (MODERATE)."""
    params = params or {}
    path = params.get("path", "")
    content = params.get("content", "")
    if not path:
        return {"ok": False, "error": "path required"}
    try:
        full = os.path.join(PROJECT_ROOT, path) if not os.path.isabs(path) else path
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "size": len(content), "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def project_edit(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Edita arquivo do projeto — substitui old por new (MODERATE)."""
    params = params or {}
    path = params.get("path", "")
    old = params.get("old", "")
    new = params.get("new", "")
    if not path or not old:
        return {"ok": False, "error": "path and old required"}
    try:
        full = os.path.join(PROJECT_ROOT, path) if not os.path.isabs(path) else path
        with open(full, "r", encoding="utf-8") as f:
            content = f.read()
        if old not in content:
            return {"ok": False, "error": "old text not found"}
        content = content.replace(old, new, 1)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "replaced": True, "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def project_grep(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Busca padrao no codigo do projeto."""
    params = params or {}
    pattern = params.get("pattern", "")
    include = params.get("include", "*.py")
    if not pattern:
        return {"ok": False, "error": "pattern required"}
    cmd = f'rg -n --include="{include}" "{pattern}" . --max-count=30'
    result = _run(cmd, timeout=15)
    if not result["ok"] and "rg" in result.get("error", ""):
        cmd = f'grep -rn --include="{include}" "{pattern}" . | head -30'
        result = _run(cmd, timeout=15)
    return result


def project_glob(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lista arquivos por padrao no projeto."""
    params = params or {}
    pattern = params.get("pattern", "**/*.py")
    max_results = params.get("max_results", 50)
    try:
        matches = glob.glob(os.path.join(PROJECT_ROOT, pattern), recursive=True)[:max_results]
        files = []
        for m in matches:
            rel = os.path.relpath(m, PROJECT_ROOT)
            try:
                stat = os.stat(m)
                files.append({"path": rel, "size": stat.st_size, "is_dir": os.path.isdir(m)})
            except Exception:
                files.append({"path": rel})
        return {"ok": True, "files": files, "count": len(files)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def project_terminal(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa comando no diretorio do projeto (HIGH)."""
    params = params or {}
    cmd = params.get("command", "")
    if not cmd:
        return {"ok": False, "error": "command required"}
    timeout = min(int(params.get("timeout", 30)), 120)
    return _run(cmd, timeout=timeout)


def project_test(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Roda testes do projeto (HIGH)."""
    params = params or {}
    test_path = params.get("path", "")
    cmd = f"python -m pytest {test_path} -q --tb=short" if test_path else "python -m pytest -q --tb=short"
    return _run(cmd, timeout=120)


def project_git_status() -> dict[str, Any]:
    """Git status do projeto."""
    return _run("git status --short")


def project_git_diff() -> dict[str, Any]:
    """Git diff do projeto."""
    return _run("git diff")


PROJECT_TOOLS: dict[str, dict[str, Any]] = {
    "project_read": {"fn": project_read, "permission": "safe", "description": "Ler arquivo do projeto"},
    "project_write": {"fn": project_write, "permission": "moderate", "description": "Escrever arquivo do projeto"},
    "project_edit": {"fn": project_edit, "permission": "moderate", "description": "Editar arquivo do projeto"},
    "project_grep": {"fn": project_grep, "permission": "safe", "description": "Buscar no codigo"},
    "project_glob": {"fn": project_glob, "permission": "safe", "description": "Listar arquivos do projeto"},
    "project_terminal": {"fn": project_terminal, "permission": "high", "description": "Terminal do projeto"},
    "project_test": {"fn": project_test, "permission": "high", "description": "Rodar testes"},
    "project_git_status": {"fn": project_git_status, "permission": "safe", "description": "Git status"},
    "project_git_diff": {"fn": project_git_diff, "permission": "safe", "description": "Git diff"},
}


def execute_project_tool(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa uma project tool."""
    tool = PROJECT_TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": f"Unknown project tool: {name}"}
    fn = tool["fn"]
    try:
        if name in ("project_git_status", "project_git_diff"):
            return fn()
        return fn(params)
    except Exception as e:
        return {"ok": False, "error": str(e)}

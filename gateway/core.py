"""Core dispatch — routes requests to operations."""

from __future__ import annotations

import os
import subprocess
import threading
import time

from gateway.audit import log_operation
from gateway.auth import authenticate
from gateway.memory import MemoryDB


class CoreOps:
    def __init__(self, base_dir: str, db_path: str) -> None:
        self.base_dir = base_dir
        self.db = MemoryDB(db_path)

    def dispatch(self, request: dict) -> dict:
        if not authenticate(request):
            return {"ok": False, "error": "unauthorized"}

        cmd = request.get("type", "")
        t0 = time.time()

        try:
            result = self._handle(cmd, request)
        except Exception as e:
            result = {"ok": False, "error": str(e)}

        elapsed = (time.time() - t0) * 1000
        log_operation(cmd, target=str(request.get("path", request.get("command", "")))[:100],
                     result="ok" if result.get("ok") else "error",
                     detail=str(result.get("error", result.get("output", "")))[:200],
                     duration_ms=elapsed)
        return result

    def _handle(self, cmd: str, req: dict) -> dict:
        if cmd == "admin_ping":
            return {"ok": True, "node": "cll-1", "status": "online", "message": "CLL1 autenticado"}

        if cmd == "status":
            return self._status()

        if cmd == "get_file":
            return self._get_file(req)

        if cmd == "put_file":
            return self._put_file(req)

        if cmd == "mkdir":
            return self._mkdir(req)

        if cmd == "chmod_run":
            return self._chmod_run(req)

        if cmd == "exec_python":
            return self._exec_python(req)

        if cmd == "memory_add":
            return self.db.add_memory(req.get("content", ""), req.get("category", "general"), req.get("importance", 5))

        if cmd == "memory_get":
            return {"ok": True, "memories": self.db.get_memories(req.get("limit", 10))}

        if cmd == "memory_search":
            return {"ok": True, "memories": self.db.search_memories(req.get("query", ""))}

        if cmd == "memory_state":
            value = req.get("value")
            if value is not None:
                return self.db.set_state(req["key"], value)
            result = self.db.get_state(req.get("key", ""))
            return {"ok": True, **(result or {"value": None})}

        if cmd == "get_state":
            result = self.db.get_state(req.get("key", ""))
            return {"ok": True, **(result or {"value": None})}

        if cmd == "heartbeat":
            node_id = req.get("node_id", "unknown")
            return self.db.set_state(f"heartbeat:{node_id}", req.get("status", "online"))

        if cmd == "restart_gateway":
            def _restart():
                time.sleep(1)
                subprocess.run(["sv", "restart", "cll1-main"], capture_output=True, timeout=10)
            threading.Thread(target=_restart, daemon=True).start()
            return {"ok": True, "operation": "restart_gateway"}

        return {"ok": False, "error": "unknown_command"}

    def _status(self) -> dict:
        result = subprocess.run(
            ["sv", "status", "cll1-main"],
            capture_output=True, text=True, timeout=10,
        )
        return {
            "ok": True,
            "operation": "status",
            "output": result.stdout.strip() or result.stderr.strip(),
        }

    def _get_file(self, req: dict) -> dict:
        from gateway.filesystem import read_file
        path = req.get("path", "")
        content = read_file(self.base_dir, path)
        return {"ok": True, "operation": "get_file", "content": content}

    def _put_file(self, req: dict) -> dict:
        from gateway.filesystem import write_file
        path = req.get("path", "")
        content = req.get("content", "")
        size = write_file(self.base_dir, path, content)
        return {"ok": True, "operation": "put_file", "path": path, "size": size}

    def _mkdir(self, req: dict) -> dict:
        from gateway.filesystem import mkdir
        path = req.get("path", "")
        mkdir(self.base_dir, path)
        return {"ok": True, "operation": "mkdir", "path": path}

    def _chmod_run(self, req: dict) -> dict:
        from gateway.security import safe_path
        path = safe_path(req.get("path", ""), self.base_dir)
        os.chmod(path, 0o700)
        return {"ok": True, "operation": "chmod_run", "path": path}

    def _exec_python(self, req: dict) -> dict:
        from gateway.security import safe_path
        path = req.get("path", "")
        if not path.endswith(".py"):
            return {"ok": False, "error": "Only .py files allowed"}

        allowlist = [
            "aris_memory.py", "install_deps.py", "install_simple.py",
            "test_exec.py", "install_bg.py", "install_direct.py", "restart_gw.py",
            "test_net2.py", "gethome.py", "find_listener.py", "test_pc_access.py",
            "check_edge.py", "read_log.py", "test_edge_direct.py",
            "setup_persistent.py", "cleanup.py",
        ]
        if os.path.basename(path) not in allowlist:
            return {"ok": False, "error": "script_not_allowed"}

        full = safe_path(path, self.base_dir)
        result = subprocess.run(
            ["python", full],
            capture_output=True, text=True, timeout=60,
            cwd=self.base_dir,
        )
        return {
            "ok": True,
            "operation": "exec_python",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

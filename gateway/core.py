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
        # Timestamp de boot do processo — permite VERIFICAR restart remoto
        # (boot_time muda após reinício real; respostas "ok" sozinhas não provam nada)
        self.boot_time = time.time()
        try:
            with open(os.path.join(base_dir, "data", "gateway_boot.txt"), "w") as f:
                f.write(str(self.boot_time))
        except Exception:
            pass
        # Trilha de evidência de restarts: cada boot registra uma linha
        # (o thread de restart morre junto com o processo, então o "completed"
        # nunca seria escrito por ele — o boot seguinte fecha o ciclo).
        try:
            with open(os.path.join(base_dir, "data", "restart.log"), "a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} BOOT boot_time={self.boot_time} pid={os.getpid()}\n")
        except Exception:
            pass

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
            return {"ok": True, "node": "cll-1", "status": "online",
                    "message": "CLL1 autenticado", "boot_time": self.boot_time,
                    "pid": os.getpid()}

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

        if cmd == "get_personality":
            return self._get_personality()

        if cmd == "heartbeat":
            node_id = req.get("node_id", "unknown")
            return self.db.set_state(f"heartbeat:{node_id}", req.get("status", "online"))

        if cmd == "restart_gateway":
            # ATENÇÃO: esta resposta confirma apenas o AGENDAMENTO do restart,
            # não a execução. Verificação real: comparar `boot_time` via
            # `status`/`admin_ping` antes e depois.
            scheduled_at = time.time()
            base_dir = self.base_dir

            def _restart():
                time.sleep(1)
                import sys
                log_path = os.path.join(base_dir, "data", "restart.log")
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} RESTART-INITIATED scheduled_at={scheduled_at}\n")
                except Exception:
                    pass
                try:
                    if sys.platform == "win32":
                        # Windows: usa taskkill e reinicia via run_aris.bat
                        import subprocess
                        subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True, timeout=5)
                        subprocess.Popen(["cmd", "/c", "run_aris.bat"], cwd=base_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
                        outcome = "win32 restart requested"
                    else:
                        # Linux/Termux: usa sv (runit). Tenta PATH e caminho absoluto.
                        import shutil
                        import subprocess
                        sv_bin = shutil.which("sv") or "/data/data/com.termux/files/usr/bin/sv"
                        r = subprocess.run([sv_bin, "restart", "cll1-main"],
                                           capture_output=True, text=True, timeout=30)
                        outcome = (f"sv restart cll1-main rc={r.returncode} "
                                   f"stdout={r.stdout.strip()[:300]} stderr={r.stderr.strip()[:300]}")
                except Exception as e:
                    outcome = f"restart FAILED: {type(e).__name__}: {e}"
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} scheduled_at={scheduled_at} {outcome}\n")
                except Exception:
                    pass

            threading.Thread(target=_restart, daemon=True).start()
            return {"ok": True, "operation": "restart_gateway",
                    "scheduled": True, "verify_via": "boot_time",
                    "note": "restart agendado; confirme via status.boot_time"}

        if cmd == "scheduler_start":
            return self._sched_start()

        if cmd == "scheduler_stop":
            return self._sched_stop()

        if cmd == "scheduler_status":
            return self._sched_status()

        if cmd == "tailscale":
            return self._tailscale(req.get("action", "status"))

        return {"ok": False, "error": "unknown_command"}

    # ── ARIS Public Scheduler (processo independente) ──────
    # Sobe/derruba o public_scheduler sem mexer no sandbox do gateway:
    # usa pidfile + start_new_session (sobrevive ao restart do gateway
    # de propósito — é um serviço independente, não um thread).

    def _sched_paths(self) -> dict:
        d = os.path.join(self.base_dir, "public_scheduler", "data")
        return {
            "main": os.path.join(self.base_dir, "public_scheduler", "cll1_main.py"),
            "pid": os.path.join(d, "scheduler.pid"),
            "log": os.path.join(self.base_dir, "logs", "scheduler.log"),
        }

    def _sched_pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def _sched_kill_by_port(self) -> list:
        """Mata QUALQUER processo ouvindo 8780 (órfãos sem pidfile).

        Sem isso, um scheduler órfão segurava a porta: o novo morria com
        EADDRINUSE mas o check de porta dizia "ok" — mascarando a falha
        e servindo código velho. Aprendido da pior forma.
        """
        import signal as _sig
        killed = []
        try:
            with open("/proc/net/tcp") as f:
                rows = f.read().splitlines()[1:]
        except Exception:
            return killed
        inodes = set()
        for row in rows:
            parts = row.split()
            if len(parts) > 9 and parts[3] == "0A":  # LISTEN
                try:
                    if parts[1].rsplit(":", 1)[1].upper() == "1F90":  # 8780
                        inodes.add(parts[9])
                except Exception:
                    continue
        if not inodes:
            return killed
        try:
            pids = [p for p in os.listdir("/proc") if p.isdigit()]
        except Exception:
            return killed
        for pid in pids:
            try:
                fds = os.listdir(f"/proc/{pid}/fd")
            except Exception:
                continue
            for fd in fds:
                try:
                    link = os.readlink(f"/proc/{pid}/fd/{fd}")
                except Exception:
                    continue
                if link.startswith("socket:[") and link[8:-1] in inodes:
                    try:
                        os.kill(int(pid), _sig.SIGTERM)
                        killed.append(int(pid))
                    except Exception:
                        pass
                    break
        return killed

    def _sched_status(self) -> dict:
        import socket as _sock
        p = self._sched_paths()
        pid = None
        try:
            with open(p["pid"], encoding="utf-8") as f:
                pid = int(f.read().strip())
        except Exception:
            pass
        alive = bool(pid) and self._sched_pid_alive(pid)
        listening = False
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(2.0)
            listening = s.connect_ex(("127.0.0.1", 8780)) == 0
            s.close()
        except Exception:
            pass
        return {"ok": True, "operation": "scheduler_status",
                "pid": pid, "alive": alive, "listening_8780": listening}

    def _sched_stop(self) -> dict:
        import signal as _sig
        p = self._sched_paths()
        st = self._sched_status()
        pid = st.get("pid")
        if pid and st.get("alive"):
            try:
                os.kill(pid, _sig.SIGTERM)
            except Exception as e:
                return {"ok": False, "error": f"kill falhou: {e}"}
            for _ in range(20):
                time.sleep(0.5)
                if not self._sched_pid_alive(pid):
                    break
            if self._sched_pid_alive(pid):
                try:
                    os.kill(pid, _sig.SIGKILL)
                except Exception:
                    pass
        try:
            if os.path.exists(p["pid"]):
                os.remove(p["pid"])
        except Exception:
            pass
        orphans = self._sched_kill_by_port()
        return {"ok": True, "operation": "scheduler_stop", "stopped_pid": pid,
                "orphans_killed": orphans}

    def _sched_start(self) -> dict:
        import socket as _sock
        import subprocess as _sp
        import sys as _sys
        p = self._sched_paths()
        if not os.path.isfile(p["main"]):
            return {"ok": False, "error": "public_scheduler/cll1_main.py não encontrado"}
        self._sched_stop()  # derruba instância velha (evita EADDRINUSE)
        # Garante porta livre mesmo com órfãos (verificação real, não só pidfile)
        import socket as _sock2
        for _ in range(30):
            try:
                s = _sock2.socket(_sock2.AF_INET, _sock2.SOCK_STREAM)
                s.settimeout(1.0)
                busy = s.connect_ex(("127.0.0.1", 8780)) == 0
                s.close()
            except Exception:
                busy = False
            if not busy:
                break
            self._sched_kill_by_port()
            time.sleep(1.0)
        os.makedirs(os.path.dirname(p["log"]), exist_ok=True)
        os.makedirs(os.path.dirname(p["pid"]), exist_ok=True)
        try:
            logf = open(p["log"], "ab")
        except Exception as e:
            return {"ok": False, "error": f"log inacessível: {e}"}
        try:
            proc = _sp.Popen(
                [_sys.executable, p["main"]],
                cwd=self.base_dir,
                stdout=logf, stderr=_sp.STDOUT,
                stdin=_sp.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return {"ok": False, "error": f"spawn falhou: {e}"}
        try:
            with open(p["pid"], "w", encoding="utf-8") as f:
                f.write(str(proc.pid))
        except Exception:
            pass
        time.sleep(3)
        if proc.poll() is not None:
            tail = ""
            try:
                with open(p["log"], "rb") as f:
                    f.seek(max(0, os.path.getsize(p["log"]) - 2000))
                    tail = f.read().decode("utf-8", "replace")
            except Exception:
                pass
            # ATENÇÃO: mesmo morto, a porta pode responder (órfão antigo).
            # Nunca reportar sucesso com processo morto.
            return {"ok": False, "error": f"scheduler morreu na largada (rc={proc.poll()})",
                    "log_tail": tail[-800:]}
        listening = False
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(2.0)
            listening = s.connect_ex(("127.0.0.1", 8780)) == 0
            s.close()
        except Exception:
            pass
        return {"ok": True, "operation": "scheduler_start",
                "pid": proc.pid, "listening_8780": listening}

    # ── Tailscale (funnel direto do CLL1, sem PC no caminho) ──
    # Binários em ~/cll1/bin (instalados via API). tailscaled roda com
    # --tun=userspace-networking: funciona no Termux SEM root.

    def _ts_paths(self) -> dict:
        home = os.path.expanduser("~")
        d = os.path.join(self.base_dir, "data")
        return {
            "bin": os.path.join(self.base_dir, "bin", "tailscale"),
            "d": os.path.join(self.base_dir, "bin", "tailscaled"),
            "sock": os.path.join(d, "tailscaled.sock"),
            "state": os.path.join(d, "tailscaled.state"),
            "log": os.path.join(self.base_dir, "logs", "tailscaled.log"),
            "up_out": os.path.join(d, "tailscale_up.out"),
        }

    def _ts_run(self, *args: str, timeout: int = 20) -> dict:
        import subprocess as _sp
        p = self._ts_paths()
        if not os.path.isfile(p["bin"]):
            return {"ok": False, "error": "tailscale não instalado (~/cll1/bin)"}
        try:
            r = _sp.run([p["bin"], "--socket=" + p["sock"], *args],
                        capture_output=True, text=True, timeout=timeout)
            return {"ok": r.returncode == 0, "rc": r.returncode,
                    "stdout": r.stdout.strip()[:2000],
                    "stderr": r.stderr.strip()[:500]}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _ts_daemon_alive(self) -> int | None:
        import subprocess as _sp
        try:
            r = _sp.run(["pgrep", "-f", "tailscaled.*userspace-networking"],
                        capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return int(r.stdout.strip().split()[0])
        except Exception:
            pass
        # Fallback sem pgrep: varre /proc
        try:
            for pid in os.listdir("/proc"):
                if not pid.isdigit() or int(pid) == os.getpid():
                    continue
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
                    if "tailscaled" in cmd and "userspace-networking" in cmd:
                        return int(pid)
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _tailscale(self, action: str) -> dict:
        import subprocess as _sp
        p = self._ts_paths()
        if action == "status":
            out: dict = {"ok": True, "operation": "tailscale_status",
                         "installed": os.path.isfile(p["bin"]),
                         "daemon_pid": self._ts_daemon_alive()}
            st = self._ts_run("status", timeout=10)
            out["logged_in"] = st["ok"]
            out["status"] = (st.get("stdout") or st.get("stderr") or "")[:500]
            fn = self._ts_run("funnel", "status", timeout=10)
            out["funnel"] = (fn.get("stdout") or fn.get("stderr") or "")[:500]
            return out
        if action == "start":
            if self._ts_daemon_alive():
                return {"ok": True, "operation": "tailscale_start",
                        "already": True}
            if not os.path.isfile(p["d"]):
                return {"ok": False, "error": "tailscaled não instalado"}
            os.makedirs(os.path.dirname(p["log"]), exist_ok=True)
            try:
                logf = open(p["log"], "ab")
            except Exception as e:
                return {"ok": False, "error": f"log: {e}"}
            try:
                proc = _sp.Popen(
                    [p["d"], "--tun=userspace-networking",
                     "--state=" + p["state"], "--socket=" + p["sock"]],
                    stdout=logf, stderr=_sp.STDOUT, stdin=_sp.DEVNULL,
                    start_new_session=True)
            except Exception as e:
                return {"ok": False, "error": f"spawn: {e}"}
            time.sleep(3)
            if proc.poll() is not None:
                return {"ok": False, "error": f"tailscaled morreu (rc={proc.poll()})"}
            return {"ok": True, "operation": "tailscale_start", "pid": proc.pid}
        if action == "up":
            # Login interativo: roda em background, URL vai p/ tailscale_up.out.
            # O dono abre a URL no browser e aprova; depois funnel funciona.
            try:
                with open(p["up_out"], "w", encoding="utf-8") as f:
                    f.write("AGUARDANDO...\n")
            except Exception as e:
                return {"ok": False, "error": f"out: {e}"}
            try:
                logf = open(p["log"], "ab")
            except Exception as e:
                return {"ok": False, "error": f"log: {e}"}
            try:
                _sp.Popen(
                    [p["bin"], "--socket=" + p["sock"], "up",
                     "--hostname=cll1", "--accept-dns=false"],
                    stdout=open(p["up_out"], "w"), stderr=_sp.STDOUT,
                    stdin=_sp.DEVNULL, start_new_session=True)
            except Exception as e:
                return {"ok": False, "error": f"spawn: {e}"}
            return {"ok": True, "operation": "tailscale_up",
                    "note": "leia data/tailscale_up.out para a URL de login"}
        if action == "funnel":
            r1 = self._ts_run("funnel", "--bg", "--https=443", "8766", timeout=30)
            r2 = self._ts_run("funnel", "--bg", "--https=8443", "8780", timeout=30)
            fn = self._ts_run("funnel", "status", timeout=10)
            return {"ok": r1["ok"] and r2["ok"], "operation": "tailscale_funnel",
                    "dashboard_443": r1, "scheduler_8443": r2,
                    "funnel_status": (fn.get("stdout") or fn.get("stderr") or "")[:800]}
        if action == "funnel_off":
            r1 = self._ts_run("funnel", "--https=443", "off", timeout=20)
            r2 = self._ts_run("funnel", "--https=8443", "off", timeout=20)
            return {"ok": True, "operation": "tailscale_funnel_off",
                    "dashboard_443": r1, "scheduler_8443": r2}
        return {"ok": False, "error": f"tailscale action? {action}"}

    def _status(self) -> dict:
        import shutil
        sv_bin = shutil.which("sv") or "/data/data/com.termux/files/usr/bin/sv"
        try:
            result = subprocess.run(
                [sv_bin, "status", "cll1-main"],
                capture_output=True, text=True, timeout=10,
            )
            output = result.stdout.strip() or result.stderr.strip()
        except FileNotFoundError:
            output = "sv binary not found (runit indisponível?)"
        except Exception as e:
            output = f"sv status falhou: {e}"
        return {
            "ok": True,
            "operation": "status",
            "output": output,
            "boot_time": self.boot_time,
            "pid": os.getpid(),
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
            "setup_persistent.py", "cleanup.py", "install_ollama.py",
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

    def _get_personality(self) -> dict:
        """Retorna a personalidade sincronizada para o painel web."""
        from core.memcore.paths import default_memory_root
        personality_path = default_memory_root() / "personality_sync.md"
        try:
            if personality_path.exists():
                content = personality_path.read_text(encoding="utf-8")
                return {"ok": True, "personality": content}
        except Exception:
            pass
        # Fallback para personalidade padrão
        from config.personality import ARIS_PERSONALITY
        return {"ok": True, "personality": ARIS_PERSONALITY}

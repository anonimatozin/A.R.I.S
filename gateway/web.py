"""HTTP server for Web UI, Agent API, and Control Center."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import parse_qs, urlparse

from gateway.audit import log_operation

_chat_files: dict[str, str] = {}
_chat_history: list[dict] = []
_edge_chat_instance = None


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class GatewayHTTPHandler(BaseHTTPRequestHandler):
    _core_ops: Callable | None = None
    _base_dir: str = ""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def _check_auth(self) -> dict | None:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        else:
            token = ""
        if not token:
            return {"ok": False, "error": "Missing authorization"}
        from gateway.auth import get_token
        if token != get_token():
            return {"ok": False, "error": "Unauthorized"}
        return None

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _serve_dashboard(self) -> None:
        dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
        try:
            with open(dashboard_path, encoding="utf-8") as f:
                html = f.read()
        except FileNotFoundError:
            self._send_json({"error": "Dashboard not found"}, 404)
            return
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_chat(self, message: str, history: list[dict]) -> dict:
        """Processa mensagem de chat via Edge Chat (Groq API)."""
        global _edge_chat_instance, _chat_files, _chat_history

        fast = self._fast_path(message)
        if fast is not None:
            _chat_history.append({"role": "user", "content": message})
            _chat_history.append({"role": "assistant", "content": fast})
            if len(_chat_history) > 40:
                _chat_history[:] = _chat_history[-40:]
            return {"ok": True, "response": fast}

        # Try LLM via PC listener first
        llm_result = self._llm_via_pc(message, history)
        if llm_result is not None:
            _chat_history.append({"role": "user", "content": message})
            _chat_history.append({"role": "assistant", "content": llm_result})
            if len(_chat_history) > 40:
                _chat_history[:] = _chat_history[-40:]
            return {"ok": True, "response": llm_result}

        try:
            import sys
            sys.path.insert(0, self._base_dir)
            from edge.edge_chat import EdgeChat, EdgeConfig

            if _edge_chat_instance is None:
                config = EdgeConfig.from_env()
                _edge_chat_instance = EdgeChat(config)

            context_msg = message
            if _chat_files:
                has_file_question = any(
                    kw in message.lower()
                    for kw in ["arquivo", "conteudo", "texto", "leia", "le", "resumo", "fala", "diz", "analyse", "analise"]
                )
                if has_file_question or "arquivo" in message.lower():
                    file_ctx = "\n\n[O usuario enviou os seguintes arquivos. Analise o conteudo abaixo e responda sobre eles]:\n"
                    for fname, fcontent in _chat_files.items():
                        preview = fcontent[:2000] + ("..." if len(fcontent) > 2000 else "")
                        file_ctx += f"\n=== ARQUIVO: {fname} ===\n{preview}\n=== FIM ===\n"
                    context_msg = message + file_ctx

            origin = {"source": "web", "user": "admin"}
            response = _edge_chat_instance.respond(context_msg, origin_info=origin)

            _chat_history.append({"role": "user", "content": message})
            _chat_history.append({"role": "assistant", "content": response})
            if len(_chat_history) > 40:
                _chat_history[:] = _chat_history[-40:]

            log_operation("chat", target=message[:100],
                         result="ok", detail=response[:200])

            return {"ok": True, "response": response}
        except Exception as e:
            return {"ok": False, "error": f"Chat error: {e}"}

    def _fast_path(self, message: str) -> str | None:
        """Comandos rapidos que nao precisam de IA."""
        import re
        msg = message.lower().strip()

        if msg in ("status", "status do pc", "pc status", "pc ta ligado", "pc ligado", "pc online"):
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                result = sock.connect_ex(("192.168.0.109", 8770))
                sock.close()
                if result == 0:
                    return "O PC esta **online**. Posso executar comandos nele."
                else:
                    return "O PC esta **offline**. Posso operar no modo edge com funcoes basicas."
            except Exception:
                return "Nao consegui verificar o PC."

        if msg in ("hora", "que horas sao", "horas", "relogio"):
            from datetime import datetime
            now = datetime.now()
            return f"Sao **{now.strftime('%H:%M')}**."

        if msg in ("data", "que dia e hoje", "hoje"):
            from datetime import datetime
            now = datetime.now()
            return f"Hoje e **{now.strftime('%d/%m/%Y')}** ({now.strftime('%A')})."

        if msg in ("limpar historico", "limpa historico", "esqueca", "esqueca tudo"):
            _chat_history.clear()
            _chat_files.clear()
            return "Historico limpo. Pode comecar de novo."

        if msg in ("ajuda", "help", "comandos", "o que voce faz"):
            return (
                "Posso ajudar com:\n"
                "- **Status do PC** — verificar se esta ligado\n"
                "- **Horario/data** — que horas sao\n"
                "- **Upload de arquivos** — envie um arquivo e eu leio\n"
                "- **Perguntas** — qualquer duvida\n"
                "- **Comandos** — desligar, ligar, abrir apps (quando PC ligado)\n"
                "- **Limpar historico** — reseta a conversa"
            )

        if msg in ("obrigado", "obrigada", "valeu", "thanks"):
            return "De nada! Se precisar de algo mais, e so pedir."

        if msg in ("oi", "ola", "bom dia", "boa tarde", "boa noite", "eai", "fala"):
            from datetime import datetime
            hour = datetime.now().hour
            if hour < 12:
                salve = "Bom dia"
            elif hour < 18:
                salve = "Boa tarde"
            else:
                salve = "Boa noite"
            return f"{salve}! Como posso ajudar?"

        if re.match(r"^(?:aris\s+)?(?:ta\s+)?(?:consegu(?:e|indo)|pode|sabe|esta)\s+.+", msg):
            return "Sim, to aqui e funcionando! Pode pedir o que precisar."

        if re.match(r"^(?:aris\s+)?(?:obrigad[oa]|valeu|thanks|vlw)", msg):
            return "De nada! Sempre que precisar."

        # Comandos de PC — fast path, sem LLM
        pc_commands = {
            ("desligar", "desliga", "shutdown", "desligar pc"): "Confirmar desligamento? Responda 'sim' pra confirmar.",
            ("reiniciar", "reinicia", "restart", "reboot"): "Confirmar reinicio? Responda 'sim' pra confirmar.",
            ("travar", "trava", "lock", "bloquear"): "Confirmar travamento? Responda 'sim' pra confirmar.",
        }
        for aliases, msg_response in pc_commands.items():
            if msg in aliases:
                return msg_response

        return None

    _pc_online_cache = {"result": None, "time": 0}

    def _llm_via_pc(self, message: str, history: list[dict]) -> str | None:
        """Chama LLM via PC listener — resolve bloqueio de IP no Groq."""
        import json as _json
        import os
        import socket
        import time
        import urllib.request

        pc_host = os.getenv("PC_HOST", "192.168.0.109")
        pc_port = int(os.getenv("PC_LISTENER_PORT", "8770"))
        api_key = os.getenv("EDGE_GROQ_API_KEY", "")
        model = os.getenv("EDGE_MODEL", "openai/gpt-oss-120b")

        if not api_key:
            return None

        # Quick PC check com cache (5s)
        now = time.time()
        if self._pc_online_cache["result"] is not None and now - self._pc_online_cache["time"] < 5:
            pc_online = self._pc_online_cache["result"]
        else:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.5)
                pc_online = s.connect_ex((pc_host, pc_port)) == 0
                s.close()
            except Exception:
                pc_online = False
            self._pc_online_cache["result"] = pc_online
            self._pc_online_cache["time"] = now

        if not pc_online:
            return None

        # Build messages
        prompt = "Voce e a A.R.I.S., uma assistente virtual brasileira. Responda sempre em portugues, de forma natural e informal."
        messages = [{"role": "system", "content": prompt}]
        for h in history[-10:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": message})

        try:
            payload = _json.dumps({
                "messages": messages,
                "model": model,
                "api_key": api_key,
            }).encode("utf-8")

            req = urllib.request.Request(
                f"http://{pc_host}:{pc_port}/api/llm",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                body = _json.loads(resp.read().decode("utf-8"))
                if body.get("ok"):
                    return body.get("response", "")
                return None

        except Exception:
            return None

    def _handle_upload(self) -> dict:
        """Processa upload de arquivo multipart."""
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return {"ok": False, "error": "Expected multipart/form-data"}

        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:]
                break

        if not boundary:
            return {"ok": False, "error": "No boundary"}

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        parts = body.split(("--" + boundary).encode())

        results = []
        for part in parts:
            if not part or part.strip() == b"" or part.strip() == b"--":
                continue

            if b"\r\n\r\n" not in part:
                continue

            header_section, file_data = part.split(b"\r\n\r\n", 1)
            header_text = header_section.decode("utf-8", errors="replace")

            filename = None
            field_name = None
            for line in header_text.split("\r\n"):
                if "Content-Disposition:" in line:
                    if 'filename="' in line:
                        fn_start = line.index('filename="') + 10
                        fn_end = line.index('"', fn_start)
                        filename = line[fn_start:fn_end]
                    if 'name="' in line:
                        name_start = line.index('name="') + 6
                        name_end = line.index('"', name_start)
                        field_name = line[name_start:name_end]

            if filename and file_data:
                global _chat_files
                upload_dir = os.path.join(self._base_dir, "uploads")
                os.makedirs(upload_dir, exist_ok=True)

                safe_name = os.path.basename(filename)
                filepath = os.path.join(upload_dir, safe_name)

                counter = 1
                while os.path.exists(filepath):
                    name, ext = os.path.splitext(safe_name)
                    filepath = os.path.join(upload_dir, f"{name}_{counter}{ext}")
                    counter += 1

                with open(filepath, "wb") as f:
                    f.write(file_data)

                is_text = False
                content_str = ""
                try:
                    content_str = file_data.decode("utf-8")
                    is_text = True
                except UnicodeDecodeError:
                    try:
                        content_str = file_data.decode("latin-1")
                        is_text = True
                    except Exception:
                        pass

                if is_text and content_str:
                    _chat_files[filename] = content_str

                result = {
                    "ok": True,
                    "filename": os.path.basename(filepath),
                    "path": filepath,
                    "size": len(file_data),
                    "is_text": is_text,
                }

                results.append(result)

                log_operation("upload", target=filename,
                             result="ok", detail=f"{len(file_data)} bytes")

        if not results:
            return {"ok": False, "error": "No files found in upload"}

        if len(results) == 1:
            return results[0]

        return {"ok": True, "files": results, "count": len(results)}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "" or path == "/":
            self._serve_dashboard()
            return

        if path == "/api/ping":
            self._send_json({"ok": True, "node": "cll-1", "status": "online"})
            return

        if path == "/api/status":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            from gateway.services import sv_status
            result = sv_status()
            self._send_json(result)
            return

        if path == "/api/audit":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            from gateway.audit import get_recent
            self._send_json({"ok": True, "entries": get_recent(100)})
            return

        if path == "/api/files":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            qs = parse_qs(parsed.query)
            rel = qs.get("path", ["."])[0]
            from gateway.filesystem import list_files
            try:
                files = list_files(self._base_dir, rel)
                self._send_json({"ok": True, "path": rel, "files": files})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/logs":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            qs = parse_qs(parsed.query)
            log_file = qs.get("file", ["cll1.log"])[0]
            lines = int(qs.get("lines", ["50"])[0])
            from gateway.services import read_log
            log_dir = os.path.join(self._base_dir, "logs")
            result = read_log(os.path.join(log_dir, log_file), lines)
            self._send_json(result)
            return

        if path == "/api/agents":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            from gateway.agent import list_agents
            agents = list_agents(self._base_dir)
            self._send_json({"ok": True, "agents": agents})
            return

        if path == "/api/metrics":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            from gateway.monitor import get_metrics
            metrics = get_metrics()
            try:
                from core.neural.mode import get_mode_manager
                mm = get_mode_manager()
                try:
                    from cll1.router import Router
                    import socket
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3.0)
                    pc_host = getattr(mm, '_pc_host', '192.168.0.109')
                    result = sock.connect_ex((pc_host, 8770))
                    sock.close()
                    pc_online = result == 0
                    mm.update_heartbeat(pc_online, reason="web_metrics")
                except Exception:
                    pc_online = mm.pc_online
                metrics["mode"] = mm.mode.value
                metrics["pc_online"] = pc_online
                metrics["last_heartbeat"] = mm.last_heartbeat
            except Exception:
                metrics["mode"] = "unknown"
                metrics["pc_online"] = False
                metrics["last_heartbeat"] = 0
            try:
                from core.tools.wol import get_wol
                wol = get_wol()
                metrics["wol"] = wol.status()
            except Exception:
                metrics["wol"] = {"configured": False}
            try:
                from core.neural.capabilities import get_capability_registry
                from core.neural.mode import get_mode_manager as mm_fn
                cr = get_capability_registry()
                mm2 = mm_fn()
                caps = cr.available_in_mode(mm2.mode)
                metrics["capabilities"] = {c.name: c.to_dict() for c in caps}
            except Exception:
                metrics["capabilities"] = {}
            try:
                from core.tools.executor import get_tool_executor
                executor = get_tool_executor()
                metrics["recent_tool_calls"] = executor.get_recent_calls(20)
            except Exception:
                metrics["recent_tool_calls"] = []
            self._send_json({"ok": True, "metrics": metrics})
            return

        if path == "/api/backups":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            from gateway.backup import list_backups
            backups = list_backups(self._base_dir)
            self._send_json({"ok": True, "backups": backups})
            return

        if path == "/api/health":
            from gateway.health import run_health_checks
            result = run_health_checks(self._base_dir)
            self._send_json(result)
            return

        if path == "/api/capabilities":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                import socket
                pc_online = False
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2.0)
                    pc_online = sock.connect_ex(("192.168.0.109", 8770)) == 0
                    sock.close()
                except Exception:
                    pass

                caps = {
                    "pc": {
                        "online": pc_online,
                        "always": [
                            {"name": "Chat / Conversa", "desc": "Conversar sobre qualquer assunto"},
                            {"name": "Memoria", "desc": "Lembrar de informacoes importantes"},
                            {"name": "Pesquisa Web", "desc": "Buscar informacoes na internet"},
                            {"name": "Traducao", "desc": "Traduzir entre idiomas"},
                            {"name": "Resumo de Texto", "desc": "Resumir textos longos"},
                            {"name": "Calculo", "desc": "Resolver contas e expressoes"},
                            {"name": "Previsao do Tempo", "desc": "Ver tempo em qualquer cidade"},
                            {"name": "Ler Arquivos", "desc": "Ler conteudo de arquivos enviados"},
                            {"name": "NLU (Local)", "desc": "Entender comandos sem IA"},
                        ],
                        "pc_on": [
                            {"name": "Abrir/Fechar Apps", "desc": "Controlar programas do PC"},
                            {"name": "Navegador", "desc": "Abrir sites e pesquisar"},
                            {"name": "Desligar/Reiniciar PC", "desc": "Controlar energia do PC"},
                            {"name": "WoL (Ligar PC)", "desc": "Ligar o PC remotamente"},
                            {"name": "Files (PC)", "desc": "Listar, ler, criar, deletar arquivos"},
                            {"name": "Shell/Exec", "desc": "Executar comandos no terminal"},
                            {"name": "Screenshots", "desc": "Capturar tela do PC"},
                            {"name": "OCR", "desc": "Ler texto de imagens"},
                            {"name": "Agendar Tarefas", "desc": "Programar acoes futuras"},
                            {"name": "Multi-Intent Planner", "desc": "Executar multiplas acoes de uma vez"},
                        ],
                        "pc_off": [
                            {"name": "Ligar PC (WoL)", "desc": "Ligacao remota via rede"},
                            {"name": "Ver Status", "desc": "Verificar se PC esta online"},
                        ]
                    }
                }
                self._send_json({"ok": True, **caps})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/exec":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            command = body.get("command", "")
            timeout = min(int(body.get("timeout", 30)), 120)
            from gateway.terminal import run_command
            result = run_command(command, timeout=timeout, cwd=self._base_dir)
            log_operation("exec", target=command, result="ok" if result["ok"] else "error",
                         detail=result.get("stdout", result.get("error", ""))[:200],
                         duration_ms=result.get("duration_ms", 0))
            self._send_json(result)
            return

        if path == "/api/file":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            action = body.get("action", "")
            rel = body.get("path", "")

            if action == "read":
                from gateway.filesystem import read_file
                try:
                    content = read_file(self._base_dir, rel)
                    self._send_json({"ok": True, "content": content})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
                return

            if action == "write":
                from gateway.filesystem import write_file
                try:
                    size = write_file(self._base_dir, rel, body.get("content", ""))
                    self._send_json({"ok": True, "size": size})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
                return

            if action == "delete":
                from gateway.filesystem import delete_file
                try:
                    ok = delete_file(self._base_dir, rel)
                    self._send_json({"ok": ok})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
                return

            if action == "move":
                dst = body.get("destination", "")
                from gateway.filesystem import move_file
                try:
                    ok = move_file(self._base_dir, rel, dst)
                    self._send_json({"ok": ok})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
                return

            if action == "copy":
                dst = body.get("destination", "")
                from gateway.filesystem import copy_file
                try:
                    ok = copy_file(self._base_dir, rel, dst)
                    self._send_json({"ok": ok})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
                return

            if action == "mkdir":
                from gateway.filesystem import mkdir
                try:
                    mkdir(self._base_dir, rel)
                    self._send_json({"ok": True})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
                return

            if action == "info":
                from gateway.filesystem import file_info
                try:
                    info = file_info(self._base_dir, rel)
                    self._send_json({"ok": True, **info})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
                return

            self._send_json({"ok": False, "error": f"Unknown action: {action}"}, 400)
            return

        if path == "/api/service":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            action = body.get("action", "status")
            svc = body.get("service", "cll1-main")
            from gateway.services import sv_enable, sv_restart, sv_status, sv_stop
            if action == "status":
                result = sv_status(svc)
            elif action == "restart":
                result = sv_restart(svc)
            elif action == "stop":
                result = sv_stop(svc)
            elif action == "enable":
                result = sv_enable(svc)
            else:
                result = {"ok": False, "error": f"Unknown action: {action}"}
            self._send_json(result)
            return

        if path == "/api/agent/chat":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            message = body.get("message", "")
            agent_id = body.get("agent_id")
            from gateway.agent import route_message
            result = route_message(message, agent_id, self._base_dir)
            log_operation("agent_chat", target=message[:100],
                         result="ok" if result.get("ok") else "error",
                         detail=str(result)[:200])
            self._send_json(result)
            return

        if path == "/api/agent/create":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            name = body.get("name", "Agent")
            agent_type = body.get("type", "local")
            from gateway.agent import create_agent
            agent = create_agent(name, agent_type, self._base_dir, **{k: v for k, v in body.items() if k not in ("name", "type")})
            self._send_json({"ok": True, "agent": agent})
            return

        if path == "/api/backup":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            action = body.get("action", "create")
            from gateway.backup import create_backup, delete_backup, restore_backup
            if action == "create":
                name = body.get("name", "")
                result = create_backup(self._base_dir, name)
            elif action == "restore":
                name = body.get("name", "")
                result = restore_backup(self._base_dir, name)
            elif action == "delete":
                name = body.get("name", "")
                result = delete_backup(self._base_dir, name)
            else:
                result = {"ok": False, "error": f"Unknown action: {action}"}
            log_operation("backup", target=action,
                         result="ok" if result.get("ok") else "error")
            self._send_json(result)
            return

        if path == "/api/chat":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            message = body.get("message", "")
            history = body.get("history", [])
            if not message:
                self._send_json({"ok": False, "error": "No message"}, 400)
                return
            try:
                result = self._handle_chat(message, history)
                self._send_json(result)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/upload":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                result = self._handle_upload()
                self._send_json(result)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/feedback":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            response_text = body.get("response", "")
            rating = body.get("rating", "none")
            try:
                import json as _json
                feedback_path = os.path.join(self._base_dir, "data", "feedback.jsonl")
                os.makedirs(os.path.dirname(feedback_path), exist_ok=True)
                with open(feedback_path, "a", encoding="utf-8") as f:
                    f.write(_json.dumps({
                        "ts": __import__("time").time(),
                        "response": response_text[:500],
                        "rating": rating
                    }) + "\n")
                if rating in ("like", "dislike"):
                    try:
                        sys.path.insert(0, self._base_dir)
                        from core.personality import get_personality
                        p = get_personality()
                        p.record_interaction("", response_text, feedback=rating)
                    except Exception:
                        pass
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/personality":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from core.personality import get_personality
                p = get_personality()
                self._send_json({"ok": True, "personality": p.get_state().to_dict()})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/personality/feedback":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            feedback = body.get("feedback", "")
            try:
                from core.personality import get_personality
                p = get_personality()
                p.record_interaction("", "", feedback=feedback)
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # Knowledge Graph API
        if path == "/api/kg/search":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            query = body.get("query", "")
            try:
                from core.knowledge_graph import get_knowledge_graph
                kg = get_knowledge_graph()
                results = kg.search(query, limit=10)
                self._send_json({"ok": True, "results": results})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/kg/store":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            content = body.get("content", "")
            node_type = body.get("type", "memory")
            tags = body.get("tags", [])
            try:
                from core.knowledge_graph import get_knowledge_graph
                kg = get_knowledge_graph()
                node_id = kg.store(content, node_type, tags=tags)
                self._send_json({"ok": True, "id": node_id})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/kg/stats":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from core.knowledge_graph import get_knowledge_graph
                kg = get_knowledge_graph()
                stats = kg.get_stats()
                self._send_json({"ok": True, "stats": stats})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # UI Skills API
        if path == "/api/ui-skills":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from core.ui_skills import get_ui_skills
                ui = get_ui_skills()
                skills = ui.get_all_skills()
                self._send_json({"ok": True, "skills": list(skills.keys())})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/ui-skills/review":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            code = body.get("code", "")
            skill = body.get("skill", "baseline-ui")
            try:
                from core.ui_skills import get_ui_skills
                ui = get_ui_skills()
                violations = ui.review_code(code, skill)
                self._send_json({"ok": True, "review": violations})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # Browser status
        if path == "/api/browser":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                pc_ip = self._get_pc_ip()
                if not pc_ip:
                    self._send_json({"ok": False, "error": "PC offline"})
                    return
                import urllib.request
                req = urllib.request.Request(f"http://{pc_ip}:8770/api/browser")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    self._send_json(data)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        self._send_json({"error": "Not found"}, 404)


def start_http_server(
    base_dir: str,
    host: str = "0.0.0.0",
    port: int = 8766,
) -> ThreadedHTTPServer:
    handler = type("Handler", (GatewayHTTPHandler,), {
        "_base_dir": base_dir,
    })
    server = ThreadedHTTPServer((host, port), handler)
    return server

"""HTTP server for Web UI, Agent API, and Control Center."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import parse_qs, urlparse
import hashlib
import base64
import struct

from gateway.audit import log_operation
from gateway.events import get_event_bus

_chat_files: dict[str, str] = {}
_chat_history: list[dict] = []
_edge_chat_instance = None

# ── Segurança ────────────────────────────────────────────────
# Arquivos que NUNCA podem ser lidos/alterados via /api/file por
# roles não-admin (contêm segredos: tokens, chaves de API, hashes).
_SENSITIVE_BASENAMES = frozenset({
    ".env", ".env.cll1", ".env.cll1.test", ".env.example",
    "secrets.enc", "users.json", "secrets.json", "credentials.json",
    "id_rsa", "id_ed25519",
})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3")


def _is_sensitive_path(rel: str) -> bool:
    base = os.path.basename(rel.strip().replace("\\", "/"))
    if base in _SENSITIVE_BASENAMES:
        return True
    return base.endswith(_SENSITIVE_SUFFIXES)


# Rate-limit de login por IP: 8 falhas em 5 min → bloqueio de 60s (429).
# Sem isso, brute-force contra /api/login público é irrestrito.
_LOGIN_FAILS: dict[str, list[float]] = {}
_LOGIN_WINDOW_S = 300.0
_LOGIN_MAX_FAILS = 8
_LOGIN_BLOCK_S = 60.0


def _login_check(ip: str) -> tuple[bool, int]:
    """Retorna (permitido, segundos_para_desbloqueio)."""
    import time as _t
    now = _t.time()
    arr = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_WINDOW_S]
    _LOGIN_FAILS[ip] = arr
    if len(arr) >= _LOGIN_MAX_FAILS:
        retry = int(_LOGIN_BLOCK_S - (now - arr[-1]))
        if retry > 0:
            return False, retry
    return True, 0


def _login_record_fail(ip: str) -> None:
    import time as _t
    _LOGIN_FAILS.setdefault(ip, []).append(_t.time())


def _login_clear(ip: str) -> None:
    _LOGIN_FAILS.pop(ip, None)


def _real_ip(handler) -> str:
    """IP real do cliente. Headers de proxy só valem se vier de proxy local confiável.

    Antes confiava em CF-Connecting-IP/X-Forwarded-For de qualquer origem,
    permitindo zerar o rate-limit de login girando o header.
    """
    try:
        direct = handler.client_address[0]
    except Exception:
        direct = "unknown"
    trusted = direct in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
    if trusted:
        cf = (handler.headers.get("CF-Connecting-IP", "") or "").strip()
        if cf:
            return cf.split(",")[0].strip()[:64]
        xff = (handler.headers.get("X-Forwarded-For", "") or "").strip()
        if xff:
            return xff.split(",")[0].strip()[:64]
    return direct


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        import traceback
        print(f"Error handling request from {client_address}:")
        traceback.print_exc()
        try:
            self.RequestHandlerClass(request, client_address, self)._send_json(
                {"ok": False, "error": "Internal server error"}, 500
            )
        except Exception:
            pass

class GatewayHTTPHandler(BaseHTTPRequestHandler):
    _core_ops: Callable | None = None
    _base_dir: str = ""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _cors_origin(self) -> str | None:
        """Retorna Origin permitido ou None (same-origin não precisa de CORS)."""
        origin = (self.headers.get("Origin", "") or "").strip()
        if not origin:
            return None
        allowed = [o.strip() for o in os.getenv(
            "ARIS_ALLOWED_ORIGINS",
            "http://192.168.0.106:8766,http://127.0.0.1:8766").split(",") if o.strip()]
        if origin in allowed:
            return origin
        return None

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        cors = self._cors_origin()
        if cors:
            self.send_header("Access-Control-Allow-Origin", cors)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except Exception:
            return {}
        if length <= 0:
            return {}
        if length > 1_000_000:  # 1MB — evita DoS via JSON gigante
            return {}
        try:
            body = self.rfile.read(length)
            return json.loads(body.decode("utf-8"))
        except Exception:
            return {}

    def _check_auth(self) -> dict | None:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        else:
            token = ""
        if not token:
            return {"ok": False, "error": "Missing authorization"}
        from gateway.auth import authenticate
        if not authenticate({"token": token}):
            return {"ok": False, "error": "Unauthorized"}
        return None

    def _get_token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return ""

    # ── Scheduler público (site :8780, mesmo aparelho) ──────
    def _sched_read(self, filename: str, sort_key: str) -> dict:
        """Lê JSON do scheduler direto do disco (sem depender dele estar no ar)."""
        import time as _t
        try:
            with open(os.path.join(self._base_dir, "public_scheduler", "data", filename),
                      encoding="utf-8") as f:
                items = json.load(f)
            if not isinstance(items, list):
                items = []
        except FileNotFoundError:
            items = []
        except Exception as e:
            return {"ok": False, "error": f"leitura falhou: {e}"}
        try:
            items.sort(key=lambda x: x.get(sort_key, ""))
        except Exception:
            pass
        counts = {"tentative": 0, "confirmed": 0, "cancelled": 0}
        for it in items:
            st = it.get("status")
            if st in counts:
                counts[st] += 1
        return {"ok": True, "items": items, "counts": counts,
                "total": len(items), "read_at": _t.time()}

    def _sched_proxy(self, sched_path: str, body: dict) -> dict:
        """Repasse autenticado para o scheduler local (:8780).

        Mutação passa pela lógica do scheduler (push WS + DM + regras),
        em vez de editar o JSON por fora.
        """
        import urllib.request as _url
        import urllib.error as _urlerr
        try:
            _headers = {"Content-Type": "application/json"}
            _tok = os.getenv("SCHEDULER_CONFIRM_TOKEN", "")
            if _tok:
                _headers["X-Scheduler-Token"] = _tok
            req = _url.Request(
                "http://127.0.0.1:8780" + sched_path,
                data=json.dumps(body).encode("utf-8"),
                headers=_headers,
                method="POST")
            with _url.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except _urlerr.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8") or "{}")
            except Exception:
                return {"ok": False, "success": False, "error": f"scheduler HTTP {e.code}"}
        except Exception:
            return {"ok": False, "success": False,
                    "error": "Scheduler offline (porta 8780 fechada?) "}

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        cors = self._cors_origin()
        if cors:
            self.send_header("Access-Control-Allow-Origin", cors)
            self.send_header("Vary", "Origin")
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
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        # Security headers (defesa em profundidade; Cloudflare soma os dele)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "connect-src 'self' wss: ws:; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(body)

    # ── WebSocket Support ──────────────────────────────────────
    def _handle_websocket_upgrade(self) -> bool:
        """Handle WebSocket upgrade request. Returns True if upgraded."""
        upgrade = self.headers.get("Upgrade", "").lower()
        connection = self.headers.get("Connection", "").lower()
        if upgrade != "websocket" or "upgrade" not in connection:
            return False

        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            self._send_json({"error": "Sec-WebSocket-Key required"}, 400)
            return True

        # Compute accept key
        accept_key = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()

        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept_key)
        self.end_headers()

        # Get event bus and start streaming
        event_bus = get_event_bus()
        if event_bus is None:
            self._ws_send_close(1011, "Event bus not available")
            return True

        self._ws_stream_events(event_bus)
        return True

    def _ws_stream_events(self, event_bus) -> None:
        """Stream events from EventBus over WebSocket."""
        import json
        import select
        import time

        # Subscribe to all events
        queue: list = []
        def handler(event):
            queue.append(event.to_dict())

        event_bus.subscribe("*", handler)

        try:
            self.connection.settimeout(0.5)
            last_ping = time.time()
            while True:
                # Check for client disconnect
                ready = select.select([self.connection], [], [], 0.5)
                if ready[0]:
                    data = self.connection.recv(1024)
                    if not data:
                        break
                    # Handle incoming frames (ping/pong, close)
                    if data[0] & 0x8F == 0x88:  # Close frame
                        break
                    elif data[0] & 0x8F == 0x89:  # Ping
                        self._ws_send_pong(data)
                    continue

                # Send queued events
                while queue:
                    event_data = queue.pop(0)
                    self._ws_send_text(json.dumps(event_data))

                # Send ping every 30 seconds
                if time.time() - last_ping > 30:
                    self._ws_send_ping()
                    last_ping = time.time()

        except (ConnectionError, BrokenPipeError, OSError, TimeoutError):
            pass
        except Exception:
            pass
        finally:
            event_bus.unsubscribe("*", handler)
            try:
                self._ws_send_close(1000, "Normal closure")
            except Exception:
                pass

    def _ws_send_frame(self, opcode: int, payload: bytes = b"") -> None:
        """Send a WebSocket frame."""
        frame = bytearray()
        frame.append(0x80 | opcode)  # FIN + opcode
        length = len(payload)
        if length < 126:
            frame.append(length)
        elif length < 65536:
            frame.append(126)
            frame.extend(struct.pack(">H", length))
        else:
            frame.append(127)
            frame.extend(struct.pack(">Q", length))
        frame.extend(payload)
        self.connection.sendall(frame)

    def _ws_send_text(self, text: str) -> None:
        self._ws_send_frame(0x1, text.encode("utf-8"))

    def _ws_send_ping(self) -> None:
        self._ws_send_frame(0x9, b"ping")

    def _ws_send_pong(self, ping_frame: bytes) -> None:
        # Echo ping payload as pong
        payload = ping_frame[2:] if len(ping_frame) > 2 else b""
        self._ws_send_frame(0xA, payload)

    def _ws_send_close(self, code: int, reason: str = "") -> None:
        payload = struct.pack(">H", code) + reason.encode("utf-8")
        self._ws_send_frame(0x8, payload)

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
                from core.neural.mode import get_mode_manager
                mm = get_mode_manager()
                if mm.pc_online:
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

        # Quick PC check com cache (5s) - use ModeManager as source of truth
        try:
            from core.neural.mode import get_mode_manager
            mm = get_mode_manager()
            pc_online = mm.pc_online
        except Exception:
            # Fallback to local check
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

        # Build messages with canonical personality
        try:
            from core.personality import get_personality
            personality = get_personality()
            situation = personality.detect_situation(message)
            system_prompt = personality.generate_prompt(situation)
        except Exception:
            system_prompt = "Voce e a A.R.I.S., uma assistente virtual brasileira. Responda sempre em portugues, de forma natural e informal."

        messages = [{"role": "system", "content": system_prompt}]
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

        # WebSocket endpoint for real-time events — exige auth sempre
        if path == "/api/ws/events":
            qs = parse_qs(parsed.query)
            token = qs.get("token", [""])[0]
            if not token:
                auth_h = self.headers.get("Authorization", "")
                if auth_h.startswith("Bearer "):
                    token = auth_h[7:]
            from gateway.auth import authenticate as _auth_ws
            if not token or not _auth_ws({"token": token}):
                self._send_json({"error": "Unauthorized"}, 401)
                return
            if self._handle_websocket_upgrade():
                return
            return

        if path == "/api/ping":
            # boot_time permite verificar restart real (muda após reinício)
            boot_time = None
            try:
                with open(os.path.join(self._base_dir, "data", "gateway_boot.txt"), encoding="utf-8") as f:
                    boot_time = float(f.read().strip())
            except Exception:
                pass
            self._send_json({"ok": True, "node": "cll-1", "status": "online", "boot_time": boot_time})
            return

        if path == "/api/versao":
            from core.version import get_version_info
            self._send_json({"ok": True, **get_version_info()})
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

        if path == "/api/approvals":
            # Fila de aprovação centralizada (extras20 #15): pendências CRITICAL +
            # agendamentos tentativos num lugar só.
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from modules.extras20 import approval_queue
                q = approval_queue()
                self._send_json({"ok": True, **q})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/privacy":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from modules.extras20 import privacy_is_on
                self._send_json({"ok": True, "privacy_mode": privacy_is_on()})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/session":
            # Retorna o usuário da sessão atual (usado no boot p/ validar token)
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            try:
                from gateway.auth import get_session, get_user_role, get_username
                import json as _json
                sess = get_session(token)
                if not sess:
                    self._send_json({"ok": False, "error": "Sessão inválida"}, 401)
                    return
                username = get_username(token) or sess.get("username", "")
                role = get_user_role(token) or sess.get("role", "")
                # Buscar expires_at do users.json
                expires_at = None
                try:
                    users_path = os.path.join(self._base_dir, "data", "users.json")
                    with open(users_path, encoding="utf-8") as f:
                        users = _json.load(f)
                    u = users.get(username, {})
                    expires_at = u.get("expires_at")
                except Exception:
                    pass
                self._send_json({"ok": True, "user": {"username": username, "role": role, "expires_at": expires_at}})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/files":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            from gateway.auth import require_permission as _req_files
            perm_err = _req_files(self._get_token(), "files")
            if perm_err:
                self._send_json(perm_err, 403)
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
            log_file = os.path.basename(qs.get("file", ["cll1.log"])[0] or "cll1.log")
            try:
                lines = max(1, min(500, int(qs.get("lines", ["50"])[0])))
            except Exception:
                lines = 50
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

        if path == "/api/scheduler/appointments":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            self._send_json(self._sched_read("appointments.json", "start"))
            return

        if path == "/api/scheduler/messages":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            qs = parse_qs(parsed.query)
            try:
                limit = max(1, min(int(qs.get("limit", ["50"])[0]), 200))
            except (TypeError, ValueError):
                limit = 50
            result = self._sched_read("messages.json", "created_at")
            if result.get("ok"):
                items = result.get("items", [])
                items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
                result["items"] = items[:limit]
            self._send_json(result)
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
                # Use ModeManager as single source of truth
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

        if path == "/api/reflex/metrics":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from core.neural.reflex import get_reflex_registry
                reflex = get_reflex_registry()
                metrics = reflex.get_metrics()
                self._send_json({"ok": True, "metrics": metrics})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
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

        if path == "/api/graph":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from core.knowledge_graph import get_knowledge_graph
                kg = get_knowledge_graph()
                nodes = []
                edges = []
                for node_id, node_data in kg.nodes.items():
                    nodes.append({
                        "id": node_id,
                        "title": node_data.get("title", node_id),
                        "type": node_data.get("type", "note"),
                        "body": node_data.get("content", "")[:500],
                        "connections": len(node_data.get("links", []))
                    })
                for node_id, node_data in kg.nodes.items():
                    for link in node_data.get("links", []):
                        edges.append({"source": node_id, "target": link})
                self._send_json({"ok": True, "nodes": nodes, "edges": edges})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/missions":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from core.memory import get_memory
                mem = get_memory()
                missions = mem.get("missions", [])
                self._send_json({"ok": True, "missions": missions})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/goal":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from core.memory import get_memory
                mem = get_memory()
                self._send_json({"ok": True, "goal": mem.get("goal", "")})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/profile":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from core.memory import get_memory
                mem = get_memory()
                self._send_json({"ok": True, "profile": mem.get("profile", "")})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/personality":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            try:
                from core.memory import get_memory
                mem = get_memory()
                self._send_json({"ok": True, "personality": mem.get("personality", "")})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
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

        # --- User Management GET (admin only) ---
        if path == "/api/users":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            from gateway.auth import cleanup_expired_users, list_users
            try:
                cleanup_expired_users()  # varredura oportunista a cada listagem
            except Exception:
                pass
            result = list_users(token)
            self._send_json(result)
            return

        if path == "/api/roles":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            from gateway.auth import get_available_roles
            result = get_available_roles()
            self._send_json(result)
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/logout":
            token = self._get_token()
            if token:
                try:
                    from gateway.auth import logout as _logout
                    _logout(token)
                except Exception:
                    pass
            self._send_json({"ok": True})
            return

        if path == "/api/login":
            ip = _real_ip(self)
            allowed, retry = _login_check(ip)
            if not allowed:
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", str(retry))
                self.end_headers()
                self.wfile.write(json.dumps(
                    {"ok": False, "error": "Muitas tentativas. Aguarde e tente de novo.",
                     "retry_after": retry}).encode("utf-8"))
                return
            body = self._read_body()
            username = body.get("username", "")
            password = body.get("password", "")
            from gateway.auth import login
            session = login(username, password)
            if session:
                _login_clear(ip)
                self._send_json({"ok": True, "session": session})
            else:
                _login_record_fail(ip)
                self._send_json({"ok": False, "error": "Usuario ou senha invalidos"}, 401)
            return

        if path == "/api/exec":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            from gateway.auth import require_permission as _req_perm
            perm_err = _req_perm(token, "terminal")
            if perm_err:
                self._send_json(perm_err, 403)
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

        if path == "/api/cll1/terminal":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            from gateway.auth import require_permission as _req_perm2
            perm_err = _req_perm2(token, "terminal")
            if perm_err:
                self._send_json(perm_err, 403)
                return
            body = self._read_body()
            command = body.get("command", "")
            if not command:
                self._send_json({"ok": False, "error": "command required"}, 400)
                return
            try:
                from core.tools.cll1_tools import execute_cll1_tool
                result = execute_cll1_tool("cll1_terminal", {"command": command})
                self._send_json(result)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/file":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            from gateway.auth import require_permission as _req_file
            perm_err = _req_file(self._get_token(), "files")
            if perm_err:
                self._send_json(perm_err, 403)
                return
            body = self._read_body()
            action = body.get("action", "")
            rel = body.get("path", "")
            # Arquivos sensíveis (segredos/hashes): só admin toca.
            # Sem isso, qualquer usuário autenticado lia .env e users.json.
            if rel and _is_sensitive_path(rel):
                from gateway.auth import get_user_role as _get_role
                if _get_role(self._get_token()) != "admin":
                    self._send_json({"ok": False, "error": "Acesso negado: arquivo restrito"}, 403)
                    return

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
                if dst and _is_sensitive_path(dst):
                    from gateway.auth import get_user_role as _get_role2
                    if _get_role2(self._get_token()) != "admin":
                        self._send_json({"ok": False, "error": "Acesso negado: arquivo restrito"}, 403)
                        return
                from gateway.filesystem import move_file
                try:
                    ok = move_file(self._base_dir, rel, dst)
                    self._send_json({"ok": ok})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
                return

            if action == "copy":
                dst = body.get("destination", "")
                if dst and _is_sensitive_path(dst):
                    from gateway.auth import get_user_role as _get_role3
                    if _get_role3(self._get_token()) != "admin":
                        self._send_json({"ok": False, "error": "Acesso negado: arquivo restrito"}, 403)
                        return
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
            # Ações mutantes (restart/stop/enable) = DoS potencial:
            # exigir permissão 'services' (operador+). 'status' segue aberto.
            if action in ("restart", "stop", "enable"):
                token = self._get_token()
                from gateway.auth import require_permission as _req_perm3
                perm_err = _req_perm3(token, "services")
                if perm_err:
                    self._send_json(perm_err, 403)
                    return
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

        if path == "/api/scheduler/confirm":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            from gateway.auth import require_permission as _req_sched
            perm_err = _req_sched(token, "missions")
            if perm_err:
                self._send_json(perm_err, 403)
                return
            body = self._read_body()
            event_id = str(body.get("event_id", "")).strip()
            note = body.get("note", "")
            note = note.strip()[:300] if isinstance(note, str) else ""
            if not event_id:
                self._send_json({"ok": False, "success": False, "error": "event_id obrigatório"}, 400)
                return
            self._send_json(self._sched_proxy(
                "/api/confirm-appointment",
                {"event_id": event_id, "confirm": True, "note": note}))
            return

        if path == "/api/scheduler/cancel":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            from gateway.auth import require_permission as _req_sched2
            perm_err = _req_sched2(token, "missions")
            if perm_err:
                self._send_json(perm_err, 403)
                return
            body = self._read_body()
            event_id = str(body.get("event_id", "")).strip()
            note = body.get("note", "")
            note = note.strip()[:300] if isinstance(note, str) else ""
            if not event_id:
                self._send_json({"ok": False, "success": False, "error": "event_id obrigatório"}, 400)
                return
            self._send_json(self._sched_proxy(
                "/api/confirm-appointment",
                {"event_id": event_id, "confirm": False, "note": note}))
            return

        if path == "/api/scheduler/reschedule":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            from gateway.auth import require_permission as _req_sched3
            perm_err = _req_sched3(token, "missions")
            if perm_err:
                self._send_json(perm_err, 403)
                return
            body = self._read_body()
            event_id = str(body.get("event_id", "")).strip()
            new_start = body.get("new_start", "")
            new_start = new_start.strip() if isinstance(new_start, str) else ""
            if not event_id or not new_start:
                self._send_json({"ok": False, "success": False,
                                 "error": "event_id e new_start obrigatórios"}, 400)
                return
            payload = {"event_id": event_id, "new_start": new_start}
            try:
                payload["duration_minutes"] = int(body.get("duration_minutes", 0)) or None
            except (TypeError, ValueError):
                payload["duration_minutes"] = None
            self._send_json(self._sched_proxy("/api/reschedule", payload))
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

        # JARVIS-style endpoints
        if path == "/api/recall":
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
                formatted = []
                for r in results:
                    formatted.append({
                        "title": r.get("title", r.get("id", "Unknown")),
                        "type": r.get("type", "note"),
                        "excerpt": r.get("content", "")[:200],
                        "id": r.get("id", "")
                    })
                self._send_json({"ok": True, "results": formatted})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/missions":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            if self.command == "GET":
                try:
                    from core.memory import get_memory
                    mem = get_memory()
                    missions = mem.get("missions", [])
                    self._send_json({"ok": True, "missions": missions})
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
                return
            body = self._read_body()
            task = body.get("task", "")
            if not task:
                self._send_json({"ok": False, "error": "Task required"}, 400)
                return
            try:
                from core.memory import get_memory
                mem = get_memory()
                missions = mem.get("missions", [])
                mission_id = f"mission_{len(missions)+1}"
                missions.append({"id": mission_id, "task": task, "status": "pending", "created": __import__("time").time()})
                mem["missions"] = missions
                mem.save()
                self._send_json({"ok": True, "id": mission_id})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/goal":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            goal = body.get("goal", "")
            if not goal:
                self._send_json({"ok": False, "error": "Goal required"}, 400)
                return
            try:
                from core.memory import get_memory
                mem = get_memory()
                mem["goal"] = goal
                mem.save()
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/profile":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            profile = body.get("profile", "")
            if not profile:
                self._send_json({"ok": False, "error": "Profile required"}, 400)
                return
            try:
                from core.memory import get_memory
                mem = get_memory()
                mem["profile"] = profile
                mem.save()
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/personality":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            body = self._read_body()
            personality = body.get("personality", "")
            if not personality:
                self._send_json({"ok": False, "error": "Personality required"}, 400)
                return
            try:
                from core.memory import get_memory
                mem = get_memory()
                mem["personality"] = personality
                mem.save()
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

                # --- User Management (admin only) ---
        if path == "/api/users":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            if self.command == "GET":
                from gateway.auth import list_users
                result = list_users(token)
                self._send_json(result)
                return
            body = self._read_body()
            action = body.get("action", "create")
            if action == "create":
                from gateway.auth import create_user
                username = body.get("username", "")
                password = body.get("password", "")
                role = body.get("role", "bicicleta-com-rodinhas")
                expires_at = body.get("expires_at")
                if not username or not password:
                    self._send_json({"ok": False, "error": "username e password obrigatórios"}, 400)
                    return
                if expires_at is not None:
                    try:
                        expires_at = float(expires_at)
                    except (ValueError, TypeError):
                        self._send_json({"ok": False, "error": "expires_at deve ser timestamp numérico"}, 400)
                        return
                try:
                    with open("debug_create_user.log", "a") as f:
                        f.write(f"DEBUG: Calling create_user with token={token[:10]}..., username={username}, role={role}\n")
                    result = create_user(token, username, password, role, expires_at)
                    with open("debug_create_user.log", "a") as f:
                        f.write(f"DEBUG: create_user returned: {result}\n")
                except Exception as e:
                    import traceback
                    with open("debug_create_user.log", "a") as f:
                        f.write(f"DEBUG ERROR in create_user: {e}\n")
                        traceback.print_exc(file=open("debug_create_user.log", "a"))
                    self._send_json({"ok": False, "error": f"Erro interno: {e}"}, 500)
                    return
                self._send_json(result)
                return
            elif action == "delete":
                from gateway.auth import delete_user
                username = body.get("username", "")
                if not username:
                    self._send_json({"ok": False, "error": "username obrigatório"}, 400)
                    return
                result = delete_user(token, username)
                self._send_json(result)
                return
            elif action == "change_role":
                from gateway.auth import change_role
                username = body.get("username", "")
                new_role = body.get("role", "")
                if not username or not new_role:
                    self._send_json({"ok": False, "error": "username e role obrigatórios"}, 400)
                    return
                result = change_role(token, username, new_role)
                self._send_json(result)
                return
            self._send_json({"ok": False, "error": f"Ação desconhecida: {action}"}, 400)
            return
        if path == "/api/users/cleanup":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            from gateway.auth import cleanup_expired_users
            result = cleanup_expired_users()
            self._send_json(result)
            return

        if path == "/api/user/password":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            body = self._read_body()
            username = body.get("username", "")
            old_password = body.get("old_password", "")
            new_password = body.get("new_password", "")
            if not username or not new_password:
                self._send_json({"ok": False, "error": "username e new_password obrigatórios"}, 400)
                return
            from gateway.auth import change_password
            result = change_password(token, username, old_password, new_password)
            self._send_json(result)
            return

        if path == "/api/roles":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            from gateway.auth import get_available_roles
            result = get_available_roles()
            self._send_json(result)
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

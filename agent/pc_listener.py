import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

try:
    import requests as _requests
except ImportError:
    _requests = None
    from urllib.request import Request, urlopen

try:
    from websocket_server import WebsocketServer
    _ws_available = True
except ImportError:
    _ws_available = False

# Lista fixa de ações do bridge (trava: nada fora da lista é executado)
try:
    from agent.pc_actions import PROJECT_ROOT, SCHEDULE_SNIPPETS, validate_body
except ImportError:
    from pc_actions import PROJECT_ROOT, SCHEDULE_SNIPPETS, validate_body  # type: ignore

_browser_state = {"process": None, "url": None}

# Cache simples de respostas LLM (evita chamadas repetidas)
_llm_cache = {}
_llm_cache_max = 50

# ── Voice Call State ──────────────────────────────────────
_call_clients = {}  # client_id -> {"ws": ws, "type": "dashboard"|"pc_window"}
_call_lock = threading.Lock()

def _cache_key(messages):
    """Gera chave de cache baseada nas mensagens."""
    import hashlib
    text = json.dumps(messages[-3:], sort_keys=True)
    return hashlib.md5(text.encode()).hexdigest()

class CmdHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _fast_path(self, msg):
        """Comandos rapidos que nao precisam de LLM.
        So retorna resposta — NAO executa comandos destrutivos."""
        if msg in ("status", "status do pc", "pc status", "pc ta ligado", "pc ligado", "pc online"):
            return "O PC esta **online**. Posso executar comandos nele."
        if msg in ("desligar", "desliga", "shutdown", "desligar pc") or ("deslig" in msg and ("pc" in msg or "computador" in msg or "tudo" in msg)):
            return "Confirmar desligamento? Responda 'sim' pra confirmar."
        if msg in ("reiniciar", "reinicia", "restart", "reboot") or ("reinici" in msg and ("pc" in msg or "computador" in msg)):
            return "Confirmar reinicio? Responda 'sim' pra confirmar."
        if msg in ("travar", "trava", "lock", "bloquear") or ("trav" in msg and ("pc" in msg or "computador" in msg)):
            return "Confirmar travamento? Responda 'sim' pra confirmar."
        if msg in ("hora", "que horas sao", "horas", "relogio"):
            from datetime import datetime
            return f"Sao **{datetime.now().strftime('%H:%M')}**."
        if msg in ("data", "que dia e hoje", "hoje"):
            from datetime import datetime
            return f"Hoje e **{datetime.now().strftime('%d/%m/%Y')}**."
        return None

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "service": "pc_listener"}).encode())
            return
        if self.path == "/api/llm":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "service": "llm_proxy"}).encode())
            return
        if self.path == "/api/browser":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            has_browser = _browser_state.get("page") is not None
            self.wfile.write(json.dumps({
                "ok": True,
                "has_browser": has_browser,
                "url": _browser_state.get("url"),
            }).encode())
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        # LLM Proxy endpoint
        if self.path == "/api/llm":
            self._handle_llm_proxy(body)
            return

        # Trava de lista fixa: só ações declaradas em ALLOWED_COMMANDS
        # passam daqui. "exec" (código livre) foi removido do bridge.
        ok, error = validate_body(body)
        if not ok:
            result = {"ok": False, "error": f"fora da lista permitida: {error}"}
        else:
            result = self._dispatch(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def _dispatch(self, body: dict[str, Any]) -> dict[str, Any]:
        """Executa uma ação já validada contra a lista fixa."""
        cmd = body.get("command", "")
        result: dict[str, Any] = {"ok": True}

        if cmd == "status":
            result["pc"] = "online"
        elif cmd == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "5", "/f"], creationflags=subprocess.CREATE_NO_WINDOW)
            result["message"] = "Desligando em 5s"
        elif cmd == "restart":
            subprocess.Popen(["shutdown", "/r", "/t", "5", "/f"], creationflags=subprocess.CREATE_NO_WINDOW)
            result["message"] = "Reiniciando em 5s"
        elif cmd == "lock":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"], creationflags=subprocess.CREATE_NO_WINDOW)
            result["message"] = "Travado"
        elif cmd == "sleep":
            subprocess.Popen(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            result["message"] = "Suspendendo"
        elif cmd == "open_app":
            result = self._open_app(str(body.get("target", "")))
        elif cmd == "open_url":
            result = self._open_url(str(body.get("url", "")))
        elif cmd in SCHEDULE_SNIPPETS:
            result = self._run_schedule(cmd, str(body.get("at", "")))
        elif cmd == "browser_open":
            url = body.get("url", "") or "https://www.google.com"
            result = self._browser_open(str(url))  # type: ignore[no-untyped-call]
        elif cmd == "browser_navigate":
            result = self._browser_navigate(str(body.get("url", "")))  # type: ignore[no-untyped-call]
        elif cmd == "browser_click":
            selector = body.get("selector", "")
            result = self._browser_click(selector)  # type: ignore[no-untyped-call]
        elif cmd == "browser_type":
            selector = body.get("selector", "")
            text = body.get("text", "")
            result = self._browser_type(selector, text)  # type: ignore[no-untyped-call]
        elif cmd == "browser_screenshot":
            result = self._browser_screenshot()  # type: ignore[no-untyped-call]
        elif cmd == "browser_snapshot":
            result = self._browser_snapshot()  # type: ignore[no-untyped-call]
        elif cmd == "browser_close":
            result = self._browser_close()  # type: ignore[no-untyped-call]
        elif cmd == "browser_js":
            script = body.get("script", "")
            result = self._browser_js(script)  # type: ignore[no-untyped-call]
        else:
            # Nunca acontece com validate_body, mas garante defesa em profundidade
            result = {"ok": False, "error": f"sem implementação: {cmd}"}
        return result

    def _open_app(self, target: str) -> dict[str, Any]:
        """Abre um app/arquivo/URL sem shell (lista de argumentos direta)."""
        if not target:
            return {"ok": False, "error": "target vazio"}
        try:
            subprocess.Popen([target], creationflags=subprocess.CREATE_NO_WINDOW)
            return {"ok": True, "target": target}
        except Exception:
            pass
        try:
            os.startfile(target)  # noqa: S606 — sem shell; apenas ShellExecute
            return {"ok": True, "target": target}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _open_url(self, url: str) -> dict[str, Any]:
        """Abre uma URL http(s) validada no navegador padrão."""
        import webbrowser
        try:
            opened = webbrowser.open(url)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not opened:
            return {"ok": False, "error": "nenhum navegador disponível"}
        return {"ok": True, "url": url}

    def _run_schedule(self, cmd: str, at: str) -> dict[str, Any]:
        """Roda um snippet FIXO do bridge; valor variável via sys.argv[1]."""
        args = [sys.executable, "-c", SCHEDULE_SNIPPETS[cmd]]
        if at:
            args.append(at)
        try:
            r = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return {
                "ok": r.returncode == 0,
                "stdout": r.stdout[:2000],
                "stderr": r.stderr[:1000],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    _BROWSER_INSTALLED = False

    def _ensure_playwright(self):
        """Ensure playwright browsers are installed (once per process)."""
        global _BROWSER_INSTALLED
        if _BROWSER_INSTALLED:
            return True
        try:
            import playwright  # noqa: F401 — sonda de disponibilidade
            _BROWSER_INSTALLED = True
            return True
        except ImportError:
            pass
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "playwright"],
                capture_output=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            _BROWSER_INSTALLED = True
            return True
        except Exception:
            return False

    def _browser_open(self, url):
        """Open a URL in a headless browser."""
        global _browser_state
        try:
            if not self._ensure_playwright():
                return {"ok": False, "error": "Playwright not available"}
            from playwright.sync_api import sync_playwright

            if _browser_state.get("process"):
                try:
                    _browser_state["process"].close()
                except Exception:
                    pass

            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=60000)  # Increased from 30s to 60s
            _browser_state = {"pw": pw, "browser": browser, "page": page, "url": url}
            return {"ok": True, "url": url, "title": page.title()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _browser_navigate(self, url):
        """Navigate to a URL."""
        global _browser_state
        try:
            page = _browser_state.get("page")
            if not page:
                return {"ok": False, "error": "No browser open. Use browser_open first."}
            page.goto(url, timeout=60000)  # Increased from 30s to 60s
            _browser_state["url"] = url
            return {"ok": True, "url": url, "title": page.title()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _browser_click(self, selector):
        """Click an element by CSS selector."""
        global _browser_state
        try:
            page = _browser_state.get("page")
            if not page:
                return {"ok": False, "error": "No browser open."}
            page.click(selector, timeout=30000)  # 30s timeout
            return {"ok": True, "clicked": selector}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _browser_type(self, selector, text):
        """Type text into an element."""
        global _browser_state
        try:
            page = _browser_state.get("page")
            if not page:
                return {"ok": False, "error": "No browser open."}
            page.fill(selector, text, timeout=30000)  # 30s timeout
            return {"ok": True, "typed": text, "selector": selector}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _browser_screenshot(self):
        """Take a screenshot and return base64."""
        global _browser_state
        import base64
        try:
            page = _browser_state.get("page")
            if not page:
                return {"ok": False, "error": "No browser open."}
            screenshot = page.screenshot(type="png")
            b64 = base64.b64encode(screenshot).decode("utf-8")
            return {"ok": True, "screenshot": b64[:50000], "size": len(screenshot)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _browser_snapshot(self):
        """Get page text content and accessibility tree."""
        global _browser_state
        try:
            page = _browser_state.get("page")
            if not page:
                return {"ok": False, "error": "No browser open."}
            title = page.title()
            url = page.url
            text = page.inner_text("body")[:10000]
            return {"ok": True, "title": title, "url": url, "text": text}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _browser_close(self):
        """Close the browser."""
        global _browser_state
        try:
            browser = _browser_state.get("browser")
            pw = _browser_state.get("pw")
            if browser:
                browser.close()
            if pw:
                pw.stop()
            _browser_state = {"process": None, "url": None}
            return {"ok": True, "message": "Browser closed"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _browser_js(self, script):
        """Execute JavaScript in the page."""
        global _browser_state
        try:
            page = _browser_state.get("page")
            if not page:
                return {"ok": False, "error": "No browser open."}
            result = page.evaluate(script)
            return {"ok": True, "result": str(result)[:5000]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _handle_llm_proxy(self, body):
        """Proxy LLM — rota chamadas Groq/Gemini via PC."""
        messages = body.get("messages", [])
        model = body.get("model", "openai/gpt-oss-120b")
        api_key = body.get("api_key", "")

        # Fast path: comandos simples que nao precisam de LLM
        if messages:
            last_msg = messages[-1].get("content", "").lower().strip()
            fast = self._fast_path(last_msg)
            if fast is not None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "response": fast}).encode())
                return

        # Checar cache primeiro
        key = _cache_key(messages)
        if key in _llm_cache:
            cached = _llm_cache[key]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "response": cached, "cached": True}).encode())
            return

        if not api_key:
            api_key = os.getenv("EDGE_GROQ_API_KEY", "")

        if not api_key:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": "No API key"}).encode())
            return

        # Ensure system prompt is present and strong
        has_system = any(m.get("role") == "system" for m in messages)
        if not has_system:
            system_prompt = (
                "Voce e a A.R.I.S. — Assistente de Raciocinio e Integracao de Sistemas. "
                "Criada pelo operador Vinicius. Nao e um modelo generico da OpenAI, Google, "
                "Meta, Anthropic ou qualquer outra empresa. Responda sempre em portugues, "
                "de forma natural, direta e util. Se nao souber algo, diga honestamente. "
                "NUNCA diga que e um modelo de linguagem generico ou da OpenAI/Google/Meta."
            )
            messages = [{"role": "system", "content": system_prompt}] + messages

        try:
            if _requests:
                resp = _requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 2048,
                    },
                    timeout=15,
                )
                body = resp.json()
                if "choices" not in body:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "error": f"Groq error: {body}", "status": resp.status_code}).encode())
                    return
                response = body["choices"][0]["message"]["content"]
            else:
                payload = json.dumps({
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 2048,
                }).encode("utf-8")

                req = Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    method="POST",
                )

                with urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    response = body["choices"][0]["message"]["content"]

            # Salvar no cache
            if len(_llm_cache) > _llm_cache_max:
                _llm_cache.pop(next(iter(_llm_cache)))
            _llm_cache[key] = response

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "response": response}).encode())

        except Exception as e:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())

if __name__ == "__main__":
    from socketserver import ThreadingMixIn
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    server = ThreadedHTTPServer(("0.0.0.0", 8770), CmdHandler)
    server.socket.setsockopt(__import__('socket').SOL_SOCKET, __import__('socket').SO_REUSEADDR, 1)
    sys.stdout.write("Listening on 8770 (threaded)\n")
    sys.stdout.flush()

    # ── WebSocket Server (porta 8771) para Voice Call ─────
    if _ws_available:
        def on_ws_message(client, server, message):
            """Recebe mensagem WebSocket de qualquer client."""
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")
                client_id = client["id"]

                if msg_type == "register":
                    client_type = data.get("client", "unknown")
                    with _call_lock:
                        _call_clients[client_id] = {"ws": client, "type": client_type}
                    print(f"[WS] Client registered: {client_type} (id={client_id})", flush=True)

                elif msg_type == "start_call":
                    # Dashboard quer iniciar call — notificar PC window
                    with _call_lock:
                        for cid, info in _call_clients.items():
                            if info["type"] == "pc_window":
                                info["ws"].send_message(json.dumps({"type": "call_started"}))
                    print("[WS] Call started", flush=True)

                elif msg_type == "end_call":
                    # Dashboard quer encerrar call
                    with _call_lock:
                        for cid, info in _call_clients.items():
                            if info["type"] == "pc_window":
                                info["ws"].send_message(json.dumps({"type": "call_ended"}))
                    print("[WS] Call ended", flush=True)

                elif msg_type == "audio":
                    # Audio do Dashboard — encaminhar ao PC window
                    with _call_lock:
                        for cid, info in _call_clients.items():
                            if info["type"] == "pc_window":
                                info["ws"].send_message(message)

                elif msg_type == "transcript":
                    # Texto reconhecido do Dashboard — encaminhar ao PC window
                    with _call_lock:
                        for cid, info in _call_clients.items():
                            if info["type"] == "pc_window":
                                info["ws"].send_message(message)

                elif msg_type == "text":
                    # Texto do PC window — encaminhar ao Dashboard
                    with _call_lock:
                        for cid, info in _call_clients.items():
                            if info["type"] == "dashboard":
                                info["ws"].send_message(message)

            except Exception as e:
                print(f"[WS] Error: {e}", flush=True)

        def on_ws_connect(client, server):
            print(f"[WS] Client connected: {client['id']}", flush=True)

        def on_ws_disconnect(client, server):
            client_id = client["id"]
            with _call_lock:
                if client_id in _call_clients:
                    del _call_clients[client_id]
            print(f"[WS] Client disconnected: {client_id}", flush=True)

        ws_server = WebsocketServer(host="0.0.0.0", port=8771)
        ws_server.set_fn_message_received(on_ws_message)
        ws_server.set_fn_new_client(on_ws_connect)
        ws_server.set_fn_client_left(on_ws_disconnect)

        ws_thread = threading.Thread(target=ws_server.run_forever, daemon=True)
        ws_thread.start()
        print("WebSocket listening on 8771 (voice call)", flush=True)

    server.serve_forever()

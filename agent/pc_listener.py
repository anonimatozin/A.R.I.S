import json
import os
import subprocess
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import requests as _requests
except ImportError:
    _requests = None
    from urllib.request import Request, urlopen

_browser_state = {"process": None, "url": None}

# Cache simples de respostas LLM (evita chamadas repetidas)
_llm_cache = {}
_llm_cache_max = 50

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
        if msg in ("desligar", "desliga", "shutdown", "desligar pc"):
            return "Confirmar desligamento? Responda 'sim' pra confirmar."
        if msg in ("reiniciar", "reinicia", "restart", "reboot"):
            return "Confirmar reinicio? Responda 'sim' pra confirmar."
        if msg in ("travar", "trava", "lock", "bloquear"):
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

        cmd = body.get("command", "")
        result = {"ok": True}
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
        elif cmd == "exec":
            code = body.get("code", "")
            try:
                r = subprocess.run(
                    [sys.executable, "-c", code],
                    capture_output=True, text=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                result["stdout"] = r.stdout[:5000]
                result["stderr"] = r.stderr[:2000]
                result["returncode"] = r.returncode
            except Exception as e:
                result["ok"] = False
                result["error"] = str(e)
        elif cmd == "browser_open":
            url = body.get("url", "https://www.google.com")
            result = self._browser_open(url)
        elif cmd == "browser_navigate":
            url = body.get("url", "")
            result = self._browser_navigate(url)
        elif cmd == "browser_click":
            selector = body.get("selector", "")
            result = self._browser_click(selector)
        elif cmd == "browser_type":
            selector = body.get("selector", "")
            text = body.get("text", "")
            result = self._browser_type(selector, text)
        elif cmd == "browser_screenshot":
            result = self._browser_screenshot()
        elif cmd == "browser_snapshot":
            result = self._browser_snapshot()
        elif cmd == "browser_close":
            result = self._browser_close()
        elif cmd == "browser_js":
            script = body.get("script", "")
            result = self._browser_js(script)
        else:
            result["ok"] = False
            result["error"] = f"Unknown: {cmd}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def _ensure_playwright(self):
        """Ensure playwright browsers are installed."""
        try:
            import playwright
            return True
        except ImportError:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "playwright"],
                capture_output=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return True

    def _browser_open(self, url):
        """Open a URL in a headless browser."""
        global _browser_state
        try:
            self._ensure_playwright()
            from playwright.sync_api import sync_playwright

            if _browser_state.get("process"):
                try:
                    _browser_state["process"].close()
                except Exception:
                    pass

            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)
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
            page.goto(url, timeout=30000)
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
            page.click(selector, timeout=10000)
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
            page.fill(selector, text, timeout=10000)
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
    server.serve_forever()

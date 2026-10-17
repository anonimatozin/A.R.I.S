"""HUD Panel Launcher — painel nativo do PC (PRIMARY only).

Servidor HTTP local + pywebview para abrir janela dedicada.
Mostra status ARIS em tempo real, métricas, controle de mic,
e conecta eventos de gestos/rostos via Event Bus.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Any, Optional

# Adiciona path do projeto ANTES de qualquer import local
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import webview
    HAS_WEBVIEW = True
except ImportError:
    HAS_WEBVIEW = False
    webview = None  # type: ignore[assignment]

from utils.logger import Logger

from core.neural.events import Event
from core.neural.event_bus import EventBus
from core.neural.mode import get_mode_manager


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTPServer que handle requests em threads separadas (necessário para SSE)."""
    daemon_threads = True


class HUDRequestHandler(SimpleHTTPRequestHandler):
    """Handler HTTP para servir HUD e API endpoints."""

    def __init__(self, *args, hud_server: 'HUDServer', **kwargs):
        self._hud_server = hud_server
        super().__init__(*args, directory=str(hud_server._hud_dir), **kwargs)

    def log_message(self, format: str, *args) -> None:
        pass

    def do_GET(self):
        parsed_path = self.path.split('?')[0]

        if parsed_path == '/api/hud/events':
            self._handle_sse()
            return
        elif parsed_path == '/api/hud/status':
            self._send_json(self._hud_server.get_status())
            return
        elif parsed_path == '/api/hud/metrics':
            self._send_json(self._hud_server.get_metrics())
            return
        elif parsed_path == '/api/hud/mode':
            self._send_json({"mode": self._hud_server.get_mode()})
            return
        elif parsed_path == '/api/hud/chat':
            self._send_json(self._hud_server.get_chat())
            return
        elif parsed_path in ('/api/hud/voice_state', '/state'):
            self._send_json(self._hud_server.get_voice_state())
            return
        elif parsed_path == '/config':
            # Para ai-visualizer core.js (adaptado): nome ARIS + faces instaladas
            self._send_json(self._hud_server.get_visualizer_config())
            return
        elif parsed_path == '/api/hud/camera/frame':
            self._handle_camera_frame()
            return
        elif parsed_path == '/api/hud/camera/stream':
            self._handle_camera_stream()
            return

        if parsed_path == '/' or parsed_path == '/index.html':
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        parsed_path = self.path.split('?')[0]
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length else '{}'

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        if self.path == '/api/hud/mic/toggle':
            result = self._hud_server.toggle_mic()
            self._send_json(result)
        elif self.path == '/api/hud/chat':
            result = self._hud_server.send_command(data.get('text', data.get('command', '')))
            self._send_json(result)
        elif self.path == '/api/hud/speak':
            text = data.get('text', '')
            if text:
                self._hud_server._speak_async(text)
                self._send_json({"ok": True})
            else:
                self._send_json({"ok": False, "error": "Texto vazio"})
        elif self.path == '/api/hud/command':
            result = self._hud_server.send_command(data.get('command', ''))
            self._send_json(result)
        elif self.path == '/api/hud/face/consent':
            result = self._hud_server.handle_face_consent(data)
            self._send_json(result)
        else:
            self._send_json({"ok": False, "error": "Not found"}, 404)

    def _handle_camera_frame(self):
        """Retorna um frame JPEG da câmera."""
        frame_b64 = self._hud_server.get_camera_frame()
        if frame_b64:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"frame": frame_b64}).encode('utf-8'))
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"frame": None}).encode('utf-8'))

    def _handle_camera_stream(self):
        """MJPEG stream — frames contínuos via HTTP multipart."""
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        import cv2
        boundary = b'--frame'

        try:
            while self._hud_server._running:
                frame_b64 = self._hud_server.get_camera_frame()
                if frame_b64:
                    import base64
                    frame_bytes = base64.b64decode(frame_b64)
                    self.wfile.write(boundary + b'\r\n')
                    self.wfile.write(b'Content-Type: image/jpeg\r\n')
                    self.wfile.write(b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n')
                    self.wfile.write(frame_bytes)
                    self.wfile.write(b'\r\n')
                    self.wfile.flush()
                time.sleep(0.03)  # ~30fps max
        except (ConnectionError, BrokenPipeError, OSError):
            pass

    def _handle_sse(self):
        """Server-Sent Events para eventos em tempo real."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        client_id = id(self)
        self._hud_server._sse_clients[client_id] = self

        try:
            self._send_sse_event('connected', {'client_id': client_id})

            while self._hud_server._running:
                time.sleep(30)
                self._send_sse_event('ping', {'ts': time.time()})
        except (ConnectionError, BrokenPipeError, OSError):
            pass
        finally:
            self._hud_server._sse_clients.pop(client_id, None)

    def _send_sse_event(self, event_type: str, data: dict):
        """Envia evento SSE para este cliente."""
        try:
            payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            self.wfile.write(payload.encode('utf-8'))
            self.wfile.flush()
        except (ConnectionError, BrokenPipeError, OSError):
            raise

    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))


class HUDServer:
    """Servidor HUD + API + WebSocket/SSE."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8790,
        logger: Optional[Logger] = None,
    ):
        self._host = host
        self._port = port
        self._logger = logger
        self._hud_dir = Path(__file__).parent
        self._running = False
        self._server: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._webview_window = None

        # Event Bus integration
        self._event_bus: Optional[EventBus] = None
        self._event_handlers_registered = False

        # SSE clients
        self._sse_clients: dict[int, Any] = {}

        # State
        self._mic_active = False
        self._pending_face_consent: Optional[dict] = None

        # Chat history (funcional — fonte para o painel de conversa)
        self._chat_history: list[dict] = []
        self._chat_lock = threading.Lock()

        # Voice/face state (funcional — fonte para /api/hud/voice_state
        # e para o ai-visualizer adaptado; mapeado dos eventos reais
        # aris_status/mic_status que o HUD já recebe via SSE)
        self._voice_state = "idle"
        self._voice_level = 0.0
        self._voice_samples: list[float] = [0.0] * 64
        self._voice_alert = False
        self._voice_updated = 0.0

        # Camera
        self._camera = None
        self._camera_lock = threading.Lock()

        # Metrics thread
        self._metrics_thread: Optional[threading.Thread] = None

        if not self._hud_dir.exists():
            raise RuntimeError(f"HUD directory not found: {self._hud_dir}")

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def start(self) -> bool:
        """Inicia servidor HTTP e threads auxiliares (NÃO abre pywebview)."""
        if self._running:
            return True

        self._connect_event_bus()
        self._running = True

        # Start HTTP server
        def make_handler(*args, **kwargs):
            return HUDRequestHandler(*args, hud_server=self, **kwargs)

        self._server = ThreadingHTTPServer((self._host, self._port), make_handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="hud-http",
            daemon=True,
        )
        self._server_thread.start()
        self._log("info", f"HUD HTTP server started on {self.url}")

        # Start periodic metrics broadcaster
        self._metrics_thread = threading.Thread(
            target=self._metrics_loop,
            name="hud-metrics",
            daemon=True,
        )
        self._metrics_thread.start()

        # Start camera if enabled
        self._init_camera()

        if HAS_WEBVIEW:
            self._log("info", "pywebview disponivel — janela sera aberta na main thread")
        else:
            self._log("warning", (
                "pywebview NAO ESTA INSTALADO. "
                "HUD acessivel apenas via browser em " + self.url + "\n"
                "Para janela nativa: pip install pywebview"
            ))

        return True

    def _connect_event_bus(self):
        """Conecta ao Event Bus local para receber eventos em tempo real."""
        try:
            self._event_bus = EventBus(logger=self._logger)
            if self._event_bus and not self._event_handlers_registered:
                self._register_event_handlers()
                self._event_handlers_registered = True
        except Exception as e:
            self._log("warning", f"Nao conectou ao Event Bus: {e}")

    def _register_event_handlers(self):
        """Registra handlers para eventos de interesse do HUD."""
        if not self._event_bus:
            return

        def make_handler(event_type: str):
            def handler(event: Event):
                if event_type == 'aris_status':
                    state = (event.payload or {}).get('state', 'idle')
                    self._set_voice_state(state)
                elif event_type == 'mic_status':
                    if (event.payload or {}).get('active'):
                        self._set_voice_state('listening')
                self._broadcast_sse(event_type, event.payload)
            return handler

        event_types = [
            'aris_status',
            'system_metrics',
            'mode_change',
            'vision_gesture_detected',
            'vision_face_detected',
            'vision_face_recognized',
            'mic_status',
            'chat_message',
        ]

        for etype in event_types:
            try:
                self._event_bus.subscribe(etype, make_handler(etype))
            except Exception as e:
                self._log("warning", f"Falha ao registrar handler para {etype}: {e}")

    def _broadcast_sse(self, event_type: str, payload: dict):
        """Envia evento para todos os clientes SSE conectados."""
        event_data = {"type": event_type, "payload": payload}
        dead_clients = []

        for client_id, client in self._sse_clients.items():
            try:
                client._send_sse_event(event_type, event_data)
            except Exception:
                dead_clients.append(client_id)

        for cid in dead_clients:
            self._sse_clients.pop(cid, None)

    def _metrics_loop(self):
        """Envia metricas periodicamente via SSE (a cada 2s)."""
        while self._running:
            time.sleep(2)
            if not self._sse_clients:
                continue
            try:
                metrics = self.get_metrics()
                self._broadcast_sse('system_metrics', metrics)
            except Exception:
                pass

    def _init_camera(self):
        """Inicializa a câmera se habilitada."""
        cam_enabled = os.environ.get('ARIS_VISION_CAMERA_ENABLED', '0').lower()
        if cam_enabled not in ('1', 'true', 'yes'):
            self._log("info", "Câmera desabilitada (ARIS_VISION_CAMERA_ENABLED=0)")
            return

        try:
            import cv2
            cam_index = int(os.environ.get('ARIS_VISION_CAMERA_INDEX', '0'))
            cap = cv2.VideoCapture(cam_index)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    self._camera = cap
                    self._log("info", f"Câmera {cam_index} aberta com sucesso ({frame.shape[1]}x{frame.shape[0]})")
                else:
                    cap.release()
                    self._log("warning", f"Câmera {cam_index} abriu mas não conseguiu ler frame")
            else:
                self._log("warning", f"Câmera {cam_index} não pôde ser aberta")
        except ImportError:
            self._log("warning", "OpenCV não instalado — câmera indisponível (pip install opencv-python)")
        except Exception as e:
            self._log("warning", f"Erro ao inicializar câmera: {e}")

    def get_camera_frame(self) -> Optional[str]:
        """Retorna frame da câmera como base64 JPEG."""
        if not self._camera:
            return None
        try:
            import cv2
            import base64
            with self._camera_lock:
                ret, frame = self._camera.read()
                if not ret:
                    return None
                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                return base64.b64encode(jpeg.tobytes()).decode('utf-8')
        except Exception:
            return None

    def stop(self):
        """Para servidor e janela."""
        self._running = False

        if self._camera:
            try:
                self._camera.release()
            except Exception:
                pass
            self._camera = None

        if self._server:
            self._server.shutdown()
            self._server = None

        if self._webview_window and HAS_WEBVIEW:
            try:
                self._webview_window.destroy()
            except Exception:
                pass

        if self._server_thread:
            self._server_thread.join(timeout=2.0)

        self._log("info", "HUD Server stopped")

    def _start_webview(self):
        """Cria janela pywebview (deve ser chamado da main thread)."""
        try:
            # Detecta backend
            try:
                from webview.platforms import edgechromium
                backend_name = "EdgeChromium"
            except ImportError:
                try:
                    from webview.platforms import mshtml
                    backend_name = "MSHTML/IE"
                except ImportError:
                    try:
                        from webview.platforms import webkit
                        backend_name = "WebKit"
                    except ImportError:
                        backend_name = "unknown"

            self._log("info", f"pywebview abrindo com backend: {backend_name}")

            window = webview.create_window(
                title="A.R.I.S. HUD — Painel de Controle",
                url=self.url,
                width=1400,
                height=900,
                min_size=(1000, 700),
                frameless=False,
                easy_drag=False,
                on_top=False,
            )
            self._webview_window = window
            return True

        except Exception as e:
            self._log("error", (
                f"FALHA ao criar janela pywebview: {e}\n"
                f"O HUD continua acessivel via browser em {self.url}"
            ))
            return False

    # --- API Endpoints ---

    def _set_voice_state(self, state: str, level: float = 0.0) -> None:
        """Atualiza estado de voz (idle|listening|thinking|speaking)."""
        if state not in ("idle", "listening", "thinking", "speaking"):
            state = "idle"
        self._voice_state = state
        self._voice_level = level
        self._voice_updated = time.time()

    def _add_chat(self, sender: str, text: str) -> dict:
        """Armazena mensagem e difunde via SSE como chat_message."""
        msg = {"sender": sender, "text": text, "ts": time.time()}
        with self._chat_lock:
            self._chat_history.append(msg)
            self._chat_history = self._chat_history[-100:]
        self._broadcast_sse('chat_message', msg)
        return msg

    def get_chat(self) -> dict:
        with self._chat_lock:
            history = list(self._chat_history)
        return {"messages": history}

    def get_voice_state(self) -> dict:
        """Compatível com ai-visualizer /state (adaptado ao Event Bus ARIS).

        Crédito: formato herdado de github.com/jaredrhod/ai-visualizer
        (Jared Rhodenizer, AGPL-3.0-or-later). Em vez dos arquivos
        .voice_state/.voice_waveform, a fonte aqui é o estado real do HUD.
        """
        return {
            "state": self._voice_state,
            "level": self._voice_level,
            "samples": list(self._voice_samples),
            "alert": self._voice_alert,
            "loading": self._voice_state == "thinking",
        }

    def get_visualizer_config(self) -> dict:
        """Config para ai-visualizer core.js (adaptado ao Event Bus ARIS).

        Crédito: faces e core.js de github.com/jaredrhod/ai-visualizer
        (Jared Rhodenizer, AGPL-3.0-or-later). Neural Core é o padrão.
        """
        faces = []
        fdir = self._hud_dir / "faces"
        if fdir.is_dir():
            for p in sorted(fdir.iterdir()):
                if p.is_dir() and (p / "index.html").exists():
                    meta = {"id": p.name, "title": p.name.title(), "tagline": ""}
                    try:
                        meta.update(json.loads((p / "face.json").read_text()))
                    except (OSError, ValueError):
                        pass
                    meta["id"] = p.name
                    faces.append(meta)
        return {"name": "ARIS", "badge": "", "face": "neural",
                "thinking_sound": False, "faces": faces}

    def publish_external(self, event_type: str, payload: dict) -> None:
        """Ponte para o barramento real da ARIS (cll1/main pode chamar).

        O HUD roda em subprocesso com EventBus próprio; este método permite
        injetar eventos do processo pai sem rodar servidores paralelos.
        """
        if event_type == 'aris_status':
            self._set_voice_state(str((payload or {}).get('state', 'idle')))
        self._broadcast_sse(event_type, payload or {})

    def get_status(self) -> dict:
        mm = get_mode_manager()
        metrics = self.get_metrics()
        return {
            "status": "online",
            "mode": mm.mode.value,
            "pc_online": mm.pc_online,
            "mic_active": self._mic_active,
            "hud_url": self.url,
            "metrics": metrics,
        }

    def get_metrics(self) -> dict:
        try:
            from gateway.monitor import get_metrics
            metrics = get_metrics()
        except Exception:
            metrics = {}

        mm = get_mode_manager()
        metrics.update({
            "mode": mm.mode.value,
            "pc_online": mm.pc_online,
            "mic_active": self._mic_active,
        })
        return metrics

    def get_mode(self) -> str:
        return get_mode_manager().mode.value

    def toggle_mic(self) -> dict:
        self._mic_active = not self._mic_active
        self._log("info", f"Microfone {'ativado' if self._mic_active else 'desativado'} via HUD")

        self._broadcast_sse('mic_status', {'active': self._mic_active})

        return {"ok": True, "active": self._mic_active}

    def send_command(self, command: str) -> dict:
        if not command:
            return {"ok": False, "error": "Comando vazio"}

        self._log("info", f"Comando via HUD: {command}")
        self._add_chat("VOCÊ", command)
        self._set_voice_state("thinking")
        self._broadcast_sse('aris_status', {'state': 'thinking'})

        try:
            from edge.edge_chat import EdgeChat
            with self._chat_lock:
                history = [
                    {"role": "user" if m["sender"] == "VOCÊ" else "assistant",
                     "content": m["text"]}
                    for m in self._chat_history[-10:]
                ]
            response = EdgeChat().respond(
                command, {"source": "hud", "history": history})
        except Exception as e:
            response = f"Comando recebido: {command} (edge indisponível: {e})"

        self._add_chat("ARIS", response)
        self._set_voice_state("speaking", level=0.6)
        self._broadcast_sse('aris_status', {'state': 'speaking'})
        self._speak_async(response)
        self._set_voice_state("idle")
        self._broadcast_sse('aris_status', {'state': 'idle'})

        return {"ok": True, "response": response, "echo": command}

    def _speak_async(self, text: str) -> None:
        """Fala a resposta em voz feminina sem bloquear (thread daemon)."""
        if os.getenv("ARIS_HUD_SPEAK", "1") != "1":
            return

        def _run():
            try:
                from utils.voice_hybrid import HybridVoice
                HybridVoice().speak(text)
            except Exception as e:
                self._log("warning", f"TTS HUD falhou: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def handle_face_consent(self, data: dict) -> dict:
        """Processa consentimento de rosto desconhecido."""
        consent = data.get('consent', False)
        encoding = data.get('encoding')
        name = data.get('name', f'Pessoa_{int(time.time())}')

        if not consent:
            self._log("info", "Consentimento negado para rosto desconhecido")
            return {"ok": True, "consented": False}

        if not encoding:
            return {"ok": False, "error": "Encoding nao fornecido"}

        try:
            from core.vision.face_recognition import FaceRecognizer
            from core.vision.sources.camera_source import CameraSource
            import numpy as np

            camera = CameraSource(enabled=True)
            recognizer = FaceRecognizer(camera=camera)

            entity_id = f"person_{name.lower().replace(' ', '_')}"
            recognizer._save_face_encoding(entity_id, encoding)

            try:
                from core.knowledge_graph import get_knowledge_graph
                kg = get_knowledge_graph()
                kg.store(
                    content=f"Nova pessoa conhecida: {name}",
                    node_type="person",
                    tags=["face_recognition", "known_person", name.lower()],
                )
            except Exception:
                pass

            self._broadcast_sse('vision_face_recognized', {
                'name': name,
                'entity_id': entity_id,
                'confidence': 0.8,
            })

            return {"ok": True, "consented": True, "entity_id": entity_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _log(self, level: str, message: str):
        if self._logger:
            getattr(self._logger, level, print)(f"[HUD] {message}")
        else:
            print(f"[HUD] {message}")


def start_hud(
    host: str = "127.0.0.1",
    port: int = 8790,
    logger: Optional[Logger] = None,
) -> HUDServer:
    """Ponto de entrada para iniciar o HUD."""
    hud = HUDServer(host=host, port=port, logger=logger)
    hud.start()
    return hud


if __name__ == "__main__":
    import signal
    import argparse

    parser = argparse.ArgumentParser(description="A.R.I.S. HUD Server")
    parser.add_argument("--no-webview", action="store_true",
                        help="Run HTTP server only (no pywebview window)")
    parser.add_argument("--pygame", action="store_true",
                        help="Launch Pygame HUD instead of pywebview")
    args = parser.parse_args()

    logger = Logger(name="hud", level="INFO")

    # Cria servidor (HTTP + metrics + camera)
    hud = HUDServer(logger=logger)
    hud.start()

    def signal_handler(sig, frame):
        logger.info("Encerrando HUD...")
        hud.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Pygame HUD mode
    if args.pygame:
        logger.info("Iniciando Pygame HUD...")
        try:
            from core.vision.hud.hud_pygame import HUD
            pygame_hud = HUD()
            pygame_hud.run()
        except Exception as e:
            logger.error(f"Pygame HUD falhou: {e}")
            logger.info(f"HUD acessivel via browser em {hud.url}")
        finally:
            hud.stop()
        sys.exit(0)

    # No-webview mode: just HTTP server
    if args.no_webview:
        logger.info(f"HUD HTTP server rodando em {hud.url}. Ctrl+C para sair.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            hud.stop()
        sys.exit(0)

    # pywebview PRECISA rodar na main thread no Windows
    if HAS_WEBVIEW:
        if hud._start_webview():
            logger.info("HUD rodando. Janela nativa aberta. Ctrl+C para sair.")
            try:
                webview.start(debug=False)
            except Exception as e:
                logger.error(f"pywebview.start() falhou: {e}")
                logger.info(f"HUD acessivel via browser em {hud.url}")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
        else:
            logger.info(f"HUD acessivel via browser em {hud.url}")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    else:
        logger.info(f"HUD rodando em {hud.url}. Pressione Ctrl+C para sair.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    hud.stop()

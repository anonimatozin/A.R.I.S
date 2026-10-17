"""Matriz de LED 8x8 (ESP32 + MAX7219) — periférico opcional do ARIS.

Regras desta integração:
- IP nunca é hardcoded: vem de ``ARIS_FACE_MATRIX_IP`` (Settings/.env);
- falha de conexão é silenciosa (``logger.debug``) e nunca quebra o ARIS;
- nenhuma chamada de rede roda na thread principal (worker próprio).

Estados aceitos pelo sketch do ESP32 (fonte de verdade, não inventar outros):
``idle``, ``listen``, ``think``, ``speak``, ``happy``.

Endpoints do firmware:
    GET /face?state=<estado>
    GET /text?msg=<texto>
    GET /num?value=<numero>
"""

from __future__ import annotations

import queue
import random
import re
import threading
import time
import urllib.parse
import urllib.request

from utils.logger import Logger

# Estados aceitos pelo sketch do ESP32.
FACE_STATES: tuple[str, ...] = ("idle", "listen", "think", "speak", "happy")

# Estados do HUD / Event Bus (payload de "aris_status").
HUD_STATES: frozenset[str] = frozenset(
    {"idle", "listening", "thinking", "speaking", "executing"}
)

# Estado do HUD -> estado do sketch.
STATE_MAP: dict[str, str] = {
    "idle": "idle",
    "listening": "listen",
    "thinking": "think",
    "executing": "think",
    "speaking": "speak",
}

# Apelidos em portugues reconhecidos pelo comando "mostra ... na matriz".
STATE_ALIASES: dict[str, str] = {
    "idle": "idle",
    "neutro": "idle",
    "parado": "idle",
    "listen": "listen",
    "ouvindo": "listen",
    "escutando": "listen",
    "think": "think",
    "pensando": "think",
    "processando": "think",
    "speak": "speak",
    "falando": "speak",
    "happy": "happy",
    "feliz": "happy",
    "sorriso": "happy",
    "sorrindo": "happy",
}

# Limite de seguranca do texto enviado ao firmware.
_TEXT_MAX = 64
_NUMBER_RE = re.compile(r"[-+]?\d{1,6}")
_NUMBER_PHRASE_RE = re.compile(r"(?:o\s+|a\s+)?(?:n[u\u00fa]mero|valor)\s+([-+]?\d{1,6})")

_STOP = object()


class FaceMatrixClient:
    """Cliente HTTP assincrono da matriz de LED 8x8."""

    def __init__(
        self,
        ip: str = "",
        timeout: float = 1.5,
        queue_size: int = 16,
        content_hold: float = 8.0,
        happy_hold: float = 1.5,
        spontaneous_interval: float = 60.0,
        spontaneous_probability: float = 0.08,
        logger: Logger | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._ip = (ip or "").strip()
        self._timeout = timeout
        self._content_hold = content_hold
        self._happy_hold = happy_hold
        self._spontaneous_interval = spontaneous_interval
        self._spontaneous_probability = spontaneous_probability
        self._logger = logger
        self._rng = rng or random.Random()

        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._hold_timer: threading.Timer | None = None

        self._running = False
        self._closed = False
        self._last_state: str | None = None
        self._pending_state: str | None = None
        self._hold_until = 0.0
        self._hold_restore: str | None = None
        self._next_spontaneous = 0.0

    # ── Atributos ───────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self._ip)

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def last_state(self) -> str | None:
        return self._last_state

    @property
    def content_hold(self) -> float:
        return self._content_hold

    @property
    def running(self) -> bool:
        return self._running

    # ── Lifecycle ───────────────────────────────────────────

    def start(self) -> bool:
        """Inicia o worker de rede. Sem IP configurado, fica desativado."""
        if not self._ip or self._closed:
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._running = True
        self._next_spontaneous = time.monotonic() + self._spontaneous_interval
        self._thread = threading.Thread(
            target=self._run, name="face-matrix", daemon=True
        )
        self._thread.start()
        self._debug(f"conectado a {self._ip}")
        self.set_state("idle")
        return True

    def stop(self) -> None:
        """Para o worker. Nunca lanca excecao."""
        self._closed = True
        self._running = False
        with self._lock:
            if self._hold_timer is not None:
                self._hold_timer.cancel()
                self._hold_timer = None
        try:
            self._queue.put_nowait(_STOP)
        except queue.Full:
            pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None
        self._debug("desconectado")

    # ── Event Bus (mesmos eventos do HUD) ───────────────────

    def handle_event(self, event) -> None:
        """Assinante do Event Bus: ``aris_status`` e ``mic_status``."""
        try:
            event_type = getattr(event, "event_type", "")
            payload = getattr(event, "payload", None) or {}
            if event_type == "aris_status":
                self.set_state(str(payload.get("state", "")))
            elif event_type == "mic_status" and payload.get("active"):
                self.set_state("listening")
        except Exception as e:  # o bus nunca deve quebrar por causa daqui
            self._debug(f"handle_event: {e}")

    # ── Comandos ────────────────────────────────────────────

    def set_state(self, state: str, hold: float = 0.0) -> bool:
        """Muda o estado facial.

        ``hold == 0`` e uma mudanca vinda dos eventos (silenciada enquanto
        o usuario estiver vendo um conteudo pedido por comando). ``hold > 0``
        e um pedido explicito: vale por ``hold`` segundos.
        """
        if not self._ip or self._closed:
            return False
        name = STATE_MAP.get(state, state)
        if name not in FACE_STATES:
            self._debug(f"estado '{state}' desconhecido — ignorado")
            return False

        now = time.monotonic()
        if hold <= 0:
            if now < self._hold_until:
                self._pending_state = name
                return False
            if name == self._last_state:
                return True
            self._pending_state = None
            self._last_state = name
            return self._enqueue(("face", name))

        if now >= self._hold_until:
            self._hold_restore = self._last_state
        self._last_state = name
        self._hold_until = now + hold
        self._pending_state = None
        ok = self._enqueue(("face", name))
        self._arm_hold(hold)
        return ok

    def show_text(self, text: str) -> bool:
        if not self._ip or self._closed:
            return False
        value = str(text).strip()[:_TEXT_MAX]
        if not value:
            return False
        self._begin_content_hold()
        return self._enqueue(("text", value))

    def show_number(self, value) -> bool:
        if not self._ip or self._closed:
            return False
        if isinstance(value, str):
            raw = value.strip()
            if not _NUMBER_RE.fullmatch(raw):
                return False
            number = int(raw)
        else:
            try:
                number = int(value)
            except (TypeError, ValueError):
                return False
            if not -999999 <= number <= 999999:
                return False
        self._begin_content_hold()
        return self._enqueue(("number", str(number)))

    def show_content(self, content: str) -> str | None:
        """Comando humano "mostra <algo> na matriz".

        Retorna a descricao do que foi enviado (para resposta falada) ou
        ``None`` quando a matriz esta desativada / conteudo invalido.
        """
        if not self._ip or self._closed:
            return None
        text = str(content or "").strip().strip("\"'“”«»")
        if not text:
            return None
        low = text.lower()
        alias = STATE_ALIASES.get(low)
        if alias:
            return f"estado {alias}" if self.set_state(alias, hold=self._content_hold) else None
        if _NUMBER_RE.fullmatch(text):
            return f"número {text}" if self.show_number(text) else None
        phrase = _NUMBER_PHRASE_RE.fullmatch(low)
        if phrase:
            return f"número {phrase.group(1)}" if self.show_number(phrase.group(1)) else None
        sent = text[:_TEXT_MAX]
        return f"texto {sent}" if self.show_text(sent) else None

    def maybe_happy(self, probability: float = 0.06, hold: float | None = None) -> bool:
        """Mostra o ``happy`` com uma dada probabilidade (nunca em cima de conteudo)."""
        if not self._ip or self._closed:
            return False
        if time.monotonic() < self._hold_until:
            return False
        if self._rng.random() >= probability:
            return False
        return self.set_state("happy", hold=self._happy_hold if hold is None else hold)

    # ── Internos ────────────────────────────────────────────

    def _run(self) -> None:
        while self._running:
            if (
                self._spontaneous_interval > 0
                and time.monotonic() >= self._next_spontaneous
            ):
                self._next_spontaneous = time.monotonic() + self._spontaneous_interval
                if self._last_state == "idle":
                    self.maybe_happy(self._spontaneous_probability, hold=self._happy_hold)
            try:
                task = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if task is _STOP:
                break
            try:
                kind = task[0]
                if kind == "face":
                    self._request("/face", {"state": task[1]})
                elif kind == "text":
                    self._request("/text", {"msg": task[1]})
                elif kind == "number":
                    self._request("/num", {"value": task[1]})
            except Exception as e:
                self._debug(f"worker: {e}")

    def _request(self, path: str, params: dict[str, str]) -> bool:
        """GET no firmware. Falha = silencio (periferico opcional)."""
        if not self._ip:
            return False
        url = f"http://{self._ip}{path}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as response:
                response.read(256)
            return True
        except Exception as e:
            self._debug(f"{path} falhou: {e}")
            return False

    def _enqueue(self, task: tuple) -> bool:
        if self._closed:
            return False
        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()  # descarta o mais antigo
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(task)
                return True
            except queue.Full:
                return False

    def _begin_content_hold(self) -> None:
        now = time.monotonic()
        if now >= self._hold_until:
            self._hold_restore = self._last_state
        self._hold_until = max(self._hold_until, now + self._content_hold)
        self._pending_state = None
        self._arm_hold(self._hold_until - now)

    def _arm_hold(self, seconds: float) -> None:
        with self._lock:
            if self._hold_timer is not None:
                self._hold_timer.cancel()
            timer = threading.Timer(seconds, self._expire_hold)
            timer.daemon = True
            self._hold_timer = timer
        timer.start()

    def _expire_hold(self) -> None:
        if time.monotonic() < self._hold_until:
            return  # novo pedido estendeu a janela
        self._hold_until = 0.0
        target = self._pending_state or self._hold_restore or self._last_state or "idle"
        self._pending_state = None
        self._hold_restore = None
        self._last_state = target
        self._enqueue(("face", target))

    def _debug(self, message: str) -> None:
        if self._logger:
            self._logger.debug(f"FaceMatrix: {message}")

"""Backend de áudio compartilhado do A.R.I.S. (Linux-first).

Problema que resolve: no Linux/ALSA, o PortAudio não pode ser
inicializado recursamente. Antes, o ContinuousVoiceSensor e o
ClapDetector cada um abriam o SEU ``pyaudio.PyAudio()`` e o SEU stream
de mic — o segundo init falhava com ``[Errno -9971] PortAudio can not
be initialized recursively`` e o clap detector morria.

Solução: UMA única inicialização do PortAudio e UM único stream de
mic, com os frames distribuídos (broadcast) para todos os listeners
registrados. Referência-contada: o stream para quando o último listener
sai. Um ``threading.Lock`` serializa o acesso ao PyAudio.

Uso:

    from utils.audio_backend import mic

    def on_frame(data: bytes) -> None:
        ...  # consome frame 16-bit mono

    token = mic.add_listener(on_frame)   # devolve callable p/ remover
    ...
    mic.remove_listener(token)
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Optional

# Silencia o ruído de ALSA/JACK ANTES de qualquer lib de áudio.
# Em Windows/macOS é no-op. ARIS_AUDIO_DEBUG=1 desativa (p/ depuração).
try:
    import aris_audio_quiet  # noqa: F401  (import tem efeito colateral)
except ImportError:
    try:
        from utils import aris_audio_quiet  # noqa: F401
    except ImportError:
        pass

try:
    import pyaudio

    HAS_PYAUDIO = True
except ImportError:  # pragma: no cover - dependência opcional
    pyaudio = None  # type: ignore[assignment]
    HAS_PYAUDIO = False


Listener = Callable[[bytes], None]

# Lock global: serializa criação/uso do PortAudio no processo inteiro.
_PORTAUDIO_LOCK = threading.Lock()


class MicBroadcaster:
    """Um único stream de mic distribuindo frames para N listeners.

    Referência-contada: ``start()`` no primeiro listener, ``stop()`` no
    último. Todas as operações são protegidas por lock.
    """

    def __init__(self, sample_rate: int = 16000, frame_duration_ms: int = 30,
                 device_index: int = -1) -> None:
        self._sample_rate = sample_rate
        self._frame_duration_ms = frame_duration_ms
        self._device_index = device_index
        self._frame_size = int(sample_rate * frame_duration_ms / 1000)

        self._lock = threading.Lock()
        self._listeners: dict[int, Listener] = {}
        self._next_token = 0
        self._pyaudio = None
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ── Registro de listeners ──────────────────────────────

    def add_listener(self, callback: Listener) -> int:
        """Registra um consumer de frames. Devolve token p/ remover.

        Inicia o stream no primeiro listener. Se o PortAudio não estiver
        disponível, devolve token negativo e nunca chama o callback.
        """
        if not HAS_PYAUDIO:
            return -1
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._listeners[token] = callback
            should_start = not self._running and len(self._listeners) == 1
        if should_start:
            self._start_locked()
        return token

    def remove_listener(self, token: int) -> None:
        """Remove um consumer. Para o stream quando o último sai."""
        with self._lock:
            self._listeners.pop(token, None)
            should_stop = self._running and not self._listeners
        if should_stop:
            self._stop_locked()

    @property
    def listener_count(self) -> int:
        with self._lock:
            return len(self._listeners)

    @property
    def running(self) -> bool:
        return self._running

    # ── Ciclo de vida do stream (interno) ──────────────────

    def _start_locked(self) -> None:
        """Abre PyAudio + stream UMA vez. Chamado com o lock externo liberado."""
        with _PORTAUDIO_LOCK:
            try:
                self._pyaudio = pyaudio.PyAudio()
                self._stream = self._pyaudio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self._sample_rate,
                    input=True,
                    input_device_index=(
                        self._device_index if self._device_index >= 0 else None
                    ),
                    frames_per_buffer=self._frame_size,
                )
            except Exception:
                self._teardown()
                return

        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="mic-broadcast"
        )
        self._thread.start()

    def _stop_locked(self) -> None:
        """Para o stream e libera o PortAudio."""
        self._running = False
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with _PORTAUDIO_LOCK:
            self._teardown()

    def _teardown(self) -> None:
        try:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
        except Exception:
            pass
        try:
            if self._pyaudio:
                self._pyaudio.terminate()
        except Exception:
            pass
        self._stream = None
        self._pyaudio = None

    def _loop(self) -> None:
        while self._running:
            stream = self._stream
            if stream is None:
                break
            try:
                data = stream.read(self._frame_size, exception_on_overflow=False)
            except Exception:
                if self._running:
                    threading.Event().wait(0.01)
                continue
            with self._lock:
                listeners = list(self._listeners.values())
            for cb in listeners:
                try:
                    cb(data)
                except Exception:
                    pass  # um listener quebrado não derruba os demais


# Instância global compartilhada (16kHz, 30ms — padrão da A.R.I.S.).
mic = MicBroadcaster()

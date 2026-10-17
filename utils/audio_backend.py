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

Backend de captação: pyaudio (PortAudio) quando disponível; caso
contrário — ou se o pyaudio falhar ao abrir — fallback para
``arecord`` (alsa-utils) lendo o dispositivo padrão por pipe, sem
dependência nova. Sem nenhum dos dois, ``add_listener`` devolve -1 e o
micro fica indisponível (sem registration fantasma).

Uso:

    from utils.audio_backend import mic

    def on_frame(data: bytes) -> None:
        ...  # consome frame 16-bit mono

    token = mic.add_listener(on_frame)   # devolve callable p/ remover
    ...
    mic.remove_listener(token)
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable

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

# Backend alternativo quando o PortAudio não existe ou está quebrado
# (caso deste ambiente: PyAudio sem módulo C e sem libportaudio no
# sistema). O ``arecord`` (alsa-utils) lê o dispositivo padrão direto
# por pipe — comprovado funcionando com sinal real (RMS > 0).
_ARECORD = shutil.which("arecord")
HAS_CAPTURE = HAS_PYAUDIO or bool(_ARECORD)


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
        self._proc: subprocess.Popen | None = None  # arecord (fallback)
        self._thread: threading.Thread | None = None
        self._running = False

    # ── Registro de listeners ──────────────────────────────

    def add_listener(self, callback: Listener) -> int:
        """Registra um consumer de frames. Devolve token p/ remover.

        Inicia a captação no primeiro listener. Se não houver NENHUM
        backend (sem PortAudio e sem arecord), devolve token negativo e
        nunca chama o callback. Se o backend existir mas o micro não
        abrir, também devolve -1 (não deixa registration fantasma).
        """
        if not HAS_CAPTURE:
            return -1
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._listeners[token] = callback
            should_start = not self._running and len(self._listeners) == 1
        if should_start:
            self._start_locked()
        if not self._running:
            # Falhou ao abrir o mic: desregistra e sinaliza indisponível.
            with self._lock:
                self._listeners.pop(token, None)
            return -1
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
        """Abre o backend de captação UMA vez. Chamado com o lock externo liberado."""
        if HAS_PYAUDIO:
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
                    self._teardown()  # pyaudio falhou → tenta arecord abaixo
        if self._stream is None:
            # Sem PortAudio (ou ele falhou): captação via arecord.
            if not self._spawn_arecord():
                self._teardown()
                return

        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="mic-broadcast"
        )
        self._thread.start()

    def _spawn_arecord(self) -> bool:
        """Sobe o ``arecord`` capturando o dispositivo ALSA padrão (raw s16le).

        Devolve False se o binário não existe ou o processo morreu na
        hora (micro ocupado/inexistente). O loop trata EOF posterior
        como queda do dispositivo e chama isto de novo (backoff 2s).
        """
        if not _ARECORD:
            return False
        try:
            proc = subprocess.Popen(
                [
                    _ARECORD, "-q",
                    "-f", "S16_LE",
                    "-r", str(self._sample_rate),
                    "-c", "1",
                    "-t", "raw",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return False
        if proc.poll() is not None:  # morreu na hora: device ocupado
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
            return False
        self._proc = proc
        return True

    def _close_arecord(self) -> None:
        """Encerra o arecord atual (se houver) e libera o pipe."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass

    def _stop_locked(self) -> None:
        """Para o stream e libera o backend (PortAudio e/ou arecord)."""
        self._running = False
        thread = self._thread
        # 3.0s: o loop do arecord pode estar no backoff de 2s (device
        # sumiu) antes de conferir _running e sair.
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
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
        self._close_arecord()

    def _loop(self) -> None:
        frame_bytes = self._frame_size * 2  # s16le mono
        while self._running:
            stream = self._stream
            proc = self._proc
            if stream is None and proc is None:
                break
            try:
                if stream is not None:
                    data = stream.read(self._frame_size, exception_on_overflow=False)
                else:
                    data = proc.stdout.read(frame_bytes)
            except Exception:
                if self._running:
                    threading.Event().wait(0.01)
                continue
            if not data:
                # EOF do arecord: dispositivo sumiu/ocupado → renasce.
                self._close_arecord()
                if not self._running:
                    break
                if not self._spawn_arecord():
                    threading.Event().wait(2.0)
                elif not self._running:
                    self._close_arecord()  # parou entre spawn e checagem
                continue
            if len(data) < frame_bytes:  # leitura parcial: completa com silêncio
                data += b"\x00" * (frame_bytes - len(data))
            with self._lock:
                listeners = list(self._listeners.values())
            for cb in listeners:
                try:
                    cb(data)
                except Exception:
                    pass  # um listener quebrado não derruba os demais


# Instância global compartilhada (16kHz, 30ms — padrão da A.R.I.S.).
mic = MicBroadcaster()

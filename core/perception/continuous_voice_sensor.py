"""Sensor de voz contínua do A.R.I.S.

Escuta ativa com VAD + wake word ("aris" em qualquer posição) + STT leve.
Injeta comandos no _input_queue via Aris.send_message().

Não duplica o STT existente (HybridVoice.listen) — este é para escuta
CONTÍNUA em background, enquanto o HybridVoice.listen() é sob demanda.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

try:
    import webrtcvad
    HAS_VAD = True
except ImportError:
    HAS_VAD = False
    webrtcvad = None  # type: ignore

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False
    pyaudio = None  # type: ignore

try:
    import faster_whisper
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False
    faster_whisper = None  # type: ignore

try:
    from vosk import Model as VoskModel, KaldiRecognizer
    HAS_VOSK = True
except ImportError:
    HAS_VOSK = False

from core.neural.events import Event, PRIORITY_NORMAL
from core.perception.sensor import Sensor, STATUS_DISABLED
from utils.logger import Logger


logger = logging.getLogger(__name__)


# ─── Configuração ───

@dataclass(frozen=True)
class ContinuousVoiceConfig:
    """Configuração do sensor de voz contínua."""
    enabled: bool = False
    wake_words: tuple[str, ...] = ("aris", "arís", "ariz", "arizs")
    vad_aggressiveness: int = 2          # 0-3 (3 = mais agressivo)
    sample_rate: int = 16000
    frame_duration_ms: int = 30          # 10, 20 ou 30ms (webrtcvad)
    silence_timeout_ms: int = 1200       # ms de silêncio p/ finalizar utterancia
    min_speech_ms: int = 800             # ms mínimos p/ considerar fala válida (ignora ruído inicial)
    max_speech_ms: int = 30000           # ms máximos de fala contínua
    warmup_frames: int = 10              # frames iniciais a ignorar (aquecimento do stream ~300ms)
    energy_threshold: float = 750.0      # threshold de energia RMS p/ VAD fallback (sem webrtcvad)
    device_index: int = -1               # índice do microfone (-1 = padrão do sistema)
    stt_model: str = "tiny"              # tiny, base, small (faster-whisper)
    stt_device: str = "cpu"              # cpu ou cuda
    stt_compute_type: str = "int8"       # int8, int16, float16
    vosk_model_path: str = "vosk-model-pt"  # modelo Vosk offline
    language: str = "pt"
    min_confidence: float = 0.35         # threshold mínimo p/ aceitar STT
    cooldown_ms: int = 1000              # cooldown entre wake words


# ─── Sensor ───

class ContinuousVoiceSensor:
    """Sensor de voz contínua com VAD + Wake Word + STT leve.

    Fluxo:
    1. Captura áudio contínuo via PyAudio (16kHz, 16-bit, mono)
    2. VAD (webrtcvad) detecta segmentos de fala
    3. Acumula frames de fala até silêncio > silence_timeout_ms
    4. STT (faster-whisper ou Vosk) transcreve
    5. Se wake word detectada em QUALQUER posição -> injeta no _input_queue
    6. Emite evento EVENT_VOICE_COMMAND no Event Bus
    """

    name = "continuous_voice"

    def __init__(
        self,
        send_message_fn: Callable[[str, Any], None],
        event_bus=None,
        config: Optional[ContinuousVoiceConfig] = None,
        logger: Optional[Logger] = None,
    ) -> None:
        self._send_message = send_message_fn
        self._event_bus = event_bus
        self._config = config or ContinuousVoiceConfig()
        self._logger = logger or logging.getLogger(__name__)

        # Estado
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stt_thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._stt_queue: queue.Queue[bytes] = queue.Queue(maxsize=50)
        self._stop_event = threading.Event()

        # VAD
        self._vad = None
        if HAS_VAD:
            self._vad = webrtcvad.Vad(self._config.vad_aggressiveness)

        # Áudio
        self._pyaudio = None
        self._stream = None
        self._mic_token: Optional[int] = None  # vaga no mic compartilhado
        self._sample_rate = self._config.sample_rate
        self._frame_size = int(self._sample_rate * self._config.frame_duration_ms / 1000)
        self._bytes_per_frame = self._frame_size * 2  # 16-bit = 2 bytes

        # STT
        self._stt_model = None
        self._vosk_recognizer = None
        self._stt_ready = threading.Event()

        # Buffer de fala
        self._speech_buffer: list[bytes] = []
        self._in_speech = False
        self._silence_frames = 0
        self._speech_frames = 0
        self._last_wake_time = 0.0
        self._frame_count = 0  # total frames processados (para warmup)
        self._running_transcript = ""  # transcript running during speech

        # Wake words (normalizados)
        self._wake_words = tuple(w.lower() for w in self._config.wake_words)

        # Flag: wake word foi detectado no segmento atual de fala
        # Quando verdadeiro, o loop continua acumulando áudio em vez de resetar o buffer
        self._wake_word_in_speech = False

        # Callbacks
        self._on_transcript: Optional[Callable[[str], None]] = None

    # ─── Propriedades ───

    @property
    def available(self) -> bool:
        return HAS_PYAUDIO and (HAS_FASTER_WHISPER or HAS_VOSK)

    @property
    def enabled(self) -> bool:
        return self._config.enabled and self.available

    def set_enabled(self, enabled: bool) -> None:
        object.__setattr__(self._config, "enabled", enabled)
        if enabled and not self._running:
            self.start()
        elif not enabled and self._running:
            self.stop()

    # ─── Inicialização STT ───

    def _init_stt(self) -> None:
        """Inicializa modelo STT (faster-whisper ou Vosk)."""
        if HAS_FASTER_WHISPER:
            try:
                self._logger.info(f"Carregando faster-whisper ({self._config.stt_model})...")
                self._stt_model = faster_whisper.WhisperModel(
                    self._config.stt_model,
                    device=self._config.stt_device,
                    compute_type=self._config.stt_compute_type,
                )
                self._logger.info("faster-whisper carregado com sucesso")
                self._stt_ready.set()
                return
            except Exception as e:
                self._logger.warning(f"Falha ao carregar faster-whisper: {e}")

        if HAS_VOSK:
            try:
                self._logger.info(f"Carregando Vosk ({self._config.vosk_model_path})...")
                model = VoskModel(self._config.vosk_model_path)
                self._vosk_recognizer = KaldiRecognizer(model, self._config.sample_rate)
                self._logger.info("Vosk carregado com sucesso")
                self._stt_ready.set()
                return
            except Exception as e:
                self._logger.warning(f"Falha ao carregar Vosk: {e}")

        self._logger.error("Nenhum modelo STT disponível (instale faster-whisper ou vosk)")
        self._stt_ready.set()

    # ─── Ciclo de vida ───

    def start(self) -> None:
        if not self.enabled:
            self._logger.warning("Sensor desabilitado ou dependências faltando")
            return
        if self._running:
            return

        self._logger.info("Iniciando sensor de voz contínua...")
        self._init_stt()
        if not self._stt_ready.wait(timeout=30):
            self._logger.error("Timeout ao carregar modelo STT")
            return

        self._stop_event.clear()
        self._running = True
        self._frame_count = 0  # reset warmup counter

        # Thread de captura de áudio
        self._thread = threading.Thread(target=self._audio_loop, daemon=True, name="voice-capture")
        self._thread.start()

        # Thread de STT
        self._stt_thread = threading.Thread(target=self._stt_loop, daemon=True, name="voice-stt")
        self._stt_thread.start()

        self._logger.info("Sensor de voz contínua ativo")

    def stop(self) -> None:
        if not self._running:
            return
        self._logger.info("Parando sensor de voz contínua...")
        self._running = False
        self._stop_event.set()

        # Sinalizar fim para filas
        try:
            self._audio_queue.put_nowait(b"")
        except queue.Full:
            pass
        try:
            self._stt_queue.put_nowait(b"")
        except queue.Full:
            pass

        if self._thread:
            self._thread.join(timeout=2)
        if self._stt_thread:
            self._stt_thread.join(timeout=2)

        if self._mic_token is not None:
            try:
                from utils.audio_backend import mic

                mic.remove_listener(self._mic_token)
            except Exception:
                pass
            self._mic_token = None

        self._logger.info("Sensor de voz contínua parado")

    # ─── Captura de áudio ───

    def _on_mic_frame(self, data: bytes) -> None:
        """Callback do mic compartilhado: enfileira o frame para o VAD/STT."""
        if not self._audio_queue.full():
            self._audio_queue.put_nowait(data)

    def _audio_loop(self) -> None:
        """Consume o mic compartilhado (MicBroadcaster).

        Antes abria o SEU ``pyaudio.PyAudio()``/stream — no Linux isso
        conflitava com o ClapDetector ("PortAudio can not be initialized
        recursively"). Agora há UMA única inicialização do PortAudio e um
        único stream, distribuído a todos os listeners.
        """
        from utils.audio_backend import mic

        token = mic.add_listener(self._on_mic_frame)
        if token < 0:
            self._logger.error("Mic compartilhado indisponível (PyAudio ausente)")
            return
        self._mic_token = token
        self._logger.debug("Stream de áudio iniciado (mic compartilhado)")

        # Mantém a thread viva enquanto houver listener; o frames chegam
        # via callback. Aguarda o stop_event.
        self._stop_event.wait()

    # ─── STT Loop ───

    def _stt_loop(self) -> None:
        """Loop de processamento STT + VAD + Wake Word (thread separada)."""
        frames_per_second = 1000 // self._config.frame_duration_ms
        silence_limit = max(1, self._config.silence_timeout_ms // self._config.frame_duration_ms)
        min_speech_frames = max(1, self._config.min_speech_ms // self._config.frame_duration_ms)
        max_speech_frames = max(1, self._config.max_speech_ms // self._config.frame_duration_ms)
        warmup_frames = getattr(self._config, "warmup_frames", 5)

        self._logger.debug(f"STT loop iniciado (silence_limit={silence_limit}, min_speech={min_speech_frames}, warmup={warmup_frames})")
        self._logger.info(f"Voz contínua ativa — escutando por wake words: {self._wake_words}")

        while self._running and not self._stop_event.is_set():
            try:
                # Aguardar frame de áudio
                frame = self._audio_queue.get(timeout=0.1)
                if not frame:  # sinal de parada
                    break

                # Warmup: ignorar primeiros frames (ruído de inicialização do stream)
                self._frame_count += 1
                if self._frame_count <= warmup_frames:
                    continue

                # VAD
                is_speech = self._is_speech(frame)

                if is_speech:
                    # Fala detectada
                    if not self._in_speech:
                        self._in_speech = True
                        self._speech_buffer = []
                        self._speech_frames = 0
                        self._silence_frames = 0
                        self._logger.debug("Início de fala detectado")
                        self._publish_aris_status("listening")

                    self._speech_buffer.append(frame)
                    self._speech_frames += 1
                    self._silence_frames = 0
                    # Se wake word já foi detectado neste segmento, continuar acumulando
                    # não reseta o buffer por causa de silêncio breve
                    if self._wake_word_in_speech:
                        # Reset silence counter when wake word was already detected
                        # e continuamos ouvindo o restante do comando
                        self._silence_frames = 0

                    # Limite máximo de fala contínua
                    if self._speech_frames >= max_speech_frames:
                        self._logger.debug(f"Limite máximo de fala atingido ({max_speech_frames} frames)")
                        delivered = self._process_speech_buffer()
                        waiting_for_command = self._wake_word_in_speech
                        self._in_speech = False
                        self._speech_buffer = []
                        self._speech_frames = 0
                        self._wake_word_in_speech = False
                        if not delivered and not waiting_for_command:
                            self._publish_aris_status("idle")

                else:
                    # Silêncio
                    if self._in_speech:
                        # Se wake word já foi detectado, exigir silêncio maior p/ finalizar
                        # (1.5s em vez de 1.2s para capturar o restante do comando)
                        effective_silence_limit = (
                            self._config.silence_timeout_ms
                            if not self._wake_word_in_speech
                            else int(self._config.silence_timeout_ms * 1.25)
                        )
                        self._silence_frames += 1
                        self._speech_buffer.append(frame)  # manter silêncio final

                        if self._silence_frames >= effective_silence_limit:
                            # Fim da utterancia
                            delivered = False
                            if self._speech_frames >= min_speech_frames:
                                self._logger.debug(f"Fim de fala detectado ({self._speech_frames} frames de fala)")
                                delivered = self._process_speech_buffer()
                            else:
                                self._logger.debug(f"Fala muito curta ignorada ({self._speech_frames} frames)")
                            waiting_for_command = self._wake_word_in_speech
                            self._in_speech = False
                            self._speech_buffer = []
                            self._speech_frames = 0
                            self._silence_frames = 0
                            # Reset wake word flag ao finalizar utterancia
                            self._wake_word_in_speech = False
                            if not delivered and not waiting_for_command:
                                self._publish_aris_status("idle")

            except queue.Empty:
                continue
            except Exception as e:
                if self._running:
                    self._logger.debug(f"Erro no STT loop: {e}")

    def _is_speech(self, frame: bytes) -> bool:
        """VAD via webrtcvad."""
        if not self._vad or len(frame) != self._bytes_per_frame:
            # Fallback simples: energia RMS
            if HAS_NUMPY:
                audio = np.frombuffer(frame, dtype=np.int16)
                energy = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
                return energy > self._config.energy_threshold
            return True  # assume fala se não tem VAD
        return self._vad.is_speech(frame, self._config.sample_rate)

    def _process_speech_buffer(self) -> bool:
        """Processa buffer de fala acumulado via STT.

        Returns:
            True quando o comando foi entregue ao ARIS (wake word válida).
        """
        if not self._speech_buffer:
            return False

        # Concatenar frames
        audio_data = b"".join(self._speech_buffer)
        duration_ms = len(audio_data) / (self._config.sample_rate * 2) * 1000
        self._logger.debug(f"Processando buffer: {len(audio_data)} bytes = {duration_ms:.0f}ms")
        self._speech_buffer = []

        # Verificar wake word ANTES de emitir - para poder continuar ouvindo
        transcript = self._transcribe(audio_data) or ""
        woke_up = any(wake in transcript.lower() for wake in self._wake_words)

        delivered = False
        try:
            if transcript:
                self._logger.debug(f"Transcrito: '{transcript}'")
                # Se detectou wake word, marcar para continuar ouvindo
                if woke_up:
                    self._wake_word_in_speech = True
                    self._logger.info(f"Wake word detectada no buffer - continuando captura do comando")
                delivered = bool(self._on_transcript_result(transcript))
            else:
                self._logger.debug("STT retornou vazio")
                # Mesmo sem transcript, se houver fala, marcar check
                if self._speech_frames > 0:
                    self._wake_word_in_speech = False
        except Exception as e:
            self._logger.debug(f"Erro na transcrição: {e}")
            self._wake_word_in_speech = False
        return delivered

    def _publish_aris_status(self, state: str) -> None:
        """Publica ``aris_status`` (mesmo evento consumido pelo HUD e pela matriz)."""
        if not self._event_bus:
            return
        try:
            self._event_bus.publish(Event(
                event_type="aris_status",
                source="continuous_voice",
                payload={"state": state},
                priority=70,
                confidence=1.0,
            ))
        except Exception as e:
            self._logger.debug(f"Falha ao publicar aris_status: {e}")

    def _transcribe(self, audio_data: bytes) -> Optional[str]:
        """Transcreve áudio via faster-whisper ou Vosk."""
        if not audio_data:
            return None

        # faster-whisper
        if self._stt_model:
            try:
                import io
                import numpy as np

                # Converter para float32 numpy array
                audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

                segments, info = self._stt_model.transcribe(
                    audio_np,
                    language=self._config.language,
                    beam_size=1,
                    best_of=1,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    compression_ratio_threshold=2.4,
                    log_prob_threshold=-1.0,
                    no_speech_threshold=0.6,
                )

                text = " ".join(seg.text for seg in segments).strip()
                if text and info.language_probability > 0.5:
                    self._logger.debug(f"STT (faster-whisper): '{text}' (lang_prob={info.language_probability:.2f})")
                    return text
            except Exception as e:
                self._logger.debug(f"Erro faster-whisper: {e}")

        # Vosk fallback
        if self._vosk_recognizer:
            try:
                if self._vosk_recognizer.AcceptWaveform(audio_data):
                    import json
                    result = json.loads(self._vosk_recognizer.Result())
                    text = result.get("text", "").strip()
                    if text:
                        self._logger.debug(f"STT (Vosk): '{text}'")
                        return text
                else:
                    # Partial result
                    import json
                    result = json.loads(self._vosk_recognizer.PartialResult())
                    return result.get("partial", "").strip()
            except Exception as e:
                self._logger.debug(f"Erro Vosk: {e}")

        return None

    def _on_transcript_result(self, transcript: str) -> bool:
        """Processa transcrição: wake word + injeção no _input_queue.

        Returns:
            True quando o comando foi entregue ao ARIS.
        """
        if not transcript:
            return False

        transcript_lower = transcript.lower().strip()
        self._logger.debug(f"Transcrição: '{transcript}'")

        # Verificar wake word em QUALQUER posição
        wake_detected = any(wake in transcript_lower for wake in self._wake_words)

        now = time.time()
        if wake_detected:
            # Cooldown entre wake words
            if now - self._last_wake_time < self._config.cooldown_ms / 1000:
                self._logger.debug("Wake word em cooldown, ignorando")
                self._wake_word_in_speech = False
                self._publish_aris_status("idle")
                return False

            self._last_wake_time = time.time()

            # Injetar no _input_queue via callback
            self._logger.info(f"Wake word detectada: '{transcript}'")
            self._send_message(transcript, None)  # origin será preenchido pelo Aris

            # Emitir evento no Event Bus
            if self._event_bus:
                from core.neural.events import EVENT_VOICE_COMMAND, PRIORITY_NORMAL
                event = Event(
                    event_type="voice_command",
                    source="continuous_voice",
                    payload={"transcript": transcript, "wake_word": True},
                    priority=80,
                    confidence=0.9,
                )
                self._event_bus.publish(event)

            # Callback opcional
            if self._on_transcript:
                try:
                    self._on_transcript(transcript)
                except Exception:
                    pass

            # Disparar sugestão proativa (se aplicável)
            self._maybe_proactive(transcript)
            return True

        return False

    def _maybe_proactive(self, transcript: str) -> None:
        """Dispara sugestão proativa via EVENT_FOLLOWUP_SUGGESTION."""
        if not self._event_bus:
            return

        # Heurísticas simples p/ oferta proativa
        t = transcript.lower()

        # Palavras que indicam dificuldade/necessidade
        difficulty_markers = (
            "não sei", "não consigo", "como faço", "como que faz",
            "ajuda", "socorro", "travou", "erro", "não funciona",
            "não entendi", "não entendo", "dúvida", "duvida",
        )

        if any(marker in transcript.lower() for marker in difficulty_markers):
            self._event_bus.publish(
                Event(
                    event_type="followup.suggestion",
                    source="continuous_voice",
                    payload={
                        "trigger": "difficulty_detected",
                        "transcript": transcript,
                        "suggestion": "Posso ajudar com isso? Quer que eu explique ou faça por você?",
                    },
                    priority=60,
                    confidence=0.7,
                ))

    # ─── Callbacks ───

    def set_transcript_callback(self, callback: Callable[[str], None]) -> None:
        self._on_transcript = callback

    # ─── Sensor interface ───

    def sense(self) -> list:
        return []

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "enabled": self.enabled,
            "available": self.available,
            "stt_ready": self._stt_ready.is_set(),
            "in_speech": self._in_speech,
            "wake_words": self._wake_words,
        }


# ─── Integração com Aris (função helper) ───

def build_continuous_voice_sensor(
    aris_instance,
    config: Optional[ContinuousVoiceConfig] = None,
) -> Optional[ContinuousVoiceSensor]:
    """Constrói o sensor de voz contínua integrado ao Aris."""
    from utils.logger import Logger

    logger = Logger(name="continuous_voice", log_dir="logs", level="INFO")

    def send_message_wrapper(text: str, origin=None):
        """Wrapper para Aris.send_message()."""
        from core.message_origin import MessageOrigin
        if origin is None:
            origin = MessageOrigin(source="voice", channel="continuous", user_id="local")
        aris_instance.send_message(text, origin)

    sensor = ContinuousVoiceSensor(
        send_message_fn=send_message_wrapper,
        event_bus=aris_instance._neural.event_bus if hasattr(aris_instance, "_neural") else None,
        config=config,
        logger=logger,
    )

    return sensor
"""Sensor de microfone do A.R.I.S.

Não abre um segundo leitor de áudio (o ARIS já possui o loop de voz).
Este sensor apenas REUTILIZA os eventos de voz existentes que trafegam
no Event Bus (``voice_command``, ``user_message``), atualizando o
estado de fala e, opcionalmente, re-emitindo um evento leve de
percepção (``mic_relay``) — sem duplicar STT/ASR.

Sem microfone disponível ou com ``mic_enabled=False``, fica ``offline``/
``disabled`` e emite zero eventos.
"""

from __future__ import annotations

from typing import Any

try:
    import speech_recognition as sr  # type: ignore[import-untyped]

    HAS_SR = True
except ImportError:
    sr = None  # type: ignore[assignment]
    HAS_SR = False

from core.neural.events import (
    EVENT_MICROPHONE,
    EVENT_USER_MESSAGE,
    EVENT_VOICE_COMMAND,
    PRIORITY_NORMAL,
    Event,
)
from core.perception.sensor import STATUS_DISABLED, Sensor
from utils.logger import Logger

# Eventos que indicam que uma pessoa falou (autoritativos).
_VOICE_EVENT_TYPES = frozenset({EVENT_VOICE_COMMAND, EVENT_USER_MESSAGE})


class MicrophoneSensor(Sensor):
    """Sensor passivo de voz: observa o barramento, não captura áudio."""

    name = "microphone"

    def __init__(
        self,
        event_bus=None,
        enabled: bool = False,
        interval: float = 2.0,
        logger: Logger | None = None,
        relay: bool = False,
    ) -> None:
        super().__init__(event_bus=event_bus, enabled=enabled, interval=interval, logger=logger)
        self._relay = bool(relay)
        self._speaking = False
        self._last_transcript = ""
        self._speech_count = 0

    @property
    def available(self) -> bool:
        return HAS_SR

    def start(self) -> None:
        if not self._enabled:
            self._status = STATUS_DISABLED
            return
        super().start()
        self._subscribe_voice()

    def stop(self) -> None:
        self._unsubscribe_voice()
        super().stop()

    def _subscribe_voice(self) -> None:
        if self.event_bus is None:
            return
        for event_type in _VOICE_EVENT_TYPES:
            self.event_bus.subscribe(event_type, self._on_voice_event)

    def _unsubscribe_voice(self) -> None:
        if self.event_bus is None:
            return
        for event_type in _VOICE_EVENT_TYPES:
            self.event_bus.unsubscribe(event_type, self._on_voice_event)

    def _on_voice_event(self, event: Event) -> None:
        """Atualiza o estado de fala a partir de eventos de voz reais."""
        self._speaking = True
        self._speech_count += 1
        transcript = event.text or event.payload.get("transcript", "")
        if transcript:
            self._last_transcript = str(transcript)
        if self._relay:
            self._publish([self._make_event(
                EVENT_MICROPHONE,
                {"detection": "speech", "confidence": event.confidence,
                 "text": f"Fala detectada: {self._last_transcript or 'voz'}"},
                priority=PRIORITY_NORMAL,
                confidence=float(event.confidence or 0.6),
            )])

    def sense(self) -> list[Event]:
        return []

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data.update({
            "speaking": self._speaking,
            "last_transcript": self._last_transcript,
            "speech_count": self._speech_count,
        })
        return data

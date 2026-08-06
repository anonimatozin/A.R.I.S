"""Sistema de voz do J.A.R.V.I.S.

Utiliza o Windows SAPI (Speech API) para síntese de voz.
"""

import threading
from typing import Optional

try:
    import win32com.client
    _SAPI_AVAILABLE = True
except ImportError:
    _SAPI_AVAILABLE = False


class Voice:
    """Gerenciador de síntese de voz.

    Args:
        rate: Velocidade da fala (-10 a 10). Padrão: 0.
        volume: Volume da fala (0 a 100). Padrão: 100.
        voice_id: ID da voz (None para padrão do sistema).
    """

    def __init__(
        self,
        rate: int = 0,
        volume: int = 100,
        voice_id: Optional[int] = None,
    ) -> None:
        self._rate = max(-10, min(10, rate))
        self._volume = max(0, min(100, volume))
        self._voice_id = voice_id
        self._speaker = None
        self._enabled = _SAPI_AVAILABLE
        self._lock = threading.Lock()

        if self._enabled:
            self._init_speaker()

    def _init_speaker(self) -> None:
        """Inicializa o objeto SAPI."""
        try:
            self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
            self._speaker.Rate = self._rate
            self._speaker.Volume = self._volume

            if self._voice_id is not None:
                voices = self._speaker.GetVoices()
                if 0 <= self._voice_id < voices.Count:
                    self._speaker.Voice = voices.Item(self._voice_id)
        except Exception:
            self._enabled = False
            self._speaker = None

    @property
    def enabled(self) -> bool:
        """Verifica se a voz está disponível."""
        return self._enabled

    @property
    def rate(self) -> int:
        """Velocidade da fala."""
        return self._rate

    @rate.setter
    def rate(self, value: int) -> None:
        self._rate = max(-10, min(10, value))
        if self._speaker:
            self._speaker.Rate = self._rate

    @property
    def volume(self) -> int:
        """Volume da fala."""
        return self._volume

    @volume.setter
    def volume(self, value: int) -> None:
        self._volume = max(0, min(100, value))
        if self._speaker:
            self._speaker.Volume = self._volume

    def speak(self, text: str, async_mode: bool = True) -> None:
        """Fala um texto.

        Args:
            text: Texto para falar.
            async_mode: Se True, fala em thread separada (não bloqueia).
        """
        if not self._enabled or not self._speaker or not text:
            return

        if async_mode:
            thread = threading.Thread(target=self._speak_sync, args=(text,), daemon=True)
            thread.start()
        else:
            self._speak_sync(text)

    def _speak_sync(self, text: str) -> None:
        """Fala um texto de forma síncrona (thread-safe)."""
        with self._lock:
            try:
                self._speaker.Speak(text)
            except Exception:
                pass

    def stop(self) -> None:
        """Para a fala atual."""
        if self._speaker:
            try:
                self._speaker.Speak("", 2)  # SVSFlagsAsync = 2, purge
            except Exception:
                pass

    def list_voices(self) -> list[str]:
        """Lista as vozes disponíveis no sistema.

        Returns:
            Lista com os nomes das vozes.
        """
        if not self._enabled or not self._speaker:
            return []

        voices = []
        try:
            for voice in self._speaker.GetVoices():
                voices.append(voice.GetDescription())
        except Exception:
            pass
        return voices

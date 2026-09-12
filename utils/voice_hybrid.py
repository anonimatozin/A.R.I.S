"""Sistema de voz híbrido do A.R.I.S.

Suporta múltiplos engines de TTS:
- edge-tts (online, alta qualidade, PT-BR)
- pyttsx3 (offline, nativo)
- Windows SAPI (fallback nativo)

Suporta STT (Speech-to-Text) via:
- speech_recognition (online/offline)
"""

import asyncio
import threading
import tempfile
import os
from typing import Optional
from pathlib import Path

try:
    import pyttsx3
    _PYTTSX3_AVAILABLE = True
except ImportError:
    _PYTTSX3_AVAILABLE = False

try:
    import speech_recognition as sr
    _SR_AVAILABLE = True
except ImportError:
    _SR_AVAILABLE = False

try:
    import edge_tts
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False


class HybridVoice:
    """Gerenciador de voz híbrido (TTS + STT).

    Tenta usar edge-tts (online) primeiro, depois pyttsx3 (offline).
    """

    def __init__(
        self,
        rate: int = 0,
        volume: int = 100,
        language: str = "pt-BR",
    ):
        self._rate = rate
        self._volume = volume
        self._language = language
        self._enabled = False
        self._tts_engine = None
        self._lock = threading.Lock()
        self._recognizer = None

        self._init_tts()
        self._init_stt()

    def _init_tts(self) -> None:
        """Inicializa o melhor engine TTS disponível."""
        if _EDGE_TTS_AVAILABLE:
            self._tts_engine = "edge-tts"
            self._enabled = True
            return

        if _PYTTSX3_AVAILABLE:
            try:
                self._tts_engine = pyttsx3.init()
                self._tts_engine.setProperty("rate", 200 + self._rate * 20)
                self._tts_engine.setProperty("volume", self._volume / 100)
                self._enabled = True
                return
            except Exception:
                pass

        self._tts_engine = None
        self._enabled = False

    def _init_stt(self) -> None:
        """Inicializa o engine STT."""
        if _SR_AVAILABLE:
            self._recognizer = sr.Recognizer()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def engine_name(self) -> str:
        if isinstance(self._tts_engine, str):
            return self._tts_engine
        return "pyttsx3" if self._tts_engine else "nenhum"

    def speak(self, text: str, async_mode: bool = True) -> None:
        """Fala um texto usando o melhor engine disponível."""
        if not self._enabled or not text:
            return

        if async_mode:
            thread = threading.Thread(target=self._speak_sync, args=(text,), daemon=True)
            thread.start()
        else:
            self._speak_sync(text)

    def _speak_sync(self, text: str) -> None:
        """Fala de forma síncrona."""
        with self._lock:
            try:
                if self._tts_engine == "edge-tts":
                    self._speak_edge(text)
                elif self._tts_engine and hasattr(self._tts_engine, "say"):
                    self._tts_engine.say(text)
                    self._tts_engine.runAndWait()
            except Exception:
                pass

    def _speak_edge(self, text: str) -> None:
        """Fala usando edge-tts (online, alta qualidade)."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._edge_tts_speak(text))
            loop.close()
        except Exception:
            # Fallback para pyttsx3
            if _PYTTSX3_AVAILABLE:
                try:
                    engine = pyttsx3.init()
                    engine.say(text)
                    engine.runAndWait()
                except Exception:
                    pass

    async def _edge_tts_speak(self, text: str) -> None:
        """Gera áudio via edge-tts e reproduz."""
        voice = "pt-BR-FranciscaNeural"
        tmp_file = os.path.join(tempfile.gettempdir(), "aris_speech.mp3")

        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(tmp_file)

        # Reproduzir com pygame ou mciSendString
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(tmp_file)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
        except ImportError:
            # Fallback: usar Windows MCI
            try:
                import ctypes
                ctypes.windll.winmm.mciSendStringW(
                    f'open "{tmp_file}" type mpegvideo alias aris_speak', None, 0, None
                )
                ctypes.windll.winmm.mciSendStringW("play aris_speak", None, 0, None)
                import time
                time.sleep(3)
                ctypes.windll.winmm.mciSendStringW("close aris_speak", None, 0, None)
            except Exception:
                pass

        # Limpar arquivo temporário
        try:
            os.remove(tmp_file)
        except Exception:
            pass

    def listen(self, timeout: int = 5, language: str = "pt-BR") -> Optional[str]:
        """Escuta áudio do microfone e converte em texto.

        Args:
            timeout: Timeout em segundos.
            language: Código do idioma.

        Returns:
            Texto reconhecido ou None.
        """
        if not self._recognizer or not _SR_AVAILABLE:
            return None

        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(source, timeout=timeout)

            # Tentar Google (gratuito)
            text = self._recognizer.recognize_google(audio, language=language)
            return text

        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            # Fallback: tentar offline com Vosk se disponível
            return self._listen_offline(audio)
        except Exception:
            return None

    def _listen_offline(self, audio) -> Optional[str]:
        """Reconhecimento offline via Vosk."""
        try:
            from vosk import Model, KaldiRecognizer
            import wave
            import json

            model = Model("vosk-model-pt")
            rec = KaldiRecognizer(model, 16000)

            # Converter audio para WAV
            wav_data = audio.get_wav_data()
            if rec.AcceptWaveform(wav_data):
                result = json.loads(rec.Result())
                return result.get("text", "")
        except Exception:
            pass
        return None

    def stop(self) -> None:
        """Para a fala atual."""
        if self._tts_engine == "edge-tts":
            try:
                import pygame
                pygame.mixer.music.stop()
            except Exception:
                pass
        elif self._tts_engine and hasattr(self._tts_engine, "stop"):
            try:
                self._tts_engine.stop()
            except Exception:
                pass

    def list_voices(self) -> list[str]:
        """Lista vozes disponíveis."""
        if self._tts_engine == "edge-tts":
            return ["pt-BR-FranciscaNeural (Edge TTS)", "pt-BR-AntonioNeural (Edge TTS)"]
        elif self._tts_engine and hasattr(self._tts_engine, "getProperty"):
            try:
                voices = self._tts_engine.getProperty("voices")
                return [v.name for v in voices]
            except Exception:
                pass
        return []

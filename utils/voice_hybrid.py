"""Sistema de voz híbrido do A.R.I.S.

Suporta múltiplos engines de TTS:
- edge-tts (online, alta qualidade, PT-BR)
- pyttsx3 (offline, nativo)
- Windows SAPI (fallback nativo)

Suporta STT (Speech-to-Text) via:
- speech_recognition (online/offline)

Seleção automática de microfone por SNR via MicSelector.
"""

import asyncio
import os
import re
import tempfile
import threading
import time
import uuid
from typing import Optional

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

try:
    from utils.mic_selector import MicSelector
    _MIC_SELECTOR_AVAILABLE = True
except ImportError:
    MicSelector = None  # type: ignore[assignment]
    _MIC_SELECTOR_AVAILABLE = False

# Lock global: todas as instâncias de HybridVoice falam em sequência
# (impede áudio duplicado, ex.: voz pt-BR + fallback lendo o mesmo texto).
_SPEECH_LOCK = threading.Lock()

_PT_VOICE_MARKERS = ("pt-", "ptbr", "portugu", "brazil", "brasil", "maria",
                     "francisca", "antonio", "thalita", "joana")


def _env_int(key: str, default: int) -> int:
    """Lê um inteiro de env var com fallback (nunca lança)."""
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _is_pt_voice(blob: str) -> bool:
    """Detecta voz em português do Brasil a partir de id/nome."""
    text = blob.lower()
    return any(marker in text for marker in _PT_VOICE_MARKERS)


class HybridVoice:
    """Gerenciador de voz híbrido (TTS + STT).

    Tenta usar edge-tts (online) primeiro, depois pyttsx3 (offline).
    Seleção automática de microfone por SNR via MicSelector.
    """

    def __init__(
        self,
        rate: int = 0,
        volume: int = 100,
        language: str = "pt-BR",
        auto_select_mic: bool = True,
        logger=None,
    ):
        self._rate = rate
        self._volume = volume
        self._language = language
        self._enabled = False
        self._tts_engine = None
        self._logger = logger
        self._lock = _SPEECH_LOCK
        self._recognizer = None
        self._speak_thread: threading.Thread | None = None
        self._stop_requested = False

        # Disjuntor do edge-tts: após N falhas seguidas, pausa as tentativas
        # por X minutos e loga UMA vez só (evita spam de 403 no log).
        self._edge_failures = 0
        self._edge_cooldown_until = 0.0  # time.monotonic()
        self._edge_cooldown_logged = False
        self._edge_max_failures = _env_int("ARIS_TTS_EDGE_MAX_FAILURES", 3)
        self._edge_cooldown_s = _env_int("ARIS_TTS_EDGE_COOLDOWN_MIN", 10) * 60

        # Mic selector
        self._mic_selector: MicSelector | None = None
        self._auto_select_mic = auto_select_mic and _MIC_SELECTOR_AVAILABLE

        self._init_tts()
        self._init_stt()

        if self._auto_select_mic:
            self._init_mic_selector()

    def _init_tts(self) -> None:
        """Inicializa o melhor engine TTS disponível (nunca voz em inglês)."""
        if _EDGE_TTS_AVAILABLE:
            self._tts_engine = "edge-tts"
            self._enabled = True
            return

        if _PYTTSX3_AVAILABLE:
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", 200 + self._rate * 20)
                engine.setProperty("volume", self._volume / 100)
                pt_voice = None
                try:
                    for v in engine.getProperty("voices") or []:
                        blob = f"{getattr(v, 'id', '')} {getattr(v, 'name', '')}"
                        if _is_pt_voice(blob):
                            pt_voice = v.id
                            break
                except Exception:
                    pass
                if pt_voice:
                    engine.setProperty("voice", pt_voice)
                    self._tts_engine = engine
                    self._enabled = True
                    return
                # Sem voz pt-BR: não fala inglês — deixa inativo.
                self._log("warning", "pyttsx3 sem voz pt-BR instalada; TTS offline desativado")
                try:
                    engine.stop()
                except Exception:
                    pass
            except Exception as exc:
                self._log("warning", f"Falha ao inicializar pyttsx3: {exc}")

        self._tts_engine = None
        self._enabled = False

    def _init_stt(self) -> None:
        """Inicializa o engine STT."""
        if _SR_AVAILABLE:
            self._recognizer = sr.Recognizer()

    def _init_mic_selector(self) -> None:
        """Inicializa seletor automático de microfone por SNR."""
        if not _MIC_SELECTOR_AVAILABLE:
            return
        try:
            self._mic_selector = MicSelector(logger=None)
            if self._mic_selector.start():
                # Aguarda primeira avaliação
                time.sleep(2.0)
        except Exception as exc:
            self._log("warning", f"Falha ao inicializar seletor de microfone: {exc}")
            self._mic_selector = None

    def _get_microphone(self) -> Optional["sr.Microphone"]:
        """Retorna Microphone com o melhor dispositivo selecionado."""
        if self._mic_selector and self._mic_selector.best_device:
            device_index = self._mic_selector.get_device_for_sr()
            if device_index is not None:
                try:
                    return sr.Microphone(device_index=device_index)
                except Exception:
                    pass
        # Fallback: microfone padrão
        return sr.Microphone()

    def _log(self, level: str, message: str) -> None:
        logger = getattr(self, "_logger", None)
        if logger:
            getattr(logger, level, print)(f"[VOICE] {message}")

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
            self._stop_requested = False
            thread = threading.Thread(target=self._speak_sync, args=(text,), daemon=True)
            self._speak_thread = thread
            thread.start()
        else:
            self._speak_sync(text)

    def _speak_sync(self, text: str) -> None:
        """Fala de forma síncrona."""
        with self._lock:
            if self._stop_requested:
                return
            try:
                if self._tts_engine == "edge-tts":
                    self._speak_edge(text)
                elif self._tts_engine and hasattr(self._tts_engine, "say"):
                    self._tts_engine.say(text)
                    self._tts_engine.runAndWait()
            except Exception:
                pass

    def _speak_edge(self, text: str) -> None:
        """Fala usando edge-tts (online) com disjuntor + fallback offline.

        Disjuntor: após N falhas seguidas (_edge_max_failures), pausa as
        tentativas do edge por _edge_cooldown_s segundos e loga UMA vez só.
        Enquanto pausado (ou se falhar), cai direto no fallback offline.
        """
        # Disjuntor aberto? Não tenta edge, vai direto p/ offline.
        if time.monotonic() < self._edge_cooldown_until:
            self._speak_offline(text)
            return

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._edge_tts_speak(text))
                finally:
                    loop.close()
                # Sucesso: zera o contador do disjuntor.
                self._edge_failures = 0
                self._edge_cooldown_logged = False
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.3)

        # Falha: alimenta o disjuntor.
        self._edge_failures += 1
        if self._edge_failures >= self._edge_max_failures:
            self._edge_cooldown_until = time.monotonic() + self._edge_cooldown_s
            if not self._edge_cooldown_logged:
                mins = self._edge_cooldown_s // 60
                self._log(
                    "warning",
                    f"edge-tts falhou {self._edge_failures}x seguidas "
                    f"({type(last_error).__name__}: {last_error}). "
                    f"Disjuntor: pausando edge-tts por {mins} min e usando voz offline.",
                )
                self._edge_cooldown_logged = True
        else:
            self._log("warning", f"edge-tts falhou ({type(last_error).__name__}: {last_error})")

        # Nunca cai para voz em inglês: o fallback só fala se houver voz pt-BR.
        self._speak_offline(text)

    def _speak_offline(self, text: str) -> None:
        """Fallback offline: piper → espeak-ng → pyttsx3 (voz pt-BR).

        Tenta o melhor disponível, nessa ordem. Silencioso se nenhum existir.
        """
        if self._speak_piper(text):
            return
        if self._speak_espeak(text):
            return
        self._speak_pyttsx3_ptbr(text, logger=self._logger)

    @staticmethod
    def _find_piper() -> str | None:
        """Localiza o binário do piper (PATH ou junto do interpretador)."""
        import shutil
        import sys
        from pathlib import Path

        exe = shutil.which("piper") or shutil.which("piper-tts")
        if exe:
            return exe
        # venv do projeto: o binário está em <venv>/bin mas o PATH do
        # processo (ARIS roda sem ativar o venv) pode não incluí-lo.
        candidate = Path(sys.executable).with_name("piper")
        if candidate.exists():
            return str(candidate)
        return None

    @staticmethod
    def _default_piper_voice() -> str:
        """Modelo do piper já baixado (voz feminina pt-BR), se existir.

        Procura em ~/.local/share/piper/voices e em <projeto>/voices.
        Sem modelo → "" (o piper sem --model falha e caímos no espeak).
        """
        from pathlib import Path

        home = Path.home()
        project = Path(__file__).resolve().parent.parent
        for directory in (
            home / ".local" / "share" / "piper" / "voices",
            project / "voices",
        ):
            model = directory / "pt_BR-faber-medium.onnx"
            if model.exists():
                return str(model)
        return ""

    def _speak_piper(self, text: str) -> bool:
        """Tenta falar com piper TTS (offline, pt-BR). True se reproduziu."""
        exe = self._find_piper()
        if not exe:
            return False
        import subprocess

        tmp_wav = os.path.join(tempfile.gettempdir(), f"aris_piper_{uuid.uuid4().hex}.wav")
        voice = os.getenv("ARIS_PIPER_VOICE", "") or self._default_piper_voice()
        try:
            cmd = [exe, "--output_file", tmp_wav]
            if voice:
                cmd += ["--model", voice]
            proc = subprocess.run(
                cmd, input=text.encode("utf-8"), capture_output=True, timeout=30
            )
            if proc.returncode != 0 or not os.path.exists(tmp_wav):
                return False
            return self._play_wav(tmp_wav)
        except Exception as exc:
            self._log("debug", f"piper falhou: {exc}")
            return False
        finally:
            try:
                if os.path.exists(tmp_wav):
                    os.remove(tmp_wav)
            except OSError:
                pass

    def _speak_espeak(self, text: str) -> bool:
        """Tenta falar com espeak-ng (offline, voz feminina pt-BR). True se reproduziu."""
        import shutil
        import subprocess

        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if not exe:
            return False
        tmp_wav = os.path.join(tempfile.gettempdir(), f"aris_espeak_{uuid.uuid4().hex}.wav")
        try:
            # pt-br+f3: variante feminina em português do Brasil (nunca
            # inglês). O mbrola-br2 (F) consta na lista mas não tem os
            # dados no sistema. ARIS_ESPEAK_VOICE troca a voz.
            espeak_voice = os.getenv("ARIS_ESPEAK_VOICE", "pt-br+f3")
            proc = subprocess.run(
                [exe, "-v", espeak_voice, "-w", tmp_wav, text],
                capture_output=True, timeout=30,
            )
            if proc.returncode != 0 or not os.path.exists(tmp_wav):
                return False
            return self._play_wav(tmp_wav)
        except Exception as exc:
            self._log("debug", f"espeak-ng falhou: {exc}")
            return False
        finally:
            try:
                if os.path.exists(tmp_wav):
                    os.remove(tmp_wav)
            except OSError:
                pass

    def _play_wav(self, path: str) -> bool:
        """Reproduz um WAV via pygame. True se tocou."""
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
            return True
        except Exception as exc:
            self._log("debug", f"pygame falhou ao tocar wav: {exc}")
            return False

    @staticmethod
    def _speak_pyttsx3_ptbr(text: str, logger=None) -> None:
        """Fallback offline — fala apenas com voz pt-BR instalada."""

        def _log(level: str, message: str) -> None:
            if logger:
                getattr(logger, level, print)(f"[VOICE] {message}")

        if not _PYTTSX3_AVAILABLE:
            return
        try:
            engine = pyttsx3.init()
        except Exception as exc:
            _log("warning", f"pyttsx3 indisponível: {exc}")
            return
        try:
            pt_voice = None
            for v in engine.getProperty("voices") or []:
                blob = f"{getattr(v, 'id', '')} {getattr(v, 'name', '')}"
                if _is_pt_voice(blob):
                    pt_voice = v.id
                    break
            if not pt_voice:
                _log(
                    "warning",
                    "Fallback TTS silenciado: nenhuma voz pt-BR instalada "
                    "(não será usada voz em inglês)",
                )
                return
            engine.setProperty("voice", pt_voice)
            try:
                engine.setProperty("rate", 200)
            except Exception:
                pass
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            _log("warning", f"Fallback pyttsx3 falhou: {exc}")
        finally:
            try:
                engine.stop()
            except Exception:
                pass

    @staticmethod
    def _clean_for_tts(text: str) -> str:
        """Limpa markdown e formatação para TTS natural."""
        if not text:
            return ""

        clean = text

        # Remover blocos de código
        clean = re.sub(r'```[\s\S]*?```', '', clean)

        # Remover inline code
        clean = re.sub(r'`([^`]+)`', r'\1', clean)

        # Remover bold/italic
        clean = re.sub(r'\*\*\*([^*]+)\*\*\*', r'\1', clean)
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
        clean = re.sub(r'\*([^*]+)\*', r'\1', clean)
        clean = re.sub(r'___([^_]+)___', r'\1', clean)
        clean = re.sub(r'__([^_]+)__', r'\1', clean)
        clean = re.sub(r'_([^_]+)_', r'\1', clean)

        # Remover links [text](url) → text
        clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)

        # Remover URLs
        clean = re.sub(r'https?://\S+', '', clean)

        # Remover headers markdown
        clean = re.sub(r'^#{1,6}\s+', '', clean, flags=re.MULTILINE)

        # Remover listas
        clean = re.sub(r'^[\s]*[-*+]\s+', '', clean, flags=re.MULTILINE)
        clean = re.sub(r'^[\s]*\d+\.\s+', '', clean, flags=re.MULTILINE)

        # Remover horizontal rules
        clean = re.sub(r'^[-*_]{3,}\s*$', '', clean, flags=re.MULTILINE)

        # Remover blockquotes
        clean = re.sub(r'^>\s*', '', clean, flags=re.MULTILINE)

        # Limpar espaços extras
        clean = re.sub(r'\n{3,}', '\n\n', clean)
        clean = re.sub(r' {2,}', ' ', clean)

        return clean.strip()

    async def _edge_tts_speak(self, text: str) -> None:
        """Gera áudio via edge-tts e reproduz."""
        clean = self._clean_for_tts(text)
        if not clean.strip():
            return

        voice = os.getenv("ARIS_TTS_VOICE", "pt-BR-FranciscaNeural")
        # Arquivo único por fala: evita colisão entre instâncias (HUD + ARIS).
        tmp_file = os.path.join(tempfile.gettempdir(), f"aris_speech_{uuid.uuid4().hex}.mp3")

        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(tmp_file)

            if self._stop_requested:
                return

            # Reproduzir com pygame; se falhar, usa o Windows MCI.
            played = False
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                pygame.mixer.music.load(tmp_file)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.wait(100)
                played = True
            except ImportError:
                pass
            except Exception as exc:
                self._log("debug", f"pygame falhou ao tocar áudio: {exc}")

            if not played:
                # Fallback: usar Windows MCI, aguardando a duração real do áudio
                try:
                    import ctypes
                    import time as _time
                    ctypes.windll.winmm.mciSendStringW(
                        f'open "{tmp_file}" type mpegvideo alias aris_speak', None, 0, None
                    )

                    length_buf = ctypes.create_unicode_buffer(64)
                    ctypes.windll.winmm.mciSendStringW(
                        "status aris_speak length", length_buf, 64, None
                    )
                    try:
                        total_ms = int(length_buf.value)
                    except (ValueError, TypeError):
                        total_ms = 0
                    max_seconds = (total_ms / 1000.0 + 2.0) if total_ms > 0 else 60.0

                    ctypes.windll.winmm.mciSendStringW("play aris_speak", None, 0, None)
                    started = _time.monotonic()
                    while _time.monotonic() - started < max_seconds:
                        mode_buf = ctypes.create_unicode_buffer(64)
                        ctypes.windll.winmm.mciSendStringW(
                            "status aris_speak mode", mode_buf, 64, None
                        )
                        if mode_buf.value.strip().lower() != "playing":
                            break
                        _time.sleep(0.25)
                    ctypes.windll.winmm.mciSendStringW("close aris_speak", None, 0, None)
                except Exception as exc:
                    self._log("warning", f"MCI falhou ao tocar áudio: {exc}")
        finally:
            # Liberar o arquivo (pygame/MCI podem mantê-lo aberto) e limpar
            try:
                import pygame
                if pygame.mixer.get_init():
                    pygame.mixer.music.unload()
            except Exception:
                pass
            for _ in range(5):
                try:
                    os.remove(tmp_file)
                    break
                except OSError:
                    time.sleep(0.2)

    def listen(self, timeout: int = 5, language: str = "pt-BR") -> str | None:
        """Escuta áudio do microfone e converte em texto.

        Args:
            timeout: Timeout em segundos.
            language: Código do idioma.

        Returns:
            Texto reconhecido ou None.
        """
        if not self._recognizer or not _SR_AVAILABLE:
            return None

        mic = self._get_microphone()
        if mic is None:
            return None

        try:
            with mic as source:
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

    def _listen_offline(self, audio) -> str | None:
        """Reconhecimento offline via Vosk."""
        try:
            import json

            from vosk import KaldiRecognizer, Model

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
        """Para a fala atual e seletor de microfone."""
        # Sinaliza cancelamento e espera a fala em andamento terminar.
        # Sem o join, o mixer do pygame é destruído enquanto outro thread
        # ainda toca áudio — no Linux isso derruba SIGABRT no encerramento.
        self._stop_requested = True
        thread = self._speak_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)

        if self._mic_selector:
            self._mic_selector.stop()
            self._mic_selector = None

        if self._tts_engine == "edge-tts":
            try:
                import ctypes
                ctypes.windll.winmm.mciSendStringW("stop aris_speak", None, 0, None)
            except Exception:
                pass
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
            return [
                "pt-BR-AntonioNeural (Edge TTS)",
                "pt-BR-FranciscaNeural (Edge TTS)",
                "pt-BR-ThalitaMultilingualNeural (Edge TTS)",
            ]
        elif self._tts_engine and hasattr(self._tts_engine, "getProperty"):
            try:
                voices = self._tts_engine.getProperty("voices")
                return [v.name for v in voices]
            except Exception:
                pass
        return []

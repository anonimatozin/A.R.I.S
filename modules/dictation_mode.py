"""Dictation Mode - Modo Dictação do J.A.R.V.I.S.

Segure uma tecla, fale, e o texto aparece em qualquer lugar.
Inspirado em isair/jarvis e akshayaggarwal99/jarvis-ai-assistant.
"""

import threading
import time
from typing import Optional

try:
    import pyautogui
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import speech_recognition as sr
    _SR = True
except ImportError:
    _SR = False


class DictationMode:
    """Modo de dictação: segure tecla → fala → texto digitado."""

    def __init__(self):
        self._active = False
        self._listening = False
        self._recognizer = None
        self._hold_key = "capslock"  # Tecla padrão
        self._language = "pt-BR"
        self._filler_words = ["é", "eh", "hum", "uh", "hmm", "tipo", "assim", "né"]
        self._custom_dictionary: dict[str, str] = {}
        self._history: list[dict] = []
        self._on_text: Optional[callable] = None

        if _SR:
            self._recognizer = sr.Recognizer()

    @property
    def available(self) -> bool:
        return _SR and _PYAUTOGUI

    @property
    def active(self) -> bool:
        return self._active

    def set_hold_key(self, key: str) -> str:
        """Define a tecla de ativação."""
        self._hold_key = key.lower()
        return f"Tecla de dictação: {self._hold_key}"

    def set_language(self, language: str) -> str:
        """Define o idioma."""
        self._language = language
        return f"Idioma: {language}"

    def add_fillers(self, *words: str) -> str:
        """Adiciona palavras para remover (fillers)."""
        self._filler_words.extend(words)
        return f"Fillers: {', '.join(self._filler_words)}"

    def add_dictionary_entry(self, word: str, replacement: str) -> str:
        """Adiciona entrada ao dicionário customizado."""
        self._custom_dictionary[word.lower()] = replacement
        return f"Dicionário: '{word}' → '{replacement}'"

    def clean_text(self, text: str) -> str:
        """Limpa o texto removendo fillers e aplicando dicionário."""
        words = text.split()
        cleaned = []

        for word in words:
            word_lower = word.lower().strip(".,!?;:")

            # Aplicar dicionário
            if word_lower in self._custom_dictionary:
                replacement = self._custom_dictionary[word_lower]
                cleaned.append(replacement)
            elif word_lower not in self._filler_words:
                cleaned.append(word)

        return " ".join(cleaned)

    def start_dictation(self, callback: Optional[callable] = None) -> str:
        """Inicia o modo dictação."""
        if not self.available:
            return "Dictação não disponível (instale SpeechRecognition e pyautogui)"

        self._active = True
        self._on_text = callback
        return f"Modo dictação ATIVADO. Segure '{self._hold_key}' e fale."

    def stop_dictation(self) -> str:
        """Para o modo dictação."""
        self._active = False
        self._listening = False
        return "Modo dictação desativado"

    def listen_once(self, timeout: int = 5) -> Optional[str]:
        """Escuta uma vez e retorna o texto."""
        if not self._recognizer:
            return None

        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = self._recognizer.listen(source, timeout=timeout)

            text = self._recognizer.recognize_google(audio, language=self._language)
            cleaned = self.clean_text(text)

            # Registrar no histórico
            self._history.append({
                "raw": text,
                "cleaned": cleaned,
                "timestamp": time.time(),
            })

            return cleaned

        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            # Tentar offline
            return self._listen_offline(audio)
        except Exception:
            return None

    def _listen_offline(self, audio) -> Optional[str]:
        """Reconhecimento offline via Vosk."""
        try:
            from vosk import Model, KaldiRecognizer
            import json

            model = Model("vosk-model-pt")
            rec = KaldiRecognizer(model, 16000)

            wav_data = audio.get_wav_data()
            if rec.AcceptWaveform(wav_data):
                result = json.loads(rec.Result())
                text = result.get("text", "")
                return self.clean_text(text)
        except Exception:
            pass
        return None

    def type_text(self, text: str) -> str:
        """Digita o texto reconhecido."""
        if not _PYAUTOGUI:
            return "pyautogui não disponível"

        pyautogui.typewrite(text, interval=0.02)
        return f"Texto digitado: {text[:50]}..."

    def get_history(self, limit: int = 10) -> list[dict]:
        """Retorna histórico de dictações."""
        return self._history[-limit:]

    def get_stats(self) -> dict:
        """Retorna estatísticas."""
        return {
            "active": self._active,
            "hold_key": self._hold_key,
            "language": self._language,
            "total_dicts": len(self._history),
            "fillers": len(self._filler_words),
            "dictionary_entries": len(self._custom_dictionary),
        }

    def format_status(self) -> str:
        """Formata status."""
        return (
            f"🎤 Dictation Mode\n"
            f"   Status: {'Ativo' if self._active else 'Inativo'}\n"
            f"   Tecla: {self._hold_key}\n"
            f"   Idioma: {self._language}\n"
            f"   Dictações: {len(self._history)}\n"
            f"   Fillers: {len(self._filler_words)}\n"
            f"   Dicionário: {len(self._custom_dictionary)} entradas"
        )

"""Silencia o ruido de ALSA/JACK que o PortAudio imprime no Linux.

Mensagens como "ALSA lib pcm.c ... Unknown PCM cards.pcm.rear" e "jack server is not running"
vem de bibliotecas em C quando o PortAudio lista os dispositivos de audio. Nao sao erros do ARIS.

Uso: importe ESTE modulo antes de qualquer import de sounddevice / pyaudio / pygame / faster-whisper:

    import aris_audio_quiet   # noqa: F401  (primeira linha util do main)

Depois do import, o ALSA fica mudo e o JACK nao tenta subir servidor. No Windows/macOS nao faz nada.
Para depurar problema de audio de verdade, rode com ARIS_AUDIO_DEBUG=1 (nao silencia nada).
"""
import ctypes
import ctypes.util
import os
import sys

_handler_ref = None   # precisa ficar vivo, senao o ctypes libera o callback e o programa cai


def silence_alsa():
    """Troca o handler de erro do ALSA por um que nao imprime nada. Devolve True se conseguiu."""
    global _handler_ref
    if not sys.platform.startswith("linux") or os.environ.get("ARIS_AUDIO_DEBUG") == "1":
        return False
    path = ctypes.util.find_library("asound")
    if not path:
        return False
    try:
        asound = ctypes.cdll.LoadLibrary(path)
        # void handler(const char *file, int line, const char *function, int err, const char *fmt, ...)
        proto = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                                 ctypes.c_int, ctypes.c_char_p)
        _handler_ref = proto(lambda *args: None)
        asound.snd_lib_error_set_handler(_handler_ref)
        return True
    except (OSError, AttributeError):
        return False


def silence_jack():
    """Impede o JACK de tentar iniciar um servidor (some com 'Cannot connect to server socket')."""
    if sys.platform.startswith("linux") and os.environ.get("ARIS_AUDIO_DEBUG") != "1":
        os.environ.setdefault("JACK_NO_START_SERVER", "1")


silence_jack()
silence_alsa()

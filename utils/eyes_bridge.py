"""Ponte A.R.I.S. → ARIS Eyes (olhos digitais na tela do usuário).

Conecta o núcleo da ARIS ao projeto ``aris_eyes/`` pelo canal local
descrito no README dele: uma linha de texto por socket UNIX em
``$XDG_RUNTIME_DIR``. O lado do cliente usa só a biblioteca padrão
(não precisa de Qt no ambiente da ARIS).

Mapeamento de estados (tabela do README do aris_eyes):

    ocioso (idle)          -> state neutral  (happy se a personalidade mandar)
    ouviu a wake word      -> state listening
    pensando/executando    -> state thinking
    falando                -> state speaking + speech <volume>
    sucesso                -> state happy
    erro                   -> state error
    alerta/confirmação     -> state alert
    encerrando (offline)   -> state sleeping

Personalidade: os traços ``humor``/``warmth`` enviesam o mood ocioso
(humor >= 0.65 ou warmth >= 0.75 -> happy, senão neutral). Pode ser
forçado com ``ARIS_EYES_IDLE_MOOD``.

Garantias — a ponte NUNCA atrapalha a ARIS:
- ``set_state`` não lança exceção (tudo é engolido e virar False);
- timeout curto (0,25s): olhos parados = ``send()`` devolve None na hora;
- deduplicação: estado repetido não é reenviado; se o envio falhar, o
  cache é desfeito para tentar de novo na próxima sincronização;
- kill-switch: ``ARIS_EYES=0`` desliga a ponte inteira;
- autolaunch: por PADRÃO a ponte sobe os olhos sozinha (``--mini``) no
  primeiro uso e reenvia o estado quando eles respondem ao ping;
  ``ARIS_EYES_AUTOLAUNCH=0`` desliga (aí os olhos são manuais).

Variáveis de ambiente:
    ARIS_EYES=0                 desliga a ponte
    ARIS_EYES_AUTOLAUNCH=0      não sobe os olhos automaticamente
    ARIS_EYES_SPEECH_LEVEL=0.6  volume da fala (0..1) ao entrar em speaking
    ARIS_EYES_IDLE_MOOD=neutral força o mood ocioso (ignora personalidade)
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Pasta do projeto aris_eyes (fica na raiz do projeto ARIS).
_EYES_DIR = Path(__file__).resolve().parent.parent / "aris_eyes"

# Estado da ARIS -> expressão dos olhos.
# None = estado que não deve mexer nos olhos (ex.: esp32_disconnected é
# estado do LED, não da ARIS).
MOOD_FOR_STATE: dict[str, str | None] = {
    "initializing": "neutral",
    "idle": None,          # resolvido por _resolve_idle_mood() (personalidade)
    "listening": "listening",
    "thinking": "thinking",
    "executing": "thinking",
    "speaking": "speaking",
    "success": "happy",
    "error": "error",
    "warning": "alert",
    "offline": "sleeping",
    "esp32_disconnected": None,
}

# Mini Deck (ESP32): estado Wi-Fi do deck -> expressão dos olhos.
WIFI_FACES: dict[str, str] = {
    "portal": "surprised",      # configurando (portal de configuração aberto)
    "connecting": "thinking",   # conectando à rede salva
    "connected": "happy",       # pronto
    "failed": "error",          # falhou (credenciais preservadas no deck)
}

# Estados em que o rosto está livre para a reação de Wi-Fi assumir.
_ESTADOS_OCIOSOS = frozenset({None, "idle", "initializing", "offline", "wifi"})

_lock = threading.Lock()
_last_state: str | None = None
_last_mood: str | None = None
_last_speaking = False
_last_speech_level: float | None = None
_idle_mood: str | None = None    # cache da personalidade
_launched = False
_sent = 0                           # comandos entregues
_failed = 0                         # sincronizações em que os olhos não responderam
_wifi_pendente: str | None = None   # reação Wi-Fi aguardando o idle da ARIS


def _enabled() -> bool:
    return os.getenv("ARIS_EYES", "1").strip().lower() not in ("0", "false", "no", "off")


def _import_send():
    """Importa ``aris_eyes.client.send`` (só stdlib). Levanta ImportError."""
    eyes_dir = str(_EYES_DIR)
    if eyes_dir not in sys.path:
        sys.path.insert(0, eyes_dir)
    # Se alguém importou "aris_eyes" antes (pacote namespace vindo da raiz
    # do projeto), limpa para o pacote real (com client.py) valer.
    cached = sys.modules.get("aris_eyes")
    if cached is not None and not hasattr(cached, "__file__"):
        for key in [k for k in sys.modules if k == "aris_eyes" or k.startswith("aris_eyes.")]:
            del sys.modules[key]
    from aris_eyes.client import send  # noqa: PLC0415 — import tardio proposital
    return send


def _client_send(command: str, timeout: float = 0.25) -> str | None:
    """Envia um comando para os olhos. Resposta, ou None. Nunca levanta."""
    try:
        send = _import_send()
        return send(command, timeout=timeout)
    except Exception:
        return None


def _norm_speech(level: float | None) -> float:
    """Normaliza o nível de fala para 0..1 (aceita também 0..100)."""
    raw = os.getenv("ARIS_EYES_SPEECH_LEVEL", "")
    if level is None and raw:
        try:
            level = float(raw)
        except ValueError:
            level = None
    if level is None:
        return 0.6
    try:
        value = float(level)
    except (TypeError, ValueError):
        return 0.6
    if value > 1.0:               # veio de volume 0..100
        value = value / 100.0
    return max(0.05, min(1.0, value))


def _mood_from_personality() -> str:
    """Mood ocioso derivado dos traços da personalidade (nunca levanta)."""
    forced = os.getenv("ARIS_EYES_IDLE_MOOD", "").strip().lower()
    if forced:
        return forced
    try:
        from core.personality import get_personality  # noqa: PLC0415

        traits = get_personality().get_state().traits
        humor = float(traits.get("humor", 0.5))
        warmth = float(traits.get("warmth", 0.5))
    except Exception:
        return "neutral"
    return "happy" if (humor >= 0.65 or warmth >= 0.75) else "neutral"


def _resolve_idle_mood() -> str:
    global _idle_mood
    if _idle_mood is None:
        _idle_mood = _mood_from_personality()
    return _idle_mood


def autolaunch_enabled() -> bool:
    """True se a ponte pode subir os olhos sozinha (padrão: sim)."""
    return os.getenv("ARIS_EYES_AUTOLAUNCH", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _maybe_launch() -> None:
    """Autolaunch: sobe os olhos UMA vez (padrão; ARIS_EYES_AUTOLAUNCH=0 desliga).

    Usa o mesmo interpretador da ARIS (``sys.executable``), que é o venv com
    PySide6 instalado — o ``aris-eyes.sh`` cairia no python3 do sistema.
    """
    global _launched
    if not autolaunch_enabled():
        return
    with _lock:
        if _launched:
            return
        _launched = True
    try:
        subprocess.Popen(
            [sys.executable, "-m", "aris_eyes", "--mini"],
            cwd=str(_EYES_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return
    threading.Thread(target=_retry_after_launch, daemon=True, name="eyes-retry").start()


def _retry_after_launch() -> None:
    """Espera os olhos subirem (ping) e reenvia o estado atual."""
    for _ in range(20):                       # ~10s no total
        time.sleep(0.5)
        if _client_send("ping", timeout=0.5) != "pong":
            continue
        with _lock:
            state, level = _last_state, _last_speech_level
            mood = _last_mood
            _clear_cache_locked()
        if state == "wifi" and mood:
            _aplicar_mood_wifi(mood)
            return
        if state:
            set_state(state, speech_level=level)
        return


def _clear_cache_locked() -> None:
    global _last_state, _last_mood, _last_speaking
    _last_state = None
    _last_mood = None
    _last_speaking = False


def set_state(state_value: str, speech_level: float | None = None) -> bool:
    """Sincroniza o estado da ARIS com os olhos.

    Returns:
        True se um comando foi enviado e aceito (``ok``); False caso
        contrário (desativado, estado irrelevante, dedupe, olhos parados).
        Nunca lança exceção.
    """
    global _last_state, _last_mood, _last_speaking, _last_speech_level, _sent, _failed
    if not _enabled():
        return False

    if state_value == "idle":
        mood = _resolve_idle_mood()
    else:
        mood = MOOD_FOR_STATE.get(state_value)
    if mood is None:
        return False
    speaking = mood == "speaking"

    with _lock:
        if (state_value == _last_state and speaking == _last_speaking
                and mood == _last_mood):
            return False                      # dedupe: nada mudou
        previous = (_last_state, _last_mood, _last_speaking, _last_speech_level)
        mood_changed = mood != _last_mood
        speech_changed = speaking != _last_speaking
        _last_state = state_value
        _last_mood = mood
        _last_speaking = speaking
        _last_speech_level = speech_level

    commands: list[str] = []
    if mood_changed:
        commands.append(f"state {mood}")
    if speaking and mood_changed:
        commands.append(f"speech {_norm_speech(speech_level):.2f}")
    if not speaking and speech_changed:
        commands.append("speech off")

    if not commands:
        return False

    accepted = False
    try:
        for command in commands:
            response = _client_send(command)
            if response is not None and not response.startswith("erro"):
                accepted = True
    except Exception:
        accepted = False

    if accepted:
        with _lock:
            _sent += 1
        if state_value == "idle":
            _aplica_pendente_wifi()          # reação Wi-Fi guardada no meio de outra coisa
        return True

    # Olhos parados/não responderam: desfaz o cache para re-tentar na
    # próxima sincronização (em vez de ficar "preso" achando que enviou).
    with _lock:
        _failed += 1
        _last_state, _last_mood, _last_speaking, _last_speech_level = previous
    _maybe_launch()
    return False


def set_wifi_face(estado: str, forcar: bool = False) -> str | None:
    """Reage nos olhos ao estado Wi-Fi do Mini Deck.

    Estados (``WIFI_FACES``): portal -> surprised, connecting -> thinking,
    connected -> happy, failed -> error.

    Se a ARIS estiver ocupada (falando/pensando/ouvindo), a reação fica
    ``pendente`` e é aplicada quando ela voltar ao idle — exceto com
    ``forcar=True`` (erro de Wi-Fi assume a expressão na hora, mas sem
    interromper uma fala em andamento).

    Returns:
        "aplicado"  — rosto ocioso, reação aplicada na hora (o chamador
                      pode falar um aviso por cima, se quiser);
        "pendente"  — guardada até a ARIS voltar ao idle;
        "forçado"   — assumiu com a ARIS ocupada (não falar por cima);
        None        — estado desconhecido, ponte desligada ou olhos parados.
        Nunca lança exceção.
    """
    global _wifi_pendente
    if not _enabled():
        return None
    mood = WIFI_FACES.get(estado)
    if mood is None:
        return None
    with _lock:
        ocioso = _last_state in _ESTADOS_OCIOSOS
        if not ocioso and not forcar:
            _wifi_pendente = mood
            return "pendente"
    if not _aplicar_mood_wifi(mood):
        return None                       # olhos parados/não responderam
    return "aplicado" if ocioso else "forçado"


def _aplicar_mood_wifi(mood: str) -> bool:
    """Aplica um mood de Wi-Fi direto nos olhos (estado sintético ``wifi``)."""
    global _last_state, _last_mood, _last_speaking, _last_speech_level, _sent, _failed
    with _lock:
        if _last_state == "wifi" and _last_mood == mood:
            return True                   # já está nessa expressão
        previous = (_last_state, _last_mood, _last_speaking, _last_speech_level)
        _last_state = "wifi"
        _last_mood = mood
        _last_speaking = False
        _last_speech_level = None

    try:
        response = _client_send(f"state {mood}")
        accepted = response is not None and not response.startswith("erro")
    except Exception:
        accepted = False

    if accepted:
        with _lock:
            _sent += 1
        return True

    # Olhos parados: desfaz o cache para re-tentar depois.
    with _lock:
        _failed += 1
        _last_state, _last_mood, _last_speaking, _last_speech_level = previous
    _maybe_launch()
    return False


def _aplica_pendente_wifi() -> None:
    """Aplica a reação de Wi-Fi guardada quando a ARIS volta ao idle."""
    global _wifi_pendente
    with _lock:
        pendente = _wifi_pendente
        _wifi_pendente = None
    if pendente:
        _aplicar_mood_wifi(pendente)


def refresh_idle_mood() -> str:
    """Recalcula o mood ocioso a partir da personalidade.

    Se os olhos estão ociosos agora, o novo mood é reenviado na hora.
    """
    global _idle_mood, _last_mood, _last_speaking, _last_state
    mood = _mood_from_personality()
    _idle_mood = mood
    resend = False
    with _lock:
        if _last_state == "idle" and _last_mood != mood:
            _last_mood = None                 # força reenvio do idle
            _last_speaking = False
            resend = True
    if resend:
        set_state("idle")
    return mood


def probe(timeout: float = 0.5) -> bool:
    """True se os olhos estão rodando (ping -> pong). Nunca lança."""
    return _client_send("ping", timeout=timeout) == "pong"


def ensure_running() -> bool:
    """True se os olhos já estão no ar; senão tenta subir (autolaunch).

    Chamado no startup da ARIS: garante que a janela dos olhos apareça
    mesmo antes da primeira mudança de estado. Nunca lança.
    """
    if probe():
        return True
    if autolaunch_enabled():
        _maybe_launch()
    return False


def stats() -> dict:
    """Diagnóstico da ponte (para testes/painel)."""
    with _lock:
        return {
            "enabled": _enabled(),
            "last_state": _last_state,
            "last_mood": _last_mood,
            "speaking": _last_speaking,
            "sent": _sent,
            "failed": _failed,
            "launched": _launched,
            "eyes_dir": str(_EYES_DIR),
        }


def reset_for_tests() -> None:
    """Zera todo o estado da ponte (usado apenas em testes)."""
    global _last_state, _last_mood, _last_speaking, _last_speech_level
    global _idle_mood, _launched, _sent, _failed, _wifi_pendente
    with _lock:
        _last_state = None
        _last_mood = None
        _last_speaking = False
        _last_speech_level = None
        _idle_mood = None
        _launched = False
        _sent = 0
        _failed = 0
        _wifi_pendente = None

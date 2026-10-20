"""Regressão do freeze do CI: driver 'dummy' do SDL quando não há som.

O CI travou 38 min em ``pygame.mixer.init()``: sem ``/dev/snd``, a
enumeração da ALSA trava com a GIL SEGURADA (py-spy mostrou a thread
principal morrendo em ``take_gil`` e o SIGALRM do pytest-timeout nunca
disparava). ``_garantir_driver_audio_headless`` decide quando forçar o
driver ``dummy`` — aqui testamos a decisão e a chamada ANTES do init,
sem depender de hardware.
"""

from __future__ import annotations

import sys
import time
import types

import utils.voice_hybrid as vh


def _hybrid() -> vh.HybridVoice:
    # auto_select_mic=False: sem MicSelector nem sleep de 2 s no teste.
    return vh.HybridVoice(auto_select_mic=False)


# ── decisão do helper ─────────────────────────────────────────────


def test_linux_sem_placa_forca_dummy(monkeypatch):
    monkeypatch.delenv("SDL_AUDIODRIVER", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(vh, "_tem_placa_som_linux", lambda: False)

    vh._garantir_driver_audio_headless()

    assert vh.os.environ.get("SDL_AUDIODRIVER") == "dummy"


def test_linux_com_placa_nao_mexe_na_env(monkeypatch):
    monkeypatch.delenv("SDL_AUDIODRIVER", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(vh, "_tem_placa_som_linux", lambda: True)

    vh._garantir_driver_audio_headless()

    assert vh.os.environ.get("SDL_AUDIODRIVER") is None


def test_env_existente_nao_e_sobrescrita(monkeypatch):
    monkeypatch.setenv("SDL_AUDIODRIVER", "pulseaudio")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(vh, "_tem_placa_som_linux", lambda: False)

    vh._garantir_driver_audio_headless()

    assert vh.os.environ["SDL_AUDIODRIVER"] == "pulseaudio"


def test_fora_do_linux_nao_mexe(monkeypatch):
    monkeypatch.delenv("SDL_AUDIODRIVER", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(vh, "_tem_placa_som_linux", lambda: False)

    vh._garantir_driver_audio_headless()

    assert vh.os.environ.get("SDL_AUDIODRIVER") is None


# ── chamada ANTES do mixer.init nas rotas de reprodução ───────────


def _pygame_falso():
    """pygame mínimo: mixer não inicializado → init registra a ordem."""
    chamadas: list[str] = []

    class _Mixer:
        @staticmethod
        def get_init():
            return None  # "não inicializado" → forçar init

        @staticmethod
        def init():
            chamadas.append("init")

        class music:  # noqa: N801 - espelha pygame.mixer.music
            @staticmethod
            def load(_caminho):
                chamadas.append("load")

            @staticmethod
            def play():
                chamadas.append("play")

            @staticmethod
            def get_busy():
                return False  # não entra no while de espera

    mod = types.SimpleNamespace(mixer=_Mixer, _chamadas=chamadas)
    return mod, chamadas


def test_play_wav_chama_helper_antes_do_init(monkeypatch):
    mod, chamadas = _pygame_falso()
    monkeypatch.setitem(sys.modules, "pygame", mod)
    monkeypatch.setattr(
        vh, "_garantir_driver_audio_headless",
        lambda: chamadas.append("helper"),
    )

    assert _hybrid()._play_wav("/tmp/inexistente.wav") is True
    assert chamadas[0] == "helper"
    assert chamadas.index("helper") < chamadas.index("init")


def test_reproduzir_audio_chama_helper_antes_do_init(monkeypatch):
    mod, chamadas = _pygame_falso()
    monkeypatch.setitem(sys.modules, "pygame", mod)
    monkeypatch.setattr(
        vh, "_garantir_driver_audio_headless",
        lambda: chamadas.append("helper"),
    )

    assert _hybrid()._reproduzir_audio("/tmp/inexistente.wav") is True
    assert chamadas[0] == "helper"
    assert chamadas.index("helper") < chamadas.index("init")


# ── fala contínua: fila sem buraco + cooldown sem fracionar ───────


def _pygame_fila_falso(duracao=0.1):
    """pygame simulado com a semântica do SDL_mixer (fila toca sozinha).

    ``music.queue(f)`` dispara sozinho quando a música atual termina;
    ``get_busy``/``get_queue`` espelham o mixer real. Tempo medido com
    ``time.monotonic`` (duração em segundos reais).
    """
    est = {
        "tocando": False, "fim": 0.0, "fila": None, "inicio": 0.0,
        "loads": [], "plays": 0, "queues": [],
    }

    def _get_busy():
        if est["tocando"] and time.monotonic() >= est["fim"]:
            if est["fila"]:
                est["fila"] = None
                est["inicio"] = time.monotonic()  # stream novo zera o clock
                est["fim"] = time.monotonic() + duracao
            else:
                est["tocando"] = False
        return est["tocando"]

    def _get_pos():
        if not est["tocando"]:
            return 0
        return int((time.monotonic() - est["inicio"]) * 1000)

    def _load(caminho):
        est["loads"].append(caminho)
        est["fila"] = None

    def _play():
        est["plays"] += 1
        est["tocando"] = True
        est["inicio"] = time.monotonic()
        est["fim"] = time.monotonic() + duracao

    def _queue(caminho):
        est["queues"].append(caminho)
        est["fila"] = caminho

    music = types.SimpleNamespace(
        load=_load, play=_play, queue=_queue,
        get_busy=_get_busy, get_pos=_get_pos,
        unload=lambda: None, init=lambda: None,
    )
    mixer = types.SimpleNamespace(get_init=lambda: (44100, -16, 2), music=music)
    mod = types.SimpleNamespace(
        mixer=mixer,
        time=types.SimpleNamespace(wait=lambda _ms: None),
        _est=est,
    )
    return mod, est


def test_fila_continua_carrega_uma_vez_e_enfileira_o_resto(monkeypatch):
    """Uma frase dá play; as demais entram na fila — sem buraco entre elas."""
    mod, est = _pygame_fila_falso(duracao=0.1)
    monkeypatch.setitem(sys.modules, "pygame", mod)

    h = _hybrid()
    h._tts_engine = "edge-tts"
    n = {"i": 0}

    def _sintetizar(text, loop):
        n["i"] += 1
        return f"/tmp/fake_{n['i']}.mp3", False

    limpos: list[str] = []
    monkeypatch.setattr(h, "_sintetizar_edge_mp3", _sintetizar)
    monkeypatch.setattr(h, "_limpar_mp3_tmp", limpos.append)

    h._speak_edge_fila("Vai chover amanhã. Leve guarda-chuva. Tudo bem?")

    assert n["i"] == 3  # uma síntese por frase
    assert est["plays"] == 1 and len(est["loads"]) == 1  # play único
    assert len(est["queues"]) == 2  # frases 2 e 3 enfileiradas (coladas)
    # Limpeza só DEPOIS que a última frase terminou de tocar; todos os
    # tmps são removidos (inclusive o da primeira frase).
    assert est["tocando"] is False
    assert limpos == ["/tmp/fake_1.mp3", "/tmp/fake_2.mp3", "/tmp/fake_3.mp3"]


def test_erro_no_meio_da_fila_fala_resto_offline_inteiro(monkeypatch):
    """Edge quebra no meio: disjuntor abre e o resto sai offline contínuo."""
    mod, est = _pygame_fila_falso(duracao=0.05)
    monkeypatch.setitem(sys.modules, "pygame", mod)

    h = _hybrid()
    h._tts_engine = "edge-tts"

    def _sintetizar(text, loop):
        if "guarda" in text:
            raise RuntimeError("403 simulado")
        return "/tmp/fake.mp3", False

    offline: list[str] = []
    disjuntor: list[Exception] = []
    monkeypatch.setattr(h, "_sintetizar_edge_mp3", _sintetizar)
    monkeypatch.setattr(h, "_limpar_mp3_tmp", lambda _p: None)
    monkeypatch.setattr(h, "_speak_offline", offline.append)
    monkeypatch.setattr(h, "_abrir_disjuntor_edge", disjuntor.append)

    h._speak_edge_fila("Tudo bem por aqui. Vai chover amanhã. Leve guarda-chuva. Até logo.")

    assert len(disjuntor) == 1 and isinstance(disjuntor[0], RuntimeError)
    # O resto vira UMA fala offline (sem tentativa de rede por frase).
    assert offline == ["Leve guarda-chuva. Até logo."]


def test_cooldown_fala_offline_inteiro_sem_fracionar(monkeypatch):
    """Disjuntor aberto: texto inteiro no offline, sem fracionar por frase."""
    h = _hybrid()
    h._tts_engine = "edge-tts"
    h._edge_cooldown_until = vh.time.monotonic() + 999

    offline: list[str] = []
    outras: list[str] = []
    monkeypatch.setattr(h, "_speak_offline", offline.append)
    monkeypatch.setattr(h, "_speak_edge_fila", outras.append)
    monkeypatch.setattr(h, "_speak_edge", outras.append)

    texto = "Vai chover amanhã. Leve guarda-chuva. Tudo bem?"
    h._speak_sync(texto)

    assert offline == [texto]  # uma chamada, com o texto completo
    assert outras == []  # nem fila nem edge por frase


def test_pyttsx3_prefere_voz_feminina_pt(monkeypatch):
    """Fallback de última instância: voz pt-BR feminina quando existe."""

    class _Voz:
        def __init__(self, id_, name):
            self.id = id_
            self.name = name

    class _Engine:
        def __init__(self):
            self.propriedades: dict = {}

        def getProperty(self, nome):  # noqa: N802 - espelha a API do pyttsx3
            return [_Voz("pt-br", "Felipe"), _Voz("pt-br+f3", "Helena")] if nome == "voices" else None

        def setProperty(self, nome, valor):  # noqa: N802 - espelha a API do pyttsx3
            self.propriedades[nome] = valor

        def say(self, _texto):
            pass

        def runAndWait(self):  # noqa: N802 - espelha a API do pyttsx3
            pass

        def stop(self):
            pass

    engine = _Engine()
    monkeypatch.setattr(vh, "_PYTTSX3_AVAILABLE", True)
    monkeypatch.setattr(vh, "pyttsx3", types.SimpleNamespace(init=lambda: engine))

    vh.HybridVoice._speak_pyttsx3_ptbr("Teste de voz.")

    assert engine.propriedades.get("voice") == "pt-br+f3"

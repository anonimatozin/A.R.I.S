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

"""Testes do ambiente dos olhos (utils/eyes_ambient.py) + precedência na ponte.

Cobre o contrato da Parte 2:
- música tocando -> scene spotify (e dedupe no ciclo seguinte);
- pausa com histerese de 3 s (não pisca) -> scene off;
- estado da ARIS SEMPRE passa na frente; retorno ao idle reaplica a cena;
- playerctl ausente -> fallback MPRIS (busctl);
- sem playerctl/busctl/dbus-send -> recurso desligado UMA vez no log;
- saídas de pactl e wpctl (fixtures reais/sintéticas) no parser do fone;
- falha no download da capa não quebra nada e accent só quando merece;
- kill-switch ARIS_EYES_AMBIENT=0 (sem subprocess, sem thread, sem observer);
- nenhuma exceção sobe; precedência bateria > ESP32 > comemorar > música;
- sono após ociosidade noturna (e não de dia).

Sem Spotify/áudio de verdade: subprocess e socket são simulados; o relógio
monotônico é injetado para a histerese e os transatórios serem determinísticos.
"""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils import eyes_ambient, eyes_bridge

FIXTURES = Path(__file__).parent / "fixtures" / "eyes_ambient"


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    """Estado zerado + env determinística entre testes."""
    for key in ("ARIS_EYES", "ARIS_EYES_SPEECH_LEVEL", "ARIS_EYES_AUTOLAUNCH",
                "ARIS_EYES_AMBIENT", "ARIS_EYES_AMBIENT_PLAYERS",
                "ARIS_EYES_AMBIENT_INTERVAL", "ARIS_EYES_AMBIENT_IDLE_DORMIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARIS_EYES_IDLE_MOOD", "neutral")
    monkeypatch.setenv("ARIS_EYES_AUTOLAUNCH", "0")   # nunca subir olhos de verdade
    eyes_bridge.reset_for_tests()
    eyes_ambient.reset_para_testes()
    yield
    eyes_bridge.reset_for_tests()
    eyes_ambient.reset_para_testes()


class _Relogio:
    """Relógio falso para os testes (histerese, janelas, ociosidade)."""

    def __init__(self, inicio: float = 1000.0):
        self.t = inicio

    def agora(self) -> float:
        return self.t

    def pular(self, segundos: float) -> None:
        self.t += segundos


@pytest.fixture
def relogio(monkeypatch):
    r = _Relogio()
    monkeypatch.setattr(eyes_ambient, "_agora", r.agora)
    return r


@pytest.fixture
def envios(monkeypatch):
    """Grava os comandos que iriam pro socket dos olhos."""
    calls: list = []

    def _fake_send(command, timeout=0.25, path=None):
        calls.append(command)
        return "ok"

    monkeypatch.setattr(eyes_bridge, "_client_send", _fake_send)
    return calls


@pytest.fixture
def comandos(monkeypatch):
    """subprocess.run simulado: mapa['cmd inteiro'] -> stdout | Exception."""
    mapa: dict = {}
    registros: list = []

    def _fake_run(cmd, capture_output=True, text=True, timeout=2.0):
        chave = " ".join(cmd)
        registros.append(chave)
        if chave not in mapa:
            return SimpleNamespace(returncode=1, stdout="")
        valor = mapa[chave]
        if isinstance(valor, Exception):
            raise valor
        return SimpleNamespace(returncode=0, stdout=valor)

    monkeypatch.setattr(eyes_ambient.subprocess, "run", _fake_run)
    return {"mapa": mapa, "registros": registros}


@pytest.fixture
def binarios(monkeypatch):
    """Quais binários 'existem' nesta simulação (padrão: só playerctl)."""
    presentes: set = {"playerctl"}
    monkeypatch.setattr(eyes_ambient, "_existe", lambda b: b in presentes)
    return presentes


KEY_STATUS = "playerctl -p spotify status"
KEY_ART = "playerctl -p spotify -f {{metadata:mpris:artUrl}}"
KEY_BUSCTL_STATUS = ("busctl --user get-property org.mpris.MediaPlayer2.spotify "
                     "/org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player Status")


# ── 1. Música ───────────────────────────────────────────────

class TestMusica:
    def test_tocando_manda_scene_spotify_e_deduplica(self, envios, comandos,
                                                     binarios, relogio):
        comandos["mapa"][KEY_STATUS] = "Playing\n"
        assert eyes_ambient.reconciliar() == ("spotify", ())
        assert "scene spotify" in envios
        # ciclo seguinte: mesma cena, nada novo bate nos olhos
        envios.clear()
        assert eyes_ambient.reconciliar() == ("spotify", ())
        assert envios == []

    def test_pausa_com_histerese_so_tira_a_cena_depois_de_3s(self, envios, comandos,
                                                             binarios, relogio):
        comandos["mapa"][KEY_STATUS] = "Playing\n"
        assert eyes_ambient.reconciliar() == ("spotify", ())
        comandos["mapa"][KEY_STATUS] = "Paused\n"
        # dentro da histerese: cena continua (sem "scene off")
        relogio.pular(1.0)
        envios.clear()
        assert eyes_ambient.reconciliar() == ("spotify", ())
        assert envios == []
        # passou de 3 s: a música "sai do ar" e a cena encerra
        relogio.pular(3.0)
        envios.clear()
        assert eyes_ambient.reconciliar() is None
        assert envios == ["scene off"]

    def test_playerctl_ausente_usa_busctl(self, envios, comandos, binarios, relogio):
        binarios.discard("playerctl")
        binarios.add("busctl")
        comandos["mapa"][KEY_BUSCTL_STATUS] = \
            (FIXTURES / "busctl_status_playing.txt").read_text(encoding="utf-8")
        assert eyes_ambient.reconciliar() == ("spotify", ())
        assert "scene spotify" in envios

    def test_sem_playerctl_busctl_nem_dbus_desliga_uma_vez(self, comandos, binarios,
                                                           relogio, caplog):
        binarios.clear()                       # nenhum caminho de consulta MPRIS
        with caplog.at_level(logging.WARNING, logger="aris.eyes_ambient"):
            assert eyes_ambient.reconciliar() is None
            assert eyes_ambient.reconciliar() is None
        assert comandos["registros"] == []      # nem tentou subprocess
        assert eyes_ambient._desligado("spotify")
        desligados = [r for r in caplog.records
                      if "desligado" in r.getMessage() and "'spotify'" in r.getMessage()]
        assert len(desligados) == 1             # log UMA vez

    def test_status_sem_player_nao_desliga_o_recurso(self, comandos, binarios, relogio):
        # playerctl existe mas ninguém responde (rc=1): recurso segue vivo
        assert eyes_ambient.reconciliar() is None
        assert not eyes_ambient._desligado("spotify")
        comandos["mapa"][KEY_STATUS] = "Playing\n"
        assert eyes_ambient.reconciliar() == ("spotify", ())


# ── 2. Precedência ARIS × ambiente ─────────────────────────

class TestPrecedencia:
    def test_estado_da_aris_passa_na_frente_e_idle_reaplica(self, envios, comandos,
                                                           binarios, relogio):
        comandos["mapa"][KEY_STATUS] = "Playing\n"
        assert eyes_ambient.reconciliar() == ("spotify", ())
        assert "scene spotify" in envios

        # ARIS falando: o estado dela assume os olhos
        envios.clear()
        assert eyes_bridge.set_state("speaking") is True
        assert "state speaking" in envios

        # no meio da fala, o ambiente tenta outra cena: fica SÓ guardada
        envios.clear()
        eyes_ambient.notificar_esp32_conectado()
        assert eyes_ambient.reconciliar() == ("conectado", ())
        assert not any(c.startswith("scene ") for c in envios), envios

        # voltou ao idle: a ponte manda a cena guardada no lugar do mood ocioso
        envios.clear()
        assert eyes_bridge.set_state("idle") is True
        assert "scene conectado" in envios
        assert "state neutral" not in envios

    def test_falha_nos_olhos_nao_trava_e_repete_no_proximo_ciclo(self, monkeypatch,
                                                                 comandos, binarios,
                                                                 relogio):
        comandos["mapa"][KEY_STATUS] = "Playing\n"
        monkeypatch.setattr(eyes_bridge, "_client_send",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("socket")))
        # não levantou: o alvo continua sendo calculado e nada foi "enviado"
        assert eyes_ambient.reconciliar() == ("spotify", ())
        assert eyes_bridge.stats()["cena_enviada"] is None


# ── 3. Fone de ouvido (fixtures) ────────────────────────────

class TestFone:
    @pytest.mark.parametrize("nome,default,esperado", [
        ("pactl_list_sinks_speakers.txt", "alsa_output.pci-0000_00_1f.3.analog-stereo", False),
        ("pactl_list_sinks_headphones.txt", "alsa_output.pci-0000_00_1f.3.analog-stereo", True),
        ("pactl_list_sinks_bluetooth.txt", "bluez_sink.AC_12_2F_9B_44_E1.1", True),
    ])
    def test_pactl(self, nome, default, esperado, comandos, binarios):
        binarios.add("pactl")
        comandos["mapa"]["pactl get-default-sink"] = default + "\n"
        comandos["mapa"]["pactl list sinks"] = \
            (FIXTURES / nome).read_text(encoding="utf-8")
        assert eyes_ambient._fone_ativo() is esperado

    @pytest.mark.parametrize("nome,esperado", [
        ("wpctl_inspect_caixa_alta.txt", False),
        ("wpctl_inspect_bluetooth.txt", True),
        ("wpctl_inspect_headphones.txt", True),
    ])
    def test_wpctl_inspect(self, nome, esperado, comandos, binarios):
        binarios.add("wpctl")
        comandos["mapa"]["wpctl status"] = \
            (FIXTURES / "wpctl_status_speakers.txt").read_text(encoding="utf-8")
        comandos["mapa"]["wpctl inspect @DEFAULT_AUDIO_SINK@"] = \
            (FIXTURES / nome).read_text(encoding="utf-8")
        assert eyes_ambient._fone_ativo() is esperado

    def test_fone_e_musica_juntos_vira_spotify_com_headphones(self, envios, comandos,
                                                              binarios, relogio):
        binarios.update({"pactl"})
        comandos["mapa"][KEY_STATUS] = "Playing\n"
        comandos["mapa"]["pactl get-default-sink"] = "bluez_sink.AC_12_2F_9B_44_E1.1\n"
        comandos["mapa"]["pactl list sinks"] = \
            (FIXTURES / "pactl_list_sinks_bluetooth.txt").read_text(encoding="utf-8")
        assert eyes_ambient.reconciliar() == ("spotify", ("headphones",))
        assert envios == ["scene spotify", "prop headphones on"]

    def test_so_fone_sem_musica_vira_scene_fone(self, envios, comandos, binarios,
                                                relogio):
        binarios.update({"pactl"})
        comandos["mapa"]["pactl get-default-sink"] = "bluez_sink.AC_12_2F_9B_44_E1.1\n"
        comandos["mapa"]["pactl list sinks"] = \
            (FIXTURES / "pactl_list_sinks_bluetooth.txt").read_text(encoding="utf-8")
        assert eyes_ambient.reconciliar() == ("fone", ())
        assert "scene fone" in envios


# ── 4. Cor da capa (accent) ─────────────────────────────────

class TestCapa:
    def test_falha_no_download_retorna_none_sem_levantar(self, monkeypatch):
        def _explode(*a, **k):
            raise OSError("sem internet")
        monkeypatch.setattr(eyes_ambient.urllib.request, "urlopen", _explode)
        assert eyes_ambient._cor_da_capa("https://example.com/x.jpg") is None

    def test_extraia_cor_vermelha_e_garanta_brilho_minimo(self, tmp_path):
        from PIL import Image

        vermelho = tmp_path / "capa.png"
        Image.new("RGB", (16, 16), (200, 30, 30)).save(vermelho)
        cor = eyes_ambient._cor_da_capa(str(vermelho))
        assert cor and cor.startswith("#") and len(cor) == 7
        r, g, b = int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)
        assert r > g and r > b                    # é vermelha de verdade

        cinza = tmp_path / "cinza.png"
        Image.new("RGB", (16, 16), (50, 50, 50)).save(cinza)
        cor2 = eyes_ambient._cor_da_capa(str(cinza))
        assert cor2 and max(int(cor2[i:i + 2], 16) for i in (1, 3, 5)) >= 70

    def test_capa_muito_grande_e_ignorada(self, tmp_path):
        grande = tmp_path / "grande.png"
        grande.write_bytes(b"\x00" * (eyes_ambient._CAPA_LIMITE + 10))
        assert eyes_ambient._cor_da_capa(str(grande)) is None

    def test_accent_enviado_uma_vez_e_ao_reaplicar(self, envios, comandos, binarios,
                                                   relogio):
        comandos["mapa"][KEY_STATUS] = "Playing\n"
        eyes_ambient._accent = "#ff5e00"          # cor já extraída (cache)
        assert eyes_ambient.reconciliar() == ("spotify", ())
        assert envios == ["scene spotify", "accent #ff5e00"]
        envios.clear()
        assert eyes_ambient.reconciliar() == ("spotify", ())
        assert envios == []                       # dedupe do accent também


# ── 5. Eventos (ESP32, sucesso, bateria, sono) ──────────────

class TestEventos:
    def test_esp32_conectado_e_transitorio(self, envios, comandos, binarios, relogio):
        eyes_ambient.notificar_esp32_conectado()
        assert eyes_ambient.reconciliar() == ("conectado", ())
        assert "scene conectado" in envios
        relogio.pular(4.0)                        # janela acabou
        assert eyes_ambient.reconciliar() is None

    def test_observador_success_dispara_comemorar(self, envios, comandos, binarios,
                                                  relogio):
        eyes_ambient._on_estado_ponte("success")
        assert eyes_ambient.reconciliar() == ("comemorar", ())
        assert "scene comemorar" in envios
        relogio.pular(5.0)
        assert eyes_ambient.reconciliar() is None

    def test_bateria_vence_musica(self, envios, comandos, binarios, relogio, monkeypatch):
        comandos["mapa"][KEY_STATUS] = "Playing\n"
        monkeypatch.setattr(eyes_ambient, "_bateria_fraca", lambda: True)
        assert eyes_ambient.reconciliar() == ("bateria", ())
        assert "scene bateria" in envios

    @pytest.mark.parametrize("hora,esperado", [(23, ("dormir", ())), (13, None)])
    def test_sono_somente_a_noite_apos_ociosidade(self, hora, esperado, envios,
                                                  comandos, binarios, relogio,
                                                  monkeypatch):
        monkeypatch.setattr(
            eyes_ambient, "datetime",
            type("D", (), {"now": staticmethod(lambda: SimpleNamespace(hour=hora))}))
        monkeypatch.setattr(eyes_ambient, "_bateria_fraca", lambda: None)
        # a ARIS entrou no idle (caminho real: observador da ponte)
        eyes_bridge.registrar_observador(eyes_ambient._on_estado_ponte)
        assert eyes_bridge.set_state("idle") is True
        relogio.pular(16 * 60.0)                  # ocioso há 16 min
        assert eyes_ambient.reconciliar() == esperado
        if esperado:
            assert "scene dormir" in envios


# ── 6. Garantias (kill-switch, erros) ───────────────────────

class TestGarantias:
    def test_kill_switch_sem_subprocess_thread_nem_observer(self, monkeypatch,
                                                            comandos, envios, relogio):
        monkeypatch.setenv("ARIS_EYES_AMBIENT", "0")
        assert eyes_ambient.reconciliar() is None
        assert comandos["registros"] == []
        assert envios == []
        eyes_ambient.iniciar()                    # não deve subir nada
        assert eyes_ambient._thread is None
        assert eyes_bridge.stats()["observadores"] == 0

    def test_nenhuma_excecao_sobe(self, monkeypatch, comandos, binarios, relogio):
        def _explode(*a, **k):
            raise RuntimeError("quebrou")
        monkeypatch.setattr(eyes_ambient.subprocess, "run", _explode)
        monkeypatch.setattr(eyes_ambient.urllib.request, "urlopen", _explode)
        monkeypatch.setattr(eyes_bridge, "_client_send",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("sem socket")))
        assert eyes_ambient.reconciliar() is None  # engoliu tudo
        eyes_ambient.notificar_esp32_conectado()
        assert eyes_ambient.reconciliar() == ("conectado", ())   # e continuou

    def test_loop_rodando_e_para(self, monkeypatch, relogio, envios, binarios):
        # iniciar/parar: thread nasce, registra o observador e morre no parar()
        monkeypatch.setenv("ARIS_EYES_AMBIENT_INTERVAL", "0.5")
        eyes_ambient.iniciar()
        thread = eyes_ambient._thread
        assert thread is not None and thread.is_alive()
        assert eyes_bridge.stats()["observadores"] == 1
        eyes_ambient.iniciar()                    # idempotente
        assert eyes_ambient._thread is thread
        eyes_ambient.parar(timeout=3.0)
        assert not thread.is_alive()

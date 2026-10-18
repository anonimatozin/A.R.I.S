"""Integração do motor dedicado no sensor de voz contínua — sem microfone.

Um motor FALSO com scores programados exercita o caminho do
ARIS_WAKE_ENGINE=openwakeword: bip ao acordar, contexto de ~1 s, gate de
privacidade (nada transcrito antes de acordar), cooldown, limiar +0.2
durante o TTS e a entrega do comando SEM conter a wake word no texto.
O modo transcript (padrão) continua com o fluxo nativo inalterado.
"""

import time

import pytest

from core.perception.continuous_voice_sensor import (
    ContinuousVoiceConfig,
    ContinuousVoiceSensor,
)

FRAME = b"\x01" * 960  # 30ms @16kHz 16-bit (mesma geometria do sensor real)


class MotorFalso:
    """Motor com scores programados (o último valor repete)."""

    def __init__(self, scores, falha=False):
        self.scores = list(scores)
        self.falha = falha
        self.chamadas = 0
        self.resets = 0

    def process(self, frame):
        self.chamadas += 1
        if self.falha:
            raise RuntimeError("motor quebrou")
        idx = min(self.chamadas - 1, len(self.scores) - 1)
        return self.scores[idx]

    def reset(self):
        self.resets += 1


@pytest.fixture
def sensor(monkeypatch):
    entregas = []
    s = ContinuousVoiceSensor(
        send_message_fn=lambda texto, origem: entregas.append(texto),
        event_bus=None,
        config=ContinuousVoiceConfig(enabled=False),
    )
    s.entregas = entregas
    bips = []
    monkeypatch.setattr(s, "_tocar_bip", lambda: bips.append(time.time()))
    s.bips = bips
    return s


# ─── _wake_pontua: limiar, cooldown e barge-in ───


def test_score_abaixo_do_limiar_nao_acorda(sensor):
    sensor._wake_engine = MotorFalso([0.2, 0.3])
    assert sensor._wake_pontua(FRAME) is False
    assert sensor._wake_pontua(FRAME) is False


def test_score_no_limiar_acorda(sensor):
    sensor._wake_engine = MotorFalso([0.9])
    assert sensor._wake_pontua(FRAME) is True


def test_cooldown_bloqueia_novo_acordar(sensor):
    sensor._wake_engine = MotorFalso([0.9, 0.9, 0.9])
    assert sensor._wake_pontua(FRAME) is True
    sensor._last_wake_time = time.time()  # acabou de acordar
    assert sensor._wake_pontua(FRAME) is False


def test_limiar_sobe_com_a_aris_falando(sensor):
    # +0.2 durante o TTS: 0.6 não acorda (limiar 0.7) mas 0.9 sim
    sensor._wake_engine = MotorFalso([0.6, 0.9])
    sensor._esta_falando = lambda: True
    assert sensor._wake_pontua(FRAME) is False
    assert sensor._wake_pontua(FRAME) is True


def test_motor_com_falha_nunca_derruba(sensor):
    sensor._wake_engine = MotorFalso([0.9], falha=True)
    assert sensor._wake_pontua(FRAME) is False  # sem exceção


# ─── _despertar_por_motor: bip, contexto e janela de captura ───


def test_despertar_por_motor_prepara_a_captura(sensor):
    sensor._wake_engine = MotorFalso([0.9])
    sensor._contexto.extend([FRAME] * 33)  # ~1 s guardado no loop

    sensor._despertar_por_motor()

    assert sensor._wake_pelo_motor is True
    assert sensor._wake_word_in_speech is True   # janela de captura aberta
    assert sensor._in_speech is True
    assert sensor._speech_buffer == [FRAME] * 33  # contexto não é perdido
    assert sensor._speech_frames == 33
    assert len(sensor.bips) == 1                  # bip tocado uma vez


def test_despertar_por_motor_e_idempotente(sensor):
    sensor._wake_engine = MotorFalso([0.9])
    sensor._despertar_por_motor()
    sensor._despertar_por_motor()  # segundo frame alto no mesmo segmento
    assert len(sensor.bips) == 1


# ─── _process_speech_buffer: privacidade e entrega ───


def test_gate_de_privacidade_nao_transcreve_sem_acordar(sensor, monkeypatch):
    sensor._wake_engine = MotorFalso([0.1])
    sensor._speech_buffer = [FRAME]
    chamadas = []
    monkeypatch.setattr(sensor, "_transcribe", lambda audio: chamadas.append(audio) or "fl")

    assert sensor._process_speech_buffer() is False
    assert chamadas == []              # STT NUNCA rodou (privacidade)
    assert sensor._speech_buffer == [] # e o descarte aconteceu


def test_comando_entregue_sem_wake_word_no_texto(sensor, monkeypatch):
    """O áudio já acordou (motor); o texto do comando pode não citar a ARIS."""
    sensor._wake_engine = MotorFalso([0.9])
    sensor._wake_pelo_motor = True
    sensor._speech_buffer = [FRAME]
    monkeypatch.setattr(sensor, "_transcribe", lambda audio: "abre o navegador")

    assert sensor._process_speech_buffer() is True
    assert sensor.entregas == ["abre o navegador"]


def test_janela_do_motor_zera_ao_fechar_a_utterancia(sensor, monkeypatch):
    sensor._wake_engine = MotorFalso([0.9])
    sensor._wake_pelo_motor = True
    sensor._speech_buffer = [FRAME]
    monkeypatch.setattr(sensor, "_transcribe", lambda audio: "abre o navegador")

    sensor._process_speech_buffer()

    assert sensor._wake_pelo_motor is False   # próximo segmento começa do zero
    assert sensor._wake_engine.resets == 1    # motor também é limpo


def test_modo_transcript_padrao_continua_igual(sensor, monkeypatch):
    """Sem motor, o fluxo nativo transcreve e casa a wake word no texto."""
    assert sensor._wake_engine is None
    sensor._speech_buffer = [FRAME]
    monkeypatch.setattr(sensor, "_transcribe", lambda audio: "aris, que horas são?")

    assert sensor._process_speech_buffer() is True
    assert sensor.entregas == ["aris, que horas são?"]


def test_excecao_no_transcribe_nao_propaga(sensor, monkeypatch):
    sensor._wake_pelo_motor = True
    sensor._speech_buffer = [FRAME]

    def _quebra(audio):
        raise RuntimeError("STT caiu")

    monkeypatch.setattr(sensor, "_transcribe", _quebra)
    assert sensor._process_speech_buffer() is False  # sem exceção


# ─── _criar_wake_engine: escolha por env ───


def test_criar_engine_padrao_e_transcript(sensor, monkeypatch):
    monkeypatch.delenv("ARIS_WAKE_ENGINE", raising=False)
    sensor._criar_wake_engine()
    assert sensor._wake_engine is None  # fluxo nativo inalterado


def test_openwakeword_indisponivel_cai_no_transcript(sensor, monkeypatch):
    monkeypatch.setenv("ARIS_WAKE_ENGINE", "openwakeword")
    try:
        import openwakeword  # noqa: F401
        pytest.skip("openWakeWord instalado: o construtor carregaria um modelo real")
    except ImportError:
        pass
    sensor._criar_wake_engine()  # não levanta
    assert sensor._wake_engine is None

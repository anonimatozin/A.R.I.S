"""Motores de wake word (core/perception/wake_engine.py) — sem microfone.

Cobrem o Protocol, o TranscriptWakeEngine (fallback), a factory com as
variáveis de ambiente (inclusive valores inválidos) e a garantia de que
nenhuma exceção sobe do processamento de frame.
"""

import logging

import pytest

from core.perception import wake_engine
from core.perception.wake_engine import (
    OpenWakeWordEngine,
    TranscriptWakeEngine,
    WakeEngine,
    criar_engine,
    escolher_engine,
    limiar_padrao,
)

WAKE = ("aris", "arís", "ariz", "arizs")

try:
    import openwakeword  # noqa: F401
    TEM_OPENWAKEWORD = True
except ImportError:
    TEM_OPENWAKEWORD = False


def _transcrever_de(textos):
    """STT falso: devolve os textos em ordem (o último repete)."""
    fila = list(textos)

    def _f(_audio):
        return fila.pop(0) if len(fila) > 1 else fila[0]

    return _f


# ─── Protocol ───


def test_transcript_wake_engine_atende_o_protocol():
    engine = TranscriptWakeEngine(transcrever=lambda audio: "aris")
    assert isinstance(engine, WakeEngine)


def test_interface_do_protocol_exige_process_e_reset():
    for nome in ("process", "reset"):
        assert hasattr(TranscriptWakeEngine(transcrever=lambda audio: ""), nome)


# ─── TranscriptWakeEngine ───


def test_acorda_quando_o_stt_confirma_a_wake_word():
    engine = TranscriptWakeEngine(
        transcrever=lambda audio: "aris, que horas são?",
        is_speech=lambda frame: frame != b"\x00" * len(frame),
        wake_words=WAKE,
        silence_limit_frames=3,
    )
    # fala (bytes "cheios") e depois silêncio para fechar a utterância
    for _ in range(5):
        assert engine.process(b"\x01" * 960) == 0.0
    for _ in range(3):
        score = engine.process(b"\x00" * 960)
    assert score == 1.0


def test_nao_acorda_sem_wake_word_no_texto():
    engine = TranscriptWakeEngine(
        transcrever=lambda audio: "o time ganhou o jogo ontem",
        is_speech=lambda frame: frame != b"\x00" * len(frame),
        wake_words=WAKE,
        silence_limit_frames=3,
    )
    for _ in range(5):
        engine.process(b"\x01" * 960)
    for _ in range(3):
        score = engine.process(b"\x00" * 960)
    assert score == 0.0


def test_silencio_nunca_acorda():
    """Áudio sintético de silêncio não gera buffer nem STT."""
    chamadas = []

    def transcrever(audio):
        chamadas.append(audio)
        return "aris"

    engine = TranscriptWakeEngine(
        transcrever=transcrever,
        is_speech=lambda frame: False,  # VAD diz: nada é fala
        wake_words=WAKE,
        silence_limit_frames=2,
    )
    scores = [engine.process(b"\x00" * 960) for _ in range(10)]
    assert scores == [0.0] * 10
    assert chamadas == []  # STT nunca rodou


def test_ruido_branco_sintetico_nao_acorda():
    """Ruído → o STT falso devolve lixo → sem wake word → 0.0."""
    import random

    random.seed(42)
    ruido = [bytes(random.randrange(256) for _ in range(960)) for _ in range(5)]
    engine = TranscriptWakeEngine(
        transcrever=_transcrever_de(["ghksl rngak zqp"]),
        is_speech=lambda frame: frame != b"\x00" * len(frame),
        wake_words=WAKE,
        silence_limit_frames=3,
    )
    for frame in ruido:
        assert engine.process(frame) == 0.0
    scores = [engine.process(b"\x00" * 960) for _ in range(3)]  # silêncio fecha
    assert scores[-1] == 0.0


def test_reset_descarta_o_buffer_parcial():
    engine = TranscriptWakeEngine(
        transcrever=lambda audio: "aris",
        is_speech=lambda frame: frame != b"\x00" * len(frame),
        wake_words=WAKE,
        silence_limit_frames=2,
    )
    for _ in range(5):
        engine.process(b"\x01" * 960)
    engine.reset()
    # silêncio após o reset: sem buffer, nada a transcrever
    for _ in range(2):
        assert engine.process(b"\x00" * 960) == 0.0


def test_excecao_no_stt_vira_score_zero():
    def transcrever_com_erro(audio):
        raise RuntimeError("STT quebrou")

    engine = TranscriptWakeEngine(
        transcrever=transcrever_com_erro,
        is_speech=lambda frame: frame != b"\x00" * len(frame),
        wake_words=WAKE,
        silence_limit_frames=2,
    )
    for _ in range(3):
        engine.process(b"\x01" * 960)
    assert engine.process(b"\x00" * 960) == 0.0  # não levantou


# ─── OpenWakeWordEngine ───


@pytest.mark.skipif(
    TEM_OPENWAKEWORD,
    reason="openWakeWord instalado nesta máquina (construiria um modelo real)",
)
def test_openwakeword_sem_dependencia_levanta_erro_instrutivo():
    with pytest.raises(ImportError, match="requirements-optional"):
        OpenWakeWordEngine()


def test_score_max_dict_e_array():
    assert wake_engine._score_max({"aris": 0.8, "outro": 0.1}) == pytest.approx(0.8)
    assert wake_engine._score_max([0.2, 0.9]) == pytest.approx(0.9)
    assert wake_engine._score_max({}) == 0.0
    assert wake_engine._score_max([]) == 0.0
    assert wake_engine._score_max(object()) == 0.0  # lixo não derruba


# ─── Factory + variáveis de ambiente ───


def test_padrao_e_transcript(monkeypatch):
    monkeypatch.delenv("ARIS_WAKE_ENGINE", raising=False)
    assert escolher_engine() == "transcript"
    assert criar_engine() is None  # sem STT injetado: fluxo nativo do sensor


def test_openwakeword_pedido_mas_indisponivel_cai_no_transcript(
    monkeypatch, caplog,
):
    monkeypatch.setenv("ARIS_WAKE_ENGINE", "openwakeword")
    with caplog.at_level(logging.WARNING, logger="core.perception.wake_engine"):
        engine = criar_engine(transcrever=lambda audio: "aris")
    assert engine is None or isinstance(engine, TranscriptWakeEngine)
    if not TEM_OPENWAKEWORD:
        assert any("openWakeWord indisponível" in r.message for r in caplog.records)


def test_engine_invalido_cai_no_transcript_com_aviso(monkeypatch, caplog):
    monkeypatch.setenv("ARIS_WAKE_ENGINE", "banana")
    with caplog.at_level(logging.WARNING, logger="core.perception.wake_engine"):
        assert escolher_engine() == "transcript"
    assert any("desconhecido" in r.message for r in caplog.records)


def test_limiar_padrao_e_ajuste(monkeypatch):
    monkeypatch.delenv("ARIS_WAKE_THRESHOLD", raising=False)
    assert limiar_padrao() == pytest.approx(0.5)
    monkeypatch.setenv("ARIS_WAKE_THRESHOLD", "0.75")
    assert limiar_padrao() == pytest.approx(0.75)
    monkeypatch.setenv("ARIS_WAKE_THRESHOLD", "2.0")
    assert limiar_padrao() == pytest.approx(1.0)  # clamp
    monkeypatch.setenv("ARIS_WAKE_THRESHOLD", "abc")
    assert limiar_padrao() == pytest.approx(0.5)  # inválido → padrão


def test_criar_engine_transcript_com_stt_injetado(monkeypatch):
    monkeypatch.setenv("ARIS_WAKE_ENGINE", "transcript")
    engine = criar_engine(
        transcrever=lambda audio: "aris",
        is_speech=lambda frame: True,
        wake_words=WAKE,
    )
    assert isinstance(engine, TranscriptWakeEngine)

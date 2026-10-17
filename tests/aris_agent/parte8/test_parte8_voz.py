"""Parte 8 — confirmação por voz/teclado: timeout = negar, dúvida = negar."""

from __future__ import annotations

import time

import pytest

from aris_agent.bridge.voz import (
    ConfirmanteDeVoz,
    entrada_com_tempo,
    interpretar_resposta,
    segundos_para_ouvinte,
)
from aris_agent.contract.types import ConfirmRequest, Risk


def _pedido(hard: bool = False, preview: str = "apagar o arquivo teste.txt") -> ConfirmRequest:
    return ConfirmRequest(
        tool_name="pc_delete_file",
        args_preview=preview,
        risk=Risk.DESTRUCTIVE,
        reason="arquivo será enviado para a Lixeira",
        hard_confirm=hard,
    )


@pytest.mark.parametrize(
    ("resposta", "hard", "esperado"),
    [
        (None, False, False),  # timeout nega
        ("", False, False),
        ("   ", False, False),
        ("sim", False, True),
        ("Sim!", False, True),
        ("pode", False, True),
        ("confirma", False, True),
        ("não", False, False),
        ("nao, cancela", False, False),
        ("qualquer coisa", False, False),  # dúvida nega
        ("sim", True, True),
        ("sim, pode", True, True),
        ("confirma", True, True),
        ("pode", True, False),  # hard exige afirmação explícita no começo
        ("isso", True, False),
        ("não", True, False),
        (None, True, False),
    ],
)
def test_interpretar_resposta(resposta: str | None, hard: bool, esperado: bool) -> None:
    assert interpretar_resposta(resposta, hard=hard) is esperado


def test_confirmante_fala_preview_e_ouve_sim() -> None:
    falado: list[str] = []
    ouvidos: list[float] = []

    def ouvir(timeout_s: float) -> str | None:
        ouvidos.append(timeout_s)
        return "sim"

    conf = ConfirmanteDeVoz(
        falar=lambda texto, *, sync=False: falado.append(texto),
        ouvir=ouvir,
        timeout_s=7.0,
    )
    assert conf(_pedido()) is True
    assert "apagar o arquivo teste.txt" in falado[0]
    assert "Confirma" in falado[0]
    # a ouvida recebe o orçamento (quase) integral quando a fala é rápida
    assert ouvidos and 6.0 <= ouvidos[0] <= 7.0


def test_fala_lenta_nao_esgota_o_orcamento() -> None:
    """TTS lento/quebrado não pode comer a confirmação: ouve com o restante."""
    ouvidos: list[float] = []

    def falar_lento(_texto: str, *, sync: bool = False) -> None:
        time.sleep(1.2)  # simula retries de TTS morrendo

    def ouvir(timeout_s: float) -> str | None:
        ouvidos.append(timeout_s)
        return "sim"

    conf = ConfirmanteDeVoz(
        falar=falar_lento,
        ouvir=ouvir,
        timeout_s=5.0,
        fala_max_s=0.2,  # teto curto para o teste
    )
    inicio = time.monotonic()
    assert conf(_pedido()) is True  # resposta chegou apesar da fala lenta
    assert time.monotonic() - inicio < 1.0  # não esperou a fala inteira
    assert ouvidos and ouvidos[0] > 3.0  # ouviu com o que sobrou do orçamento


def test_confirmante_hard_fala_que_e_destrutiva() -> None:
    falado: list[str] = []
    conf = ConfirmanteDeVoz(
        falar=lambda texto, *, sync=False: falado.append(texto),
        ouvir=lambda _t: "sim",
    )
    assert conf(_pedido(hard=True)) is True
    assert "destrutiva" in falado[0].lower()
    assert "sim" in falado[0].lower()


def test_confirmante_timeout_nega() -> None:
    conf = ConfirmanteDeVoz(
        falar=lambda texto, *, sync=False: None,
        ouvir=lambda _t: None,
    )
    assert conf(_pedido()) is False


def test_confirmante_ouvir_que_quebra_nao_derruba() -> None:
    def ouvir(_t: float) -> str | None:
        raise RuntimeError("sem áudio")

    conf = ConfirmanteDeVoz(falar=lambda texto, *, sync=False: None, ouvir=ouvir)
    assert conf(_pedido()) is False  # sem áudio = dúvida = nega


def test_confirmante_falar_que_quebra_continua() -> None:
    def falar(_texto: str, *, sync: bool = False) -> None:
        raise RuntimeError("TTS fora")

    conf = ConfirmanteDeVoz(falar=falar, ouvir=lambda _t: "pode")
    assert conf(_pedido()) is True  # fala falhou, mas a ouvida responde


def test_confirmante_sem_preview_usa_nome_da_ferramenta() -> None:
    falado: list[str] = []
    conf = ConfirmanteDeVoz(
        falar=lambda texto, *, sync=False: falado.append(texto),
        ouvir=lambda _t: "não",
    )
    assert conf(_pedido(preview="")) is False
    assert "pc_delete_file" in falado[0]


def test_entrada_com_tempo_devolve_que_veio(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _p="": "sim")
    assert entrada_com_tempo(2.0, prompt="> ") == "sim"


def test_entrada_com_tempo_eof_devolve_none(monkeypatch) -> None:
    def _eof(_p: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    assert entrada_com_tempo(2.0) is None


def test_entrada_com_tempo_estoura_e_descarta_resposta_tardia(monkeypatch) -> None:
    def _lento(_p: str = "") -> str:
        time.sleep(1.4)  # > timeout mínimo de 1s
        return "tarde demais"

    monkeypatch.setattr("builtins.input", _lento)
    inicio = time.monotonic()
    assert entrada_com_tempo(1.0) is None
    assert time.monotonic() - inicio < 1.35  # devolveu no timeout, sem esperar o fim
    time.sleep(0.5)  # deixa a thread órfã terminar e ser descartada


def test_segundos_para_ouvinte_arredonda_para_cima() -> None:
    assert segundos_para_ouvinte(5.2) == 6
    assert segundos_para_ouvinte(0.2) == 1
    assert segundos_para_ouvinte(1.0) == 1

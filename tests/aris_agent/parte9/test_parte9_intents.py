"""Parte 9 — dataset de intenções e avaliação do classificador injetável."""

from __future__ import annotations

import pytest

from aris_agent.evals.intents import (
    DATASET_PATH,
    ROTULOS,
    avaliar_classificador,
    carregar_dataset,
    classificar_regras,
    relatorio_markdown,
)


def test_dataset_existe_e_tem_tamanho_minimo() -> None:
    assert DATASET_PATH.is_file()
    pares = carregar_dataset()
    assert len(pares) >= 300, f"dataset com só {len(pares)} frases"


def test_dataset_sem_duplicatas_e_rotulos_validos() -> None:
    pares = carregar_dataset()
    textos = [t for t, _r in pares]
    assert len(textos) == len(set(textos)), "há frases repetidas no dataset"
    assert {r for _t, r in pares} <= set(ROTULOS)
    # todos os rótulos precisam aparecer
    assert {r for _t, r in pares} == set(ROTULOS)


def test_rotulo_invalido_levanta_erro(tmp_path) -> None:
    arquivo = tmp_path / "d.jsonl"
    arquivo.write_text('{"texto": "oi", "rotulo": "outro"}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        carregar_dataset(arquivo)


def test_classificador_de_referencia_bate_meta() -> None:
    """Linha de base honesta: só regras, sem LLM. Meta: ≥90% geral, ≥95% perigoso."""
    resultado = avaliar_classificador(classificar_regras)
    assert resultado["total"] >= 300
    assert resultado["acuracia"] >= 0.90, (
        f"acurácia {resultado['acuracia']} abaixo de 0.90"
    )
    perigoso = resultado["por_rotulo"]["perigoso"]
    assert perigoso["acuracia"] >= 0.95, (
        f"recall de perigoso {perigoso['acuracia']} abaixo de 0.95"
    )


def test_classificador_ruim_levanta_acuracia_baixa() -> None:
    resultado = avaliar_classificador(lambda _texto: "conversa")
    assert 0.0 < resultado["acuracia"] < 0.5
    assert resultado["por_rotulo"]["conversa"]["acertos"] == 55


def test_classificador_que_lanca_nao_derruba_avaliacao() -> None:
    def bomba(_texto: str) -> str:
        raise RuntimeError("explode")

    resultado = avaliar_classificador(bomba)
    assert resultado["acertos"] == 0


def test_relatorio_markdown() -> None:
    resultado = avaliar_classificador(classificar_regras)
    texto = relatorio_markdown(resultado)
    assert "# Avaliação do classificador de intenções" in texto
    for rotulo in ROTULOS:
        assert rotulo in texto

"""Fuzzy ≤1 edição da wake word (bug real: o whisper ouvia "Ares", não "Aris").

A camada fuzzy vive em matches_wake_word junto com o casamento por palavra
inteira (tests/test_wake_word.py traz os casos deles): ela só vale em
palavras >= 4 letras com a MESMA letra inicial, entao "Ares" acorda mas
"varis"/"iris" nao.
"""

import pytest

from core.perception.continuous_voice_sensor import matches_wake_word

WAKE = ("aris", "arís", "ariz", "arizs")


@pytest.mark.parametrize(
    "frase",
    [
        "Ares, abre o navegador",   # whisper ouviu "Ares" em vez de "Aris"
        "ares toca uma música",
        "ei alris",                 # 1 edição (transposição/deleção), inicial igual
    ],
)
def test_acorda_com_variacao_fonica(frase):
    assert matches_wake_word(frase, WAKE)


@pytest.mark.parametrize(
    "frase",
    [
        "varis coisas",             # 1 edição mas letra inicial diferente
        "maris chegou aqui",        # idem
        "iris brilha",              # idem
        "arisson",                  # 3 edições demais
        "ari",                      # curto demais p/ fuzzy e não é palavra exata
    ],
)
def test_nao_acorda_fora_da_regra_fuzzy(frase):
    assert not matches_wake_word(frase, WAKE)


def test_fuzzy_com_lista_customizada():
    assert matches_wake_word("ares", ("aris",))
    assert matches_wake_word("ariz", ("aris",))
    assert not matches_wake_word("iris", ("aris",))
    assert not matches_wake_word("paris", ("aris",))


def test_pontuacao_e_casing_continuam_valendo():
    assert matches_wake_word("ARIS!", ("aris",))
    assert matches_wake_word("Ei, Áris:", ("aris",))
    assert not matches_wake_word("arisco", ("aris",))    # 2 edições

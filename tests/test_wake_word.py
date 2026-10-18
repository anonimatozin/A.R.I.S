"""Wake word por palavra inteira (antes era substring: "Paris" acordava a ARIS)."""

import pytest

from core.perception.continuous_voice_sensor import matches_wake_word

WAKE = ("aris", "arís", "ariz", "arizs")


@pytest.mark.parametrize(
    "frase",
    [
        "Aris abre o navegador",
        "ei aris",
        "Áris, que horas são?",
        "ARIS",
        "oi, aris.",
        "aris!",
        "abre o youtube aris",
        "ARÍS",
        "ariz toca uma música",
    ],
)
def test_acorda_com_a_palavra(frase):
    assert matches_wake_word(frase, WAKE)


@pytest.mark.parametrize(
    "frase",
    [
        "Paris é uma cidade linda",
        "a Maris chegou",
        "varis coisas",
        "esse cachorro é arisco",
        "ariscos e bravos",
        "Arizona fica nos Estados Unidos",
        "",
        "   ",
    ],
)
def test_nao_acorda_com_palavras_parecidas(frase):
    assert not matches_wake_word(frase, WAKE)


def test_sem_wake_words_nunca_acorda():
    assert not matches_wake_word("aris", ())


def test_acento_nao_importa_nos_dois_lados():
    assert matches_wake_word("aris", ("arís",))
    assert matches_wake_word("áris", ("aris",))


def test_wake_word_com_mais_de_uma_palavra():
    assert matches_wake_word("ei aris, tudo bem?", ("ei aris",))
    assert not matches_wake_word("ei paris", ("ei aris",))

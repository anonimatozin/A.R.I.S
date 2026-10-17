"""Mini-agente pedra-papel-tesoura na Camada Reflexo.

Regra de entrega: jogar PPT ≥ 3 vezes conferindo o placar —
sorteio local (sem LLM), placar determinístico, resultado no LED.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import random

from core.reflex_layer import JokenpoReflexAgent, ReflexLayer


class FakeFace:
    """Dublê da FaceMatrixClient — grava o que iria para /num e /face."""

    def __init__(self):
        self.numbers: list[int] = []
        self.states: list[str] = []

    def show_number(self, value) -> bool:
        self.numbers.append(int(value))
        return True

    def set_state(self, state: str, hold: float = 0.0) -> bool:
        self.states.append(state)
        return True


def _agent(seed: int = 42, face=None) -> JokenpoReflexAgent:
    return JokenpoReflexAgent(face_matrix=face, rng=random.Random(seed))


# ── Partida completa: 3 rodadas + placar ───────────────────

def test_tres_rodadas_com_placar_consistente():
    face = FakeFace()
    agent = _agent(seed=42, face=face)
    layer = ReflexLayer(agents=[agent])

    respostas = []
    for jogada in ("pedra", "papel", "tesoura"):
        result = layer.process(f"eu jogo {jogada}")
        assert result is not None and result.handled, jogada
        respostas.append(result.response)

    # placar fecha com o número de rodadas
    assert sum(agent.score.values()) == 3
    assert 0 <= agent.score["user"] <= 3
    assert 0 <= agent.score["aris"] <= 3
    assert 0 <= agent.score["draw"] <= 3

    # cada resposta traz a jogada e o placar atualizado
    for resposta in respostas:
        assert "Placar" in resposta
        assert "você" in resposta.lower()
        assert any(m in resposta for m in ("pedra", "papel", "tesoura"))

    # LED recebeu /num com o resultado de cada rodada (0/1/2)
    assert len(face.numbers) == 3
    assert all(code in (0, 1, 2) for code in face.numbers)


def test_placar_deterministico_contra_regra():
    """Replica a regra do jogo e confere o placar do agente."""
    moves = ("pedra", "papel", "tesoura")
    esperado = {"aris": 0, "user": 0, "draw": 0}
    rng = random.Random(7)
    for jogada in ("pedra", "papel", "tesoura"):
        aris_move = rng.choice(moves)
        diff = (moves.index(aris_move) - moves.index(jogada)) % 3
        if diff == 0:
            esperado["draw"] += 1
        elif diff == 1:
            esperado["aris"] += 1
        else:
            esperado["user"] += 1

    agent = _agent(seed=7)
    for jogada in ("pedra", "papel", "tesoura"):
        result = agent.handle(f"jogo {jogada}")
        assert result.handled

    assert agent.score == esperado


def test_sem_llm_e_sem_led_tambem_funciona():
    """LED opcional: sem matriz a partida continua."""
    agent = _agent(seed=1, face=None)
    result = agent.handle("pedra")
    assert result.handled
    assert "Placar" in result.response


# ── Comandos da partida ────────────────────────────────────

def test_inicio_placar_e_reset():
    agent = _agent()
    layer = ReflexLayer(agents=[agent])

    start = layer.process("vamos jogar pedra papel tesoura")
    assert start is not None and start.handled
    assert "pedra" in start.response.lower()

    layer.process("pedra")
    layer.process("papel")
    assert sum(agent.score.values()) == 2

    placar = layer.process("qual o placar")
    assert placar is not None and placar.handled
    assert "Placar —" in placar.response

    reset = layer.process("zera o placar")
    assert reset is not None and reset.handled
    assert agent.score == {"aris": 0, "user": 0, "draw": 0}


def test_variacoes_de_jogada_sao_reconhecidas():
    agent = _agent()
    for frase in (
        "pedra",
        "jogo papel",
        "vou de tesoura",
        "eu escolho pedra",
        "Papel!",
    ):
        assert agent.can_handle(frase) >= 0.9, frase


def test_nao_sequestra_conversa_comum():
    agent = _agent()
    layer = ReflexLayer(agents=[agent])
    for frase in ("que horas são", "abre o notepad", "manda mensagem pro João"):
        assert agent.can_handle(frase) == 0.0, frase
        assert layer.process(frase) is None, frase


def test_led_recebe_resultado_a_cada_rodada():
    face = FakeFace()
    agent = _agent(seed=3, face=face)
    for _ in range(3):
        agent.handle("pedra")
    assert len(face.numbers) == 3

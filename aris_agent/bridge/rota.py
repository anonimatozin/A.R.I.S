"""Roteamento de pedidos da Parte 8: parada de emergência e intenção.

Decisão (depois da Camada Reflexo, que continua mandando na frente):

1. frase de parada ("para tudo") → KillSwitch, resposta curta;
2. classificador de intenção (regras, o mesmo avaliado nos evals da Parte 9):
   tarefa (``comando_pc``/``pesquisa``/``perigoso``) → agente completo;
   o resto (conversa, pergunta, recado/ideia longa) → caminho antigo.
"""

from __future__ import annotations

import logging
import unicodedata

from ..evals.intents import classificar_regras

log = logging.getLogger("aris.agent.bridge.rota")

# Frases de emergência (normalizadas: sem acento/caixa). O texto precisa ser
# curto — "para tudo" dentro de uma frase longa não é ordem de parada.
FRASES_DE_PARADA = (
    "para tudo",
    "pare tudo",
    "cancela tudo",
    "cancelar tudo",
    "para agora",
    "pare agora",
    "para com isso",
    "pare com isso",
    "chega disso",
)
MAX_CHARS_PARADA = 80

# Frases longas não viram comando (spec da Parte 8: recado/ideia grandes não
# devem ser fatiados em ordens); perigoso passa sempre (segurança não espera).
MAX_CHARS_TAREFA = 160
ROTULOS_TAREFA = frozenset({"comando_pc", "pesquisa", "perigoso"})


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços colapsados (para casar frases)."""
    base = (
        unicodedata.normalize("NFKD", str(texto))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return " ".join(base.lower().split())


class Roteador:
    """Decide entre ``"agente"`` (tarefa) e ``"conversa"`` (caminho atual)."""

    def __init__(self, *, max_chars_tarefa: int = MAX_CHARS_TAREFA) -> None:
        self.max_chars_tarefa = int(max_chars_tarefa)

    def eh_de_parada(self, texto: str) -> bool:
        """``True`` se o texto é uma ordem de parada curta ("para tudo")."""
        base = normalizar(texto).strip(" .!?")
        if not base or len(base) > MAX_CHARS_PARADA:
            return False
        return any(frase in base for frase in FRASES_DE_PARADA)

    def decidir(self, texto: str) -> str:
        """Devolve ``"agente"`` ou ``"conversa"`` para ``texto``."""
        limpo = " ".join(str(texto).split())
        if not limpo:
            return "conversa"
        try:
            rotulo = classificar_regras(limpo)
        except Exception as exc:  # noqa: BLE001 - classificador nunca pode derrubar o loop
            log.warning("classificador falhou (%s); seguindo como conversa", exc)
            return "conversa"
        if rotulo == "perigoso":
            return "agente"  # política de segurança só existe no agente
        if len(limpo) > self.max_chars_tarefa:
            return "conversa"  # recado/ideia longa: deixa o caminho atual conversar
        if rotulo in ROTULOS_TAREFA:
            return "agente"
        return "conversa"

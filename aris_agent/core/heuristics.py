"""Heurísticas leves do laço: trivialidade, correção, verificação e dificuldade."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

Difficulty = Literal["easy", "normal", "hard"]

# Marcadores em português (minúsculos e sem acento) casados por substring.
_CASUAL_RE = re.compile(
    r"^(oi|ola|opa|e ai|eai|bom dia|boa tarde|boa noite|obrigad[oa]|vlw|valeu|ok|certo|"
    r"beleza|tchau|fala|fps)[.!?\s]*$"
)

_ACAO = (
    "pesquis", "busca", "internet", "abrir", "criar", "salvar", "escrev", "execut",
    "rodar", "instal", "apag", "delet", "envi", "baix", "calcul", "arquivo", "pasta",
    "clique", "digita", "agenda", "lembre", "memoria", "plano", "tarefa", "resume",
    "lista", "config", "sistema", "programa", "confer", "verific", "renome", "move",
)

_CORRECAO = (
    "o certo e", "nao, o certo", "errado", "esta errado", "ta errado", "voce errou",
    "vc errou", "nao e isso", "nao foi isso", "nao era isso", "correcao", "se enganou",
    "do jeito certo", "modo certo", "voce confundiu", "vc confundiu",
)

_VERIFICAR = (
    "confira", "confirme", "confirma", "confere", "conferir", "verifique", "verificar",
    "certeza", "checa", "checar", "revisa", "revisar", "garanta", "garantir",
)


def normalize(text: str) -> str:
    """Minúsculas e sem acento — base para casar marcadores em português."""
    lowered = unicodedata.normalize("NFD", str(text).lower())
    return "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")


def looks_trivial(text: str) -> bool:
    """True para conversa casual ou pedido curto que não pede ação nenhuma."""
    t = normalize(text).strip()
    if not t:
        return True
    if _CASUAL_RE.match(t):
        return True
    return len(t) <= 30 and not any(p in t for p in _ACAO)


def looks_like_correction(text: str) -> bool:
    """True quando o usuário parece estar corrigindo a ARIS."""
    t = normalize(text)
    return any(marcador in t for marcador in _CORRECAO)


def asks_to_verify(text: str) -> bool:
    """True quando o usuário pede para conferir/confirmar o resultado."""
    t = normalize(text)
    return any(marcador in t for marcador in _VERIFICAR)


def choose_difficulty(
    user_text: str,
    *,
    first: bool,
    plan_size: int,
    tool_calls_done: int,
    corrections: int,
) -> Difficulty:
    """Escolhe a cadeia de modelos: easy (trivial), normal (padrão), hard (complexo/falhou)."""
    if corrections:
        return "hard"
    if plan_size >= 3 or tool_calls_done >= 3:
        return "hard"
    if first and looks_trivial(user_text):
        return "easy"
    return "normal"


__all__ = [
    "Difficulty",
    "asks_to_verify",
    "choose_difficulty",
    "looks_like_correction",
    "looks_trivial",
    "normalize",
]

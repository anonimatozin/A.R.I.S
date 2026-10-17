"""Normalização de texto da memória: acentos, caixa, pontuação e deduplicação.

A mesma normalização é usada para deduplicar itens (``remember``) e para a busca
no modo ``LIKE`` (fallback quando o SQLite não tem FTS5), garantindo que
"configuração" encontre "configuracao".
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Troca qualquer sequência de pontuação/símbolos por um espaço.
_PUNCT_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+", flags=re.UNICODE)

# Limite de caracteres comparados na semelhança quase-duplicada (custo do SequenceMatcher).
_SIM_MAX_CHARS = 300


def strip_accents(text: str) -> str:
    """Remove marcas diacríticas (NFKD + filtro de combining)."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, sem pontuação e com espaços colapsados."""
    lowered = (text or "").lower()
    without_accents = strip_accents(lowered)
    without_punct = _PUNCT_RE.sub(" ", without_accents)
    return _WS_RE.sub(" ", without_punct).strip()


def tokenize(text: str) -> list[str]:
    """Termos normalizados de uma consulta (para FTS5 e LIKE)."""
    norm = normalize(text)
    return [term for term in norm.split(" ") if term]


def escape_like(term: str) -> str:
    """Escapa curingas do ``LIKE`` (``%``, ``_`` e ``\\``) para uso com ``ESCAPE '\\'``."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def similar(a: str, b: str, threshold: float = 0.92) -> bool:
    """Verifica se dois textos (já normalizados) são "quase iguais".

    Usa ``SequenceMatcher.ratio()`` limitado aos primeiros ``_SIM_MAX_CHARS``
    caracteres, com um pré-filtro de comprimento que é seguro para o limiar
    (se a semelhança >= t, a diferença de comprimento não passa de ~17%).
    """
    if not a or not b:
        return False
    if a == b:
        return True
    max_diff = 0.25 * max(len(a), len(b))
    if abs(len(a) - len(b)) > max_diff:
        return False
    return SequenceMatcher(None, a[:_SIM_MAX_CHARS], b[:_SIM_MAX_CHARS]).ratio() >= threshold


def clean_tags(tags) -> tuple[str, ...]:
    """Normaliza uma lista de tags: strings, sem vazias, sem repetidas, no máximo 12."""
    if tags is None:
        return ()
    if isinstance(tags, str):
        parts = [part.strip() for part in tags.split(",")]
    else:
        try:
            parts = [str(part).strip() for part in tags if part is not None]
        except TypeError:
            return ()
    seen: dict[str, None] = {}
    for part in parts:
        if not part or len(part) > 48:
            continue
        seen.setdefault(part)
        if len(seen) >= 12:
            break
    return tuple(seen)

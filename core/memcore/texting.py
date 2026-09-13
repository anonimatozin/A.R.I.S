"""Heurísticas de texto para a memória (entidades, fatos, tokenização).

Determinístico, barato e offline. Embeddings podem ser adicionados
depois; a busca tradicional continua funcionando sem eles.
"""

from __future__ import annotations

import re

_STOPWORDS_PT = {
    "a", "o", "as", "os", "de", "do", "da", "dos", "das", "em", "no", "na",
    "nos", "nas", "um", "uma", "uns", "umas", "e", "ou", "para", "por",
    "com", "sem", "que", "qual", "como", "quando", "onde", "porque", "mas",
    "me", "te", "se", "eu", "voce", "vc", "tu", "ele", "ela", "nos",
    "minha", "meu", "minhas", "seus", "sua", "suas", "isso", "isto", "aquilo",
    "este", "esta", "esse", "essa", "está", "estao", "nao", "não", "sim",
    "muito", "mais", "menos", "so", "só", "tb", "tambem", "tbm",
}

# Verbos que normalmente anunciam um fato estável (memória semântica).
_FACT_MARKERS = [
    "possui", "tem", "usa", "uso", "gosto", "prefiro", "adoro", "odeio",
    "meu nome", "me chamo", "me chamam", "sou", "é", "sao", "trabalho com",
    "estudo", "moro", "nasci", "quero", "faço", "faco", "usei", "instalei",
]

# Marcadores de correção/contradição.
_CONTRADICTION_MARKERS = [
    "na verdade", "agora uso", "nao uso", "não uso", "não gosto", "nao gosto",
    "troquei", "mudei para", "agora é", "na verdade eu",
    "esquece", "deixa de lado", "corrigindo", "me corrige",
]


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-záàâãéêíóôõúç]+", text.lower())
    return [w for w in words if w not in _STOPWORDS_PT and len(w) > 2]


def extract_entities(text: str, limit: int = 8) -> list[str]:
    """Extrai entidades simples (palavras significativas) do texto."""
    seen: list[str] = []
    for word in tokenize(text):
        if word not in seen:
            seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def is_fact_statement(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _FACT_MARKERS)


def is_contradiction(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _CONTRADICTION_MARKERS)


def similarity(a: str, b: str) -> float:
    """Similaridade determinística simples (coeficiente de Jaccard) entre tokens."""
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

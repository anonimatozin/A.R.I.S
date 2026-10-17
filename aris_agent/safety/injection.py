"""Detecção de padrões típicos de prompt injection em texto não confiável.

``scan_untrusted`` **não remove** nada: só sinaliza para o log de auditoria.
"""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignora_instrucoes",
        re.compile(
            r"ignore\s+(?:as|todas|o)?\s*instru[cç][oõ]es\s+(?:anteriores|do\s+sistema|acima|antigas)"
            r"|esque[cç]a\s+(?:as|todas|o)?\s*instru[cç][oõ]es"
            r"|disregard\s+(?:all|previous|the)?\s*instructions"
            r"|ignore\s+(?:previous|all|above)\s+instructions",
            re.IGNORECASE,
        ),
    ),
    (
        "executa_comando",
        re.compile(
            r"execute\s+este\s+comando|execute\s+o\s+comando\s+abaixo"
            r"|rode\s+o\s+comando\s+(?:a\s+seguir|abaixo)|executar\s+o\s+comando\s+seguinte"
            r"|run\s+(?:this|the\s+following)\s+command|execute\s+(?:this|the\s+following)\s+command",
            re.IGNORECASE,
        ),
    ),
    (
        "pega_credencial",
        re.compile(
            r"(?:envie|envia|informe|informa|mande|me\s+passe|me\s+mande|digite|cole|copie|forne[cç]a)"
            r"[^.\n]{0,80}(?:sua|a|o|as|os)?\s*(?:chave|senha|token|credencial|password|api[\s_-]?key)"
            r"|(?:api[\s_-]?key|senha|password|token)\s*(?:=|:)?\s*(?:aqui|sua\s+valor)",
            re.IGNORECASE,
        ),
    ),
    (
        "esconde_do_usuario",
        re.compile(
            r"n[ãa]o\s+(?:conte|avise|informe|mostre|mencione)\s+(?:ao|para\s+o)\s+usu[áa]rio"
            r"|sem\s+(?:informar|avisar|dizer\s+ao)\s+usu[áa]rio"
            r"|do\s+not\s+tell\s+(?:the\s+)?user",
            re.IGNORECASE,
        ),
    ),
    (
        "substitui_seguranca",
        re.compile(
            r"modo\s+(?:de\s+)?desenvolvedor|developer\s+mode|jailbreak"
            r"|ignore\s+(?:o\s+)?sistema\s+de\s+seguran[çc]a|system\s+prompt"
            r"|novas?\s+instru[cç][oõ]es\s*:|new\s+instructions\s*:",
            re.IGNORECASE,
        ),
    ),
)


def scan_untrusted(text: str) -> list[str]:
    """Rótulos dos padrões de injeção encontrados em ``text`` (lista vazia se limpo)."""
    if not text:
        return []
    return [label for label, pattern in _PATTERNS if pattern.search(text)]

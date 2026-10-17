"""Seleção de ferramentas por tarefa: núcleo sempre + grupos por palavras-chave.

Enviar as ~30 ferramentas em toda chamada custa tokens; aqui o laço manda só as
prováveis e aceita as demais se o modelo pedir (o agente inclui nas chamadas seguintes).
"""

from __future__ import annotations

import re

from ..contract.types import ToolSpec
from ..tools.registry import ToolRegistry
from .heuristics import normalize

# Núcleo: sempre enviado quando existe no registry.
CORE = ("skill_load", "memory_recall", "memory_remember", "plan_update", "calc")

MAX_TOOLS = 10

# tag -> palavras que ativam o grupo inteiro (expansão por tags).
GRUPOS: dict[str, tuple[str, ...]] = {
    "web": (
        "pesquis", "busca", "internet", "noticia", "site", "url", "http", "google",
        "previsao", "clima", "cotacao", "web", "wiki",
    ),
    "files": (
        "arquivo", "pasta", "diretorio", "salvar", "escrever", "documento", "ler",
        "txt", "csv", "renome",
    ),
    "pc": (
        "abrir", "fechar", "programa", "janela", "mouse", "teclado", "clique",
        "digitar", "executar", "rodar", "volume", "tela", "computador", "captura",
    ),
    "memory": ("lembre", "memoria", "guarde", "esqueca", "historico"),
    "skill": ("skill", "procedimento", "rotina"),
    "calc": ("calcule", "calculadora", "conta", "quanto", "multiplic", "soma"),
}

_PALAVRA_RE = re.compile(r"[a-z0-9]{4,}")


class ToolSelector:
    """Escolhe quais ToolSpec enviar ao LLM nesta chamada."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def select(self, user_text: str, used: tuple[str, ...] | list[str] = ()) -> list[ToolSpec]:
        """Núcleo + grupos ativados + ferramentas já usadas + as mais parecidas com o pedido."""
        todos = {spec.name: spec for spec in self._registry.specs()}
        escolhidas: dict[str, ToolSpec] = {}

        for nome in CORE:
            if nome in todos:
                escolhidas[nome] = todos[nome]

        texto = normalize(user_text)
        for tag, palavras in GRUPOS.items():
            if not any(p in texto for p in palavras):
                continue
            if any(tag in spec.tags for spec in todos.values()):
                for spec in todos.values():
                    if tag in spec.tags:
                        escolhidas[spec.name] = spec

        # Ferramenta já usada nesta tarefa volta a ser enviada.
        for nome in used:
            if nome in todos:
                escolhidas[nome] = todos[nome]

        palavras = _PALAVRA_RE.findall(texto)
        pontuadas: list[tuple[int, str, ToolSpec]] = []
        for nome, spec in todos.items():
            if nome in escolhidas:
                continue
            score = self._score(palavras, spec)
            if score > 0:
                pontuadas.append((score, nome, spec))
        pontuadas.sort(key=lambda t: (-t[0], t[1]))

        for _score, nome, spec in pontuadas:
            if len(escolhidas) >= MAX_TOOLS:
                break
            escolhidas[nome] = spec

        return list(escolhidas.values())

    @staticmethod
    def _score(palavras: list[str], spec: ToolSpec) -> int:
        alvo = normalize(f"{spec.name} {spec.description} {' '.join(spec.tags)}")
        return sum(1 for palavra in palavras if palavra in alvo)


__all__ = ["CORE", "GRUPOS", "MAX_TOOLS", "ToolSelector"]

"""Ferramentas de skills da A.R.I.S. (Parte 6).

A biblioteca entra por um ponto de injeção simples::

    from aris_agent.tools.skill_tools import set_library
    from aris_agent.skills import SkillLibrary

    set_library(SkillLibrary.from_config(cfg))   # chamado pela Parte 8

Sem biblioteca configurada, as ferramentas devolvem ``ToolResult(ok=False)``
com mensagem clara — nada de exceção para o laço do agente. Executar scripts
de skill é papel das ferramentas do PC (Parte 2), passando pelo executor de
segurança (Parte 5); aqui só documentamos o caminho do script no ``skill_load``.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ...contract.utils import truncate_text
from ...skills import SkillError
from ..registry import ToolRegistry, function_tool

if TYPE_CHECKING:
    from ...skills import SkillLibrary

log = logging.getLogger("aris.agent.tools.skill_tools")

__all__ = ["get_library", "register", "set_library"]

_lock = threading.Lock()
_library: SkillLibrary | None = None

_SKILL_LOAD_SPEC = ToolSpec(
    name="skill_load",
    description=(
        "Carrega o conteúdo completo de uma skill (instruções especializadas guardadas em "
        "pastas) pelo nome. Use quando a descrição de uma skill do catálogo combinar com a "
        "tarefa atual — antes de executar a tarefa. Devolve o corpo do SKILL.md e a lista de "
        "recursos disponíveis (scripts/, references/, assets/) com caminhos relativos."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "nome da skill como aparece no catálogo (ex.: 'pesquisa-web')",
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    risk=Risk.READ,
    tags=("skills",),
)

_SKILL_READ_RESOURCE_SPEC = ToolSpec(
    name="skill_read_resource",
    description=(
        "Lê um arquivo auxiliar de uma skill (pasta references/, assets/ ou scripts/) que o "
        "skill_load listou. O caminho é RELATIVO à pasta da skill, ex.: "
        "'references/modelo.md'. Use somente depois de skill_load listar o recurso; o caminho "
        "não pode sair da pasta da skill."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "nome da skill dona do arquivo",
            },
            "relative_path": {
                "type": "string",
                "description": "caminho relativo dentro da skill (ex.: 'references/modelo.md')",
            },
        },
        "required": ["name", "relative_path"],
        "additionalProperties": False,
    },
    risk=Risk.READ,
    path_args=("relative_path",),
    tags=("skills",),
)


def set_library(library: SkillLibrary | None) -> None:
    """Ponto de injeção: liga/desliga a biblioteca de skills usada pelas ferramentas."""
    global _library
    with _lock:
        _library = library
    log.info(
        "biblioteca de skills %s configurada nas ferramentas",
        type(library).__name__ if library is not None else "nenhuma",
    )


def get_library() -> SkillLibrary | None:
    """Biblioteca configurada (``None`` = ferramentas respondem ``ok=False``)."""
    with _lock:
        return _library


def _sem_biblioteca() -> ToolResult:
    return ToolResult(
        ok=False,
        error=(
            "biblioteca de skills não configurada: chame set_library(SkillLibrary(...)) em "
            "aris_agent.tools.skill_tools com uma instância de SkillLibrary"
        ),
    )


def _nome(args: dict) -> str | None:
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    return name.strip()


def _desconhecida(name: str, library: SkillLibrary) -> ToolResult:
    disponiveis = ", ".join(library.names()) or "(nenhuma skill cadastrada)"
    return ToolResult(ok=False, error=f"skill desconhecida: {name!r}. Disponíveis: {disponiveis}")


def _limite(ctx: ToolContext) -> int:
    try:
        return max(1, int(ctx.config.max_tool_chars))
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensivo
        return 8000


@function_tool(_SKILL_LOAD_SPEC)
def _skill_load(args: dict, ctx: ToolContext) -> ToolResult:
    library = get_library()
    if library is None:
        return _sem_biblioteca()
    name = _nome(args)
    if name is None:
        return ToolResult(ok=False, error="parâmetro 'name' obrigatório e não vazio")
    try:
        conteudo = library.load(name)
        recursos = library.resources(name)
    except KeyError:
        return _desconhecida(name, library)
    except (SkillError, OSError) as exc:
        return ToolResult(ok=False, error=f"não carreguei a skill {name}: {exc}")
    return ToolResult(
        ok=True,
        content=truncate_text(conteudo, _limite(ctx)),
        data={"name": name, "resources": list(recursos)},
    )


@function_tool(_SKILL_READ_RESOURCE_SPEC)
def _skill_read_resource(args: dict, ctx: ToolContext) -> ToolResult:
    library = get_library()
    if library is None:
        return _sem_biblioteca()
    name = _nome(args)
    if name is None:
        return ToolResult(ok=False, error="parâmetro 'name' obrigatório e não vazio")
    relative_path = args.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path.strip():
        return ToolResult(ok=False, error="parâmetro 'relative_path' obrigatório e não vazio")
    try:
        texto = library.read_resource(name, relative_path.strip())
    except KeyError:
        return _desconhecida(name, library)
    except (SkillError, OSError) as exc:
        return ToolResult(ok=False, error=str(exc))
    return ToolResult(
        ok=True,
        content=truncate_text(texto, _limite(ctx)),
        data={"name": name, "relative_path": relative_path.strip()},
    )


def register(registry: ToolRegistry) -> None:
    """Registra as ferramentas de skills (idempotente)."""
    for tool in (_skill_load, _skill_read_resource):
        if tool.spec.name not in registry:
            registry.register(tool)
    log.debug("ferramentas de skills registradas")

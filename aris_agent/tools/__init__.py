"""Auto-descoberta das ferramentas.

Convenção: todo subpacote de ``aris_agent.tools`` expõe
``def register(registry: ToolRegistry) -> None`` no seu ``__init__.py``.
Um subpacote que falhar ao importar (dependência ausente, por exemplo) gera
apenas um aviso em log: uma parte quebrada não pode derrubar as outras.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

from .registry import ToolRegistry, function_tool

log = logging.getLogger("aris.agent.tools")

__all__ = ["ToolRegistry", "discover", "function_tool"]


def discover(registry: ToolRegistry, package: ModuleType | None = None) -> list[str]:
    """Importa os subpacotes de ``package`` (padrão: ``aris_agent.tools``) e chama ``register``.

    Devolve a lista de subpacotes processados com sucesso.
    """
    pkg = package if package is not None else importlib.import_module(__name__)
    prefix = getattr(pkg, "__name__", __name__) + "."
    processed: list[str] = []
    for module_info in pkgutil.iter_modules(getattr(pkg, "__path__", [])):
        if not module_info.ispkg:
            continue
        name = module_info.name
        try:
            module = importlib.import_module(prefix + name)
        except Exception as exc:  # noqa: BLE001 - parte quebrada não pode derrubar as outras
            log.warning("subpacote de ferramentas %s falhou ao importar: %s", name, exc)
            continue
        register = getattr(module, "register", None)
        if not callable(register):
            log.debug("subpacote %s sem register(); nada a fazer", name)
            continue
        try:
            register(registry)
        except Exception as exc:  # noqa: BLE001
            log.warning("register() de %s falhou: %s", name, exc)
            continue
        processed.append(name)
        log.debug("ferramentas de %s registradas", name)
    return processed

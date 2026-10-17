"""Dono: Parte 3 — ferramentas de web (busca, leitura e navegador).

Expõe ``def register(registry)`` para a auto-descoberta de ``aris_agent.tools``.
Todos os textos devolvidos são conteúdo não confiável: cada ferramenta usa
``untrusted_output=True`` e envolve a saída em ``wrap_untrusted``.
"""

from __future__ import annotations

from ..registry import ToolRegistry


def register(registry: ToolRegistry) -> None:
    """Registra as 11 ferramentas de web (nomes fixos da Parte 3)."""
    from .browser import (
        browser_click,
        browser_close,
        browser_open,
        browser_press,
        browser_screenshot,
        browser_snapshot,
        browser_type,
    )
    from .pages import web_download, web_extract_links, web_fetch
    from .search import web_search as _web_search_tool

    for tool in (
        _web_search_tool,
        web_fetch,
        web_extract_links,
        web_download,
        browser_open,
        browser_snapshot,
        browser_click,
        browser_type,
        browser_press,
        browser_screenshot,
        browser_close,
    ):
        registry.register(tool)

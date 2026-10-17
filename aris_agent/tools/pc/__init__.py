"""Dono: Parte 2 — ferramentas do PC (Windows).

Exponha ``def register(registry)`` aqui para a auto-descoberta de ``aris_agent.tools``.
"""

from __future__ import annotations

from .apps import pc_open_app
from .calc import calc
from .clipboard import pc_clipboard_get, pc_clipboard_set
from .files import (
    pc_delete_file,
    pc_list_dir,
    pc_move_file,
    pc_read_file,
    pc_search_files,
    pc_write_file,
)
from .input_tools import pc_keys, pc_mouse
from .screenshot import pc_screenshot
from .shell import pc_python_run, pc_run_command
from .system import pc_list_processes, pc_system_info
from .ui import pc_ui_click, pc_ui_find, pc_ui_type
from .windows import pc_focus_window, pc_list_windows

# Ordem da tabela do PROMPT_PARTE_2 (nomes fixos, sem repetição).
TOOLS: tuple = (
    pc_system_info,
    pc_list_processes,
    pc_list_windows,
    pc_list_dir,
    pc_read_file,
    pc_search_files,
    pc_write_file,
    pc_move_file,
    pc_delete_file,
    pc_open_app,
    pc_focus_window,
    pc_run_command,
    pc_python_run,
    calc,
    pc_clipboard_get,
    pc_clipboard_set,
    pc_screenshot,
    pc_ui_find,
    pc_ui_click,
    pc_ui_type,
    pc_keys,
    pc_mouse,
)


def register(registry) -> None:
    """Registra todas as ferramentas do PC no registry do agente."""
    for tool in TOOLS:
        registry.register(tool)


__all__ = ["TOOLS", "register"]

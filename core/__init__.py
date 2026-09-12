"""Core do projeto A.R.I.S.

Este módulo contém os componentes centrais do sistema.
"""

from core.aris import Aris
from core.module_manager import ModuleManager
from core.commands import CommandRegistry

__all__ = ["Aris", "ModuleManager", "CommandRegistry"]

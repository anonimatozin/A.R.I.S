"""Core do projeto J.A.R.V.I.S.

Este módulo contém os componentes centrais do sistema.
"""

from core.jarvis import Jarvis
from core.module_manager import ModuleManager
from core.commands import CommandRegistry

__all__ = ["Jarvis", "ModuleManager", "CommandRegistry"]

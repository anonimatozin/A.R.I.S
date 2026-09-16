"""Security Layer — classificacao e validacao de acoes.

Classifica acoes em SAFE, CONFIRMATION_REQUIRED e BLOCKED.
Fornece funcao de validacao para o ToolExecutor.
"""
from __future__ import annotations

import re
from enum import Enum


class SecurityLevel(Enum):
    SAFE = "safe"
    CONFIRMATION_REQUIRED = "confirmation_required"
    BLOCKED = "blocked"


class SecurityAction:
    def __init__(self, name: str, level: SecurityLevel, description: str = "") -> None:
        self.name = name
        self.level = level
        self.description = description


_ACTIONS: dict[str, SecurityAction] = {}

SAFE_ACTIONS = [
    ("browser.open", "Abrir navegador/URL"),
    ("browser.search", "Pesquisar na web"),
    ("system.status", "Consultar status do sistema"),
    ("system.cpu", "Consultar uso de CPU"),
    ("system.memory", "Consultar uso de memoria"),
    ("system.disk", "Consultar disco"),
    ("system.processes", "Listar processos"),
    ("system.info", "Informacoes do sistema"),
    ("memory.store", "Armazenar memoria"),
    ("memory.search", "Buscar memoria"),
    ("memory.retrieve", "Recuperar memoria"),
    ("file.read", "Ler arquivo"),
    ("file.list", "Listar arquivos"),
    ("file.search", "Buscar arquivos"),
    ("reminder.create", "Criar lembrete"),
    ("reminder.list", "Listar lembretes"),
    ("reminder.cancel", "Cancelar lembrete"),
    ("search.web", "Pesquisar na web"),
    ("exec.safe", "Executar comando seguro"),
]

CONFIRMATION_ACTIONS = [
    ("system.shutdown", "Desligar PC"),
    ("system.restart", "Reiniciar PC"),
    ("system.schedule_shutdown", "Agendar desligamento"),
    ("system.schedule_wake", "Agendar ligamento"),
    ("file.delete", "Deletar arquivo"),
    ("file.move", "Mover arquivo"),
    ("file.write", "Escrever arquivo"),
    ("exec.confirm", "Executar comando com risco"),
    ("system.open_program", "Abrir programa"),
]

BLOCKED_ACTIONS = [
    ("exec.arbitrary", "Execucao arbitraria de codigo"),
    ("system.format", "Formatar disco"),
    ("system.delete_system", "Deletar arquivos do sistema"),
    ("security.disable", "Desabilitar seguranca"),
]


def _register_defaults():
    for name, desc in SAFE_ACTIONS:
        _ACTIONS[name] = SecurityAction(name, SecurityLevel.SAFE, desc)
    for name, desc in CONFIRMATION_ACTIONS:
        _ACTIONS[name] = SecurityAction(name, SecurityLevel.CONFIRMATION_REQUIRED, desc)
    for name, desc in BLOCKED_ACTIONS:
        _ACTIONS[name] = SecurityAction(name, SecurityLevel.BLOCKED, desc)


_register_defaults()


def classify_action(action_name: str) -> SecurityLevel:
    """Classifica nivel de seguranca de uma acao."""
    if action_name in _ACTIONS:
        return _ACTIONS[action_name].level

    for pattern, level in [
        (r"^browser\.", SecurityLevel.SAFE),
        (r"^memory\.", SecurityLevel.SAFE),
        (r"^reminder\.", SecurityLevel.SAFE),
        (r"^search\.", SecurityLevel.SAFE),
        (r"^system\.(status|cpu|memory|disk|info|processes)", SecurityLevel.SAFE),
        (r"^file\.(read|list|search)", SecurityLevel.SAFE),
        (r"^system\.(shutdown|restart|schedule)", SecurityLevel.CONFIRMATION_REQUIRED),
        (r"^file\.(delete|move|write)", SecurityLevel.CONFIRMATION_REQUIRED),
        (r"^exec\.", SecurityLevel.CONFIRMATION_REQUIRED),
        (r"^system\.(format|delete)", SecurityLevel.BLOCKED),
        (r"^security\.", SecurityLevel.BLOCKED),
    ]:
        if re.match(pattern, action_name):
            return level

    return SecurityLevel.CONFIRMATION_REQUIRED


def validate_action(action_name: str, confirmed: bool = False) -> dict:
    """Valida se acao pode ser executada.

    Returns:
        dict com "allowed", "level", "needs_confirmation", "message".
    """
    level = classify_action(action_name)

    if level == SecurityLevel.BLOCKED:
        return {
            "allowed": False,
            "level": "blocked",
            "needs_confirmation": False,
            "message": f"Acao bloqueada: {action_name}",
        }

    if level == SecurityLevel.CONFIRMATION_REQUIRED and not confirmed:
        action = _ACTIONS.get(action_name)
        desc = action.description if action else action_name
        return {
            "allowed": False,
            "level": "confirmation_required",
            "needs_confirmation": True,
            "message": f"Confirmacao necessaria: {desc}",
        }

    return {
        "allowed": True,
        "level": "safe" if level == SecurityLevel.SAFE else "confirmed",
        "needs_confirmation": False,
        "message": "Acao permitida.",
    }


def register_action(name: str, level: SecurityLevel, description: str = "") -> None:
    """Registra nova acao de seguranca."""
    _ACTIONS[name] = SecurityAction(name, level, description)


def get_all_actions() -> list[dict]:
    """Lista todas as acoes registradas."""
    return [
        {"name": a.name, "level": a.level.value, "description": a.description}
        for a in _ACTIONS.values()
    ]

"""ARIS Mode System — EDGE / PRIMARY / TRANSITIONING / UNKNOWN.

Determinado por heartbeat/handshake real, NUNCA por interpretacao do LLM.
A A.R.I.S. nunca finge ter uma capability que nao esta disponivel no modo atual.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any, Callable


class ARISMode(StrEnum):
    EDGE = "edge"
    PRIMARY = "primary"
    TRANSITIONING = "transitioning"
    UNKNOWN = "unknown"


class ModeTransition:
    """Registra uma transicao de modo."""

    def __init__(self, from_mode: ARISMode, to_mode: ARISMode, reason: str) -> None:
        self.from_mode = from_mode
        self.to_mode = to_mode
        self.reason = reason
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_mode.value,
            "to": self.to_mode.value,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class ModeManager:
    """Gerencia o modo de operacao da A.R.I.S.

    O modo e determinado exclusivamente por heartbeat/handshake real:
    - PC online via TCP heartbeat → PRIMARY
    - PC offline (3+ failures) → EDGE
    - Durante transicao → TRANSITIONING
    - Sem informacao → UNKNOWN
    """

    def __init__(self) -> None:
        self._mode = ARISMode.UNKNOWN
        self._previous_mode: ARISMode | None = None
        self._last_heartbeat: float = 0.0
        self._pc_online: bool = False
        self._consecutive_failures: int = 0
        self._transitions: list[ModeTransition] = []
        self._listeners: list[Callable[[ARISMode, ARISMode], None]] = []
        self._last_switch: float = 0.0
        # User override: quando o usuario contesta explicitamente o modo
        self._user_override: ARISMode | None = None
        self._user_override_time: float = 0.0
        self._user_override_ttl: float = 300.0  # 5 minutos

    @property
    def mode(self) -> ARISMode:
        # Verificar se user override expirou
        if self._user_override and (time.time() - self._user_override_time) > self._user_override_ttl:
            self._user_override = None
        return self._user_override or self._mode

    @property
    def raw_mode(self) -> ARISMode:
        """Modo real sem considerar user override."""
        return self._mode

    @property
    def previous_mode(self) -> ARISMode | None:
        return self._previous_mode

    @property
    def pc_online(self) -> bool:
        return self._pc_online

    @property
    def last_heartbeat(self) -> float:
        return self._last_heartbeat

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def transitions(self) -> list[ModeTransition]:
        return list(self._transitions)

    @property
    def has_user_override(self) -> bool:
        if self._user_override and (time.time() - self._user_override_time) > self._user_override_ttl:
            self._user_override = None
        return self._user_override is not None

    def on_transition(self, callback: Callable[[ARISMode, ARISMode], None]) -> None:
        """Registra callback para mudancas de modo."""
        self._listeners.append(callback)

    def update_heartbeat(self, pc_online: bool, reason: str = "heartbeat") -> ARISMode:
        """Atualiza estado baseado no heartbeat.

        Args:
            pc_online: Se o PC esta acessivel via TCP.
            reason: Motivo da atualizacao.

        Returns:
            Novo modo apos a transicao.
        """
        self._last_heartbeat = time.time()
        old_mode = self._mode
        self._pc_online = pc_online

        # Se há user override ativo, não mudar modo automaticamente
        if self.has_user_override:
            if self._logger:
                self._logger.debug(f"Modo protegido por user override: {self._user_override.value}")
            return self.mode

        if pc_online:
            self._consecutive_failures = 0
            if self._mode != ARISMode.PRIMARY:
                self._set_mode(ARISMode.PRIMARY, reason)
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3 and self._mode != ARISMode.EDGE:
                self._set_mode(ARISMode.EDGE, reason)
            elif self._consecutive_failures > 0 and self._mode == ARISMode.PRIMARY:
                self._set_mode(ARISMode.TRANSITIONING, reason)

        return self.mode

    def force_mode(self, mode: ARISMode, reason: str = "manual") -> None:
        """Forca um modo especifico (para testes/diagnostico)."""
        self._set_mode(mode, reason)

    def apply_user_feedback(self, user_says_pc_online: bool, reason: str = "user_feedback") -> ARISMode:
        """Aplica feedback do usuario sobre estado do PC.
        
        Quando o usuario diz explicitamente "o PC está ligado" ou "o PC está desligado",
        isso tem precedência sobre o heartbeat automático por um período (TTL).
        """
        if user_says_pc_online:
            self._user_override = ARISMode.PRIMARY
            self._user_override_time = time.time()
            self._pc_online = True
            self._consecutive_failures = 0
            if self._mode != ARISMode.PRIMARY:
                self._set_mode(ARISMode.PRIMARY, reason)
        else:
            self._user_override = ARISMode.EDGE
            self._user_override_time = time.time()
            self._pc_online = False
            self._consecutive_failures = 3
            if self._mode != ARISMode.EDGE:
                self._set_mode(ARISMode.EDGE, reason)
        
        if self._logger:
            self._logger.info(f"User feedback aplicado: PC {'online' if user_says_pc_online else 'offline'} -> modo {self._user_override.value}")
        return self.mode

    def clear_user_override(self) -> None:
        """Limpa override do usuario (volta para modo automatico)."""
        self._user_override = None
        self._user_override_time = 0.0

    def _set_mode(self, new_mode: ARISMode, reason: str) -> None:
        if new_mode == self._mode:
            return

        self._previous_mode = self._mode
        self._mode = new_mode
        self._last_switch = time.time()

        transition = ModeTransition(self._previous_mode, new_mode, reason)
        self._transitions.append(transition)
        if len(self._transitions) > 50:
            self._transitions = self._transitions[-50:]

        for listener in self._listeners:
            try:
                listener(self._previous_mode, new_mode)
            except Exception:
                pass

    def is_available(self, capability: str, capabilities_registry: Any = None) -> bool:
        """Verifica se uma capability esta disponivel no modo atual.

        Delega ao CapabilityRegistry se fornecido, senao usa regra basica.
        """
        current_mode = self.mode  # Usa mode (com user override)
        if capabilities_registry is not None:
            return capabilities_registry.is_available(capability, current_mode)
        if current_mode == ARISMode.PRIMARY:
            return True
        if current_mode == ARISMode.EDGE:
            edge_only = {
                "chat", "memory", "discord", "cll1_status", "cll1_system_info",
                "cll1_uptime", "cll1_disk", "cll1_memory", "cll1_cpu",
                "cll1_network", "cll1_process_list", "cll1_process_status",
                "cll1_service_list", "cll1_service_status", "cll1_logs",
                "cll1_list_files", "cll1_read_file", "cll1_search_files",
                "email_status", "email_list", "email_search", "email_read",
                "memory_add", "memory_get", "memory_search", "memory_state",
            }
            return capability in edge_only
        return False

    def snapshot(self) -> dict[str, Any]:
        """Estado atual do modo."""
        current_mode = self.mode
        return {
            "mode": current_mode.value,
            "raw_mode": self._mode.value,
            "previous_mode": self._previous_mode.value if self._previous_mode else None,
            "pc_online": self._pc_online,
            "consecutive_failures": self._consecutive_failures,
            "last_heartbeat": self._last_heartbeat,
            "last_switch": self._last_switch,
            "transitions_count": len(self._transitions),
            "user_override": self._user_override.value if self.has_user_override else None,
            "user_override_remaining": max(0, self._user_override_ttl - (time.time() - self._user_override_time)) if self.has_user_override else 0,
        }

    def describe(self) -> str:
        """Descricao textual do modo atual."""
        mode_names = {
            ARISMode.PRIMARY: "PRIMARY (PC online)",
            ARISMode.EDGE: "EDGE (PC offline)",
            ARISMode.TRANSITIONING: "TRANSITIONING",
            ARISMode.UNKNOWN: "UNKNOWN",
        }
        desc = mode_names.get(self.mode, self.mode.value)
        if self.has_user_override:
            remaining = max(0, int(self._user_override_ttl - (time.time() - self._user_override_time)))
            desc += f" [override do usuario: {self._user_override.value} por mais {remaining}s]"
        return desc


_mode_manager: ModeManager | None = None


def get_mode_manager() -> ModeManager:
    """Retorna a instancia singleton do ModeManager."""
    global _mode_manager
    if _mode_manager is None:
        _mode_manager = ModeManager()
    return _mode_manager


def reset_mode_manager() -> None:
    """Reseta o singleton do ModeManager (apenas para testes)."""
    global _mode_manager
    _mode_manager = None

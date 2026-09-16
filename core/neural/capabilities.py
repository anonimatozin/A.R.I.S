"""Capability Registry — capacidades disponiveis por modo.

EDGE: chat, memoria, Discord, status do CLL1, arquivos do CLL1, terminal
      seguro do CLL1, servicos do CLL1, logs, e-mail basico, configuracoes
      permitidas, monitoramento.
PRIMARY: tudo do EDGE + arquivos do Windows, terminal do Windows, programas,
         navegador, automacao, visao, tela, camera, hardware, ferramentas
         avancadas, agente completo, gerenciamento do projeto, ferramentas
         de desenvolvimento.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PermissionLevel(StrEnum):
    SAFE = "safe"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Capability:
    """Uma capability individual do sistema."""
    name: str
    description: str
    permission: PermissionLevel
    modes: tuple[str, ...]  # modos onde esta disponivel
    requires_confirmation: bool = False
    category: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission.value,
            "modes": list(self.modes),
            "requires_confirmation": self.requires_confirmation,
            "category": self.category,
        }


class CapabilityRegistry:
    """Registro central de capacidades por modo."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Registra todas as capabilities padrao do sistema."""
        # ── EDGE capabilities ─────────────────────────────────
        edge = ("edge", "primary")
        primary_only = ("primary",)

        # Chat & Memoria
        self.register(Capability("chat", "Conversa via LLM", PermissionLevel.SAFE, edge, category="core"))
        self.register(Capability("memory_add", "Adicionar memoria", PermissionLevel.SAFE, edge, category="memory"))
        self.register(Capability("memory_get", "Recuperar memoria", PermissionLevel.SAFE, edge, category="memory"))
        self.register(Capability("memory_search", "Buscar memorias", PermissionLevel.SAFE, edge, category="memory"))
        self.register(Capability("memory_state", "Estado da memoria", PermissionLevel.SAFE, edge, category="memory"))
        self.register(Capability("memory_sync", "Sincronizar memoria", PermissionLevel.MODERATE, edge, category="memory"))

        # Discord
        self.register(Capability("discord", "Bot Discord", PermissionLevel.SAFE, edge, category="communication"))

        # CLL1 — Status
        self.register(Capability("cll1_status", "Status geral do CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_system_info", "Info do sistema CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_uptime", "Uptime do CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_disk", "Uso de disco CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_memory", "Uso de memoria CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_cpu", "Uso de CPU CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_network", "Rede do CLL1", PermissionLevel.SAFE, edge, category="cll1"))

        # CLL1 — Processos
        self.register(Capability("cll1_process_list", "Listar processos CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_process_status", "Status de processo CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_process_stop", "Parar processo CLL1", PermissionLevel.HIGH, edge, category="cll1", requires_confirmation=True))

        # CLL1 — Servicos
        self.register(Capability("cll1_service_list", "Listar servicos CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_service_status", "Status de servico CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_service_restart", "Reiniciar servico CLL1", PermissionLevel.HIGH, edge, category="cll1", requires_confirmation=True))

        # CLL1 — Arquivos
        self.register(Capability("cll1_list_files", "Listar arquivos CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_read_file", "Ler arquivo CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_write_file", "Escrever arquivo CLL1", PermissionLevel.MODERATE, edge, category="cll1"))
        self.register(Capability("cll1_edit_file", "Editar arquivo CLL1", PermissionLevel.MODERATE, edge, category="cll1"))
        self.register(Capability("cll1_create_directory", "Criar diretorio CLL1", PermissionLevel.MODERATE, edge, category="cll1"))
        self.register(Capability("cll1_copy_file", "Copiar arquivo CLL1", PermissionLevel.MODERATE, edge, category="cll1"))
        self.register(Capability("cll1_move_file", "Mover arquivo CLL1", PermissionLevel.MODERATE, edge, category="cll1"))
        self.register(Capability("cll1_search_files", "Buscar arquivos CLL1", PermissionLevel.SAFE, edge, category="cll1"))

        # CLL1 — Terminal & Logs
        self.register(Capability("cll1_terminal", "Terminal seguro CLL1", PermissionLevel.HIGH, edge, category="cll1"))
        self.register(Capability("cll1_logs", "Logs do CLL1", PermissionLevel.SAFE, edge, category="cll1"))
        self.register(Capability("cll1_logs_search", "Buscar nos logs CLL1", PermissionLevel.SAFE, edge, category="cll1"))

        # CLL1 — Servicos
        self.register(Capability("cll1_services", "Gerenciar servicos CLL1", PermissionLevel.HIGH, edge, category="cll1"))

        # Email
        self.register(Capability("email_status", "Status do email", PermissionLevel.SAFE, edge, category="email"))
        self.register(Capability("email_list", "Listar emails", PermissionLevel.SAFE, edge, category="email"))
        self.register(Capability("email_search", "Buscar emails", PermissionLevel.SAFE, edge, category="email"))
        self.register(Capability("email_read", "Ler email", PermissionLevel.SAFE, edge, category="email"))
        self.register(Capability("email_mark_read", "Marcar como lido", PermissionLevel.SAFE, edge, category="email"))
        self.register(Capability("email_send", "Enviar email", PermissionLevel.CRITICAL, edge, category="email", requires_confirmation=True))
        self.register(Capability("email_reply", "Responder email", PermissionLevel.CRITICAL, edge, category="email", requires_confirmation=True))
        self.register(Capability("email_archive", "Arquivar email", PermissionLevel.MODERATE, edge, category="email"))
        self.register(Capability("email_move", "Mover email", PermissionLevel.MODERATE, edge, category="email"))

        # Config & Monitor
        self.register(Capability("config", "Configuracoes", PermissionLevel.MODERATE, edge, category="system"))
        self.register(Capability("monitor", "Monitoramento", PermissionLevel.SAFE, edge, category="system"))
        self.register(Capability("health", "Health checks", PermissionLevel.SAFE, edge, category="system"))
        self.register(Capability("backup", "Backup/Restore", PermissionLevel.HIGH, edge, category="system", requires_confirmation=True))

        # ── PRIMARY-only capabilities ─────────────────────────
        # PC — Arquivos
        self.register(Capability("pc_list_files", "Listar arquivos PC", PermissionLevel.SAFE, primary_only, category="pc"))
        self.register(Capability("pc_read_file", "Ler arquivo PC", PermissionLevel.SAFE, primary_only, category="pc"))
        self.register(Capability("pc_write_file", "Escrever arquivo PC", PermissionLevel.MODERATE, primary_only, category="pc"))
        self.register(Capability("pc_edit_file", "Editar arquivo PC", PermissionLevel.MODERATE, primary_only, category="pc"))
        self.register(Capability("pc_create_directory", "Criar diretorio PC", PermissionLevel.MODERATE, primary_only, category="pc"))
        self.register(Capability("pc_search_files", "Buscar arquivos PC", PermissionLevel.SAFE, primary_only, category="pc"))
        self.register(Capability("pc_copy_file", "Copiar arquivo PC", PermissionLevel.MODERATE, primary_only, category="pc"))
        self.register(Capability("pc_move_file", "Mover arquivo PC", PermissionLevel.MODERATE, primary_only, category="pc"))
        self.register(Capability("pc_delete_file", "Deletar arquivo PC", PermissionLevel.HIGH, primary_only, category="pc", requires_confirmation=True))

        # PC — Terminal & Sistema
        self.register(Capability("pc_run_command", "Executar comando PC", PermissionLevel.HIGH, primary_only, category="pc"))
        self.register(Capability("pc_processes", "Processos do PC", PermissionLevel.SAFE, primary_only, category="pc"))
        self.register(Capability("pc_services", "Servicos do PC", PermissionLevel.SAFE, primary_only, category="pc"))
        self.register(Capability("pc_logs", "Logs do PC", PermissionLevel.SAFE, primary_only, category="pc"))
        self.register(Capability("pc_system_status", "Status do PC", PermissionLevel.SAFE, primary_only, category="pc"))

        # PC — Controle (H)
        self.register(Capability("pc_shutdown", "Desligar PC", PermissionLevel.CRITICAL, primary_only, category="pc_control", requires_confirmation=True))
        self.register(Capability("pc_restart", "Reiniciar PC", PermissionLevel.CRITICAL, primary_only, category="pc_control", requires_confirmation=True))
        self.register(Capability("pc_lock", "Bloquear PC", PermissionLevel.HIGH, primary_only, category="pc_control"))
        self.register(Capability("pc_sleep", "Suspender PC", PermissionLevel.HIGH, primary_only, category="pc_control"))

        # Wake-on-LAN (G)
        self.register(Capability("wake_on_lan", "Ligar PC remotamente", PermissionLevel.CRITICAL, ("edge",), category="wol", requires_confirmation=True))

        # PC — Avancado
        self.register(Capability("pc_browser", "Navegador", PermissionLevel.MODERATE, primary_only, category="pc_advanced"))
        self.register(Capability("pc_vision", "Visao/OCR", PermissionLevel.MODERATE, primary_only, category="pc_advanced"))
        self.register(Capability("pc_camera", "Camera", PermissionLevel.MODERATE, primary_only, category="pc_advanced"))
        self.register(Capability("pc_hardware", "Hardware/ESP32", PermissionLevel.MODERATE, primary_only, category="pc_advanced"))

        # Projeto (K)
        self.register(Capability("project_read", "Ler arquivo projeto", PermissionLevel.SAFE, primary_only, category="project"))
        self.register(Capability("project_write", "Escrever arquivo projeto", PermissionLevel.MODERATE, primary_only, category="project"))
        self.register(Capability("project_edit", "Editar arquivo projeto", PermissionLevel.MODERATE, primary_only, category="project"))
        self.register(Capability("project_grep", "Buscar no codigo", PermissionLevel.SAFE, primary_only, category="project"))
        self.register(Capability("project_glob", "Listar arquivos projeto", PermissionLevel.SAFE, primary_only, category="project"))
        self.register(Capability("project_terminal", "Terminal do projeto", PermissionLevel.HIGH, primary_only, category="project"))
        self.register(Capability("project_test", "Rodar testes", PermissionLevel.HIGH, primary_only, category="project"))
        self.register(Capability("project_git_status", "Git status", PermissionLevel.SAFE, primary_only, category="project"))
        self.register(Capability("project_git_diff", "Git diff", PermissionLevel.SAFE, primary_only, category="project"))

        # Agent Loop (E)
        self.register(Capability("agent_loop", "Agent Loop autonomo", PermissionLevel.HIGH, primary_only, category="agent"))

        # Intelligence Tools (internal)
        intel_modes = ("edge", "primary")
        self.register(Capability("intel_search", "Busca web simples", PermissionLevel.SAFE, intel_modes, category="intelligence"))
        self.register(Capability("intel_research", "Pesquisa aprofundada", PermissionLevel.SAFE, intel_modes, category="intelligence"))
        self.register(Capability("intel_verify", "Verificacao de fatos", PermissionLevel.SAFE, intel_modes, category="intelligence"))
        self.register(Capability("intel_compare", "Comparacao lado a lado", PermissionLevel.SAFE, intel_modes, category="intelligence"))
        self.register(Capability("intel_latest", "Noticias recentes", PermissionLevel.SAFE, intel_modes, category="intelligence"))

    def register(self, capability: Capability) -> None:
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def is_available(self, name: str, mode: Any) -> None:
        """Verifica se uma capability esta disponivel no modo."""
        from core.neural.mode import ARISMode
        cap = self._capabilities.get(name)
        if cap is None:
            return False
        mode_value = mode.value if isinstance(mode, ARISMode) else str(mode)
        return mode_value in cap.modes

    def available_in_mode(self, mode: Any) -> list[Capability]:
        """Retorna todas as capabilities disponiveis no modo."""
        from core.neural.mode import ARISMode
        mode_value = mode.value if isinstance(mode, ARISMode) else str(mode)
        return [c for c in self._capabilities.values() if mode_value in c.modes]

    def by_category(self, mode: Any | None = None) -> dict[str, list[Capability]]:
        """Agrupa capabilities por categoria."""
        caps = self._capabilities.values()
        if mode is not None:
            from core.neural.mode import ARISMode
            mode_value = mode.value if isinstance(mode, ARISMode) else str(mode)
            caps = [c for c in caps if mode_value in c.modes]
        result: dict[str, list[Capability]] = {}
        for cap in caps:
            result.setdefault(cap.category, []).append(cap)
        return result

    def requires_confirmation(self, name: str) -> bool:
        cap = self._capabilities.get(name)
        return cap.requires_confirmation if cap else False

    def get_permission(self, name: str) -> PermissionLevel | None:
        cap = self._capabilities.get(name)
        return cap.permission if cap else None

    def to_dict(self, mode: Any | None = None) -> dict[str, Any]:
        """Serializa capabilities para API/dashboard."""
        from core.neural.mode import ARISMode
        result = {}
        for name, cap in self._capabilities.items():
            if mode is not None:
                mode_value = mode.value if isinstance(mode, ARISMode) else str(mode)
                if mode_value not in cap.modes:
                    continue
            result[name] = cap.to_dict()
        return result


_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
    return _registry

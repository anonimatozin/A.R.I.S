"""Command Registry do J.A.R.V.I.S.

Registry central de comandos com suporte a decorators e safety.
Cada módulo se auto-registra via @registry.register().
"""

from typing import Callable, Any, Optional


class CommandRegistry:
    """Registro central de comandos do sistema.

    Suporta:
    1. Text commands (legado): "help", "exit" — registrados via register()
    2. Intent handlers (novo): module="weather" — registrados via register_intent()
    3. Safety levels: mapeamento de módulo → nível de segurança
    """

    def __init__(self):
        self._commands: dict[str, Callable] = {}
        self._command_meta: dict[str, dict] = {}
        self._intent_handlers: dict[str, Callable] = {}
        self._intent_meta: dict[str, dict] = {}
        self._safety_manager = None
        self._safety_levels: dict[str, int] = {}  # module → SafetyLevel value
        self._pending_confirmation: dict[str, dict] = {}  # token → {module, action, params, ctx}

    # ── Text commands (legado) ──────────────────────────────

    def register(self, name: str, description: str = "", aliases: list[str] | None = None):
        """Decorator para registrar um comando de texto."""
        def decorator(func):
            self._commands[name] = func
            self._command_meta[name] = {
                "description": description,
                "aliases": aliases or [],
            }
            for alias in (aliases or []):
                self._commands[alias] = func
            return func
        return decorator

    def execute_text(self, text: str) -> bool:
        """Executa um comando de texto (legado)."""
        parts = text.strip().split()
        if not parts:
            return False

        cmd_name = parts[0].lower()
        handler = self._commands.get(cmd_name)
        if handler is None:
            return False

        try:
            handler(*parts[1:])
            return True
        except Exception as e:
            print(f"  Erro ao executar '{cmd_name}': {e}")
            return False

    # ── Intent handlers (novo) ──────────────────────────────

    def register_intent(self, module: str, description: str = ""):
        """Decorator para registrar um handler de intenção por módulo."""
        def decorator(func):
            self._intent_handlers[module] = func
            self._intent_meta[module] = {"description": description}
            return func
        return decorator

    def execute_intent(self, module: str, action: str, params: dict, **ctx) -> str | None:
        """Executa um handler de intenção com verificação de safety.

        Fluxo:
        1. Verificar safety level do módulo
        2. Se CRITICAL e sem confirmação → retornar pendência
        3. Se confirmado → executar
        4. Senão → executar diretamente
        """
        handler = self._intent_handlers.get(module)
        if handler is None:
            return None

        # Safety check
        if self._safety_manager:
            safety_level = self._get_safety_level(module)
            from modules.safety import SafetyLevel

            if safety_level >= SafetyLevel.CRITICAL.value:
                # Precisa de confirmação e/ou senha
                confirmed = params.get("_confirmed", False)
                password = params.get("_password", "")

                if not confirmed:
                    token = f"{module}_{action}"
                    self._pending_confirmation[token] = {
                        "module": module,
                        "action": action,
                        "params": params,
                        "ctx": ctx,
                    }
                    return f"⚠️ Ação CRITICAL requer confirmação. Responda 'sim' para confirmar."

                if not self._safety_manager.check_password(password):
                    return "❌ Senha incorreta. Ação negada."

                self._safety_manager._log_audit(f"{module}/{action}", "critical_approved")

            elif safety_level >= SafetyLevel.DANGER.value:
                self._safety_manager._log_audit(f"{module}/{action}", "danger_executed")

        try:
            result = handler(action=action, params=params, **ctx)
            return result
        except Exception as e:
            return f"Erro ao executar {module}/{action}: {e}"

    def confirm_pending(self, token: str, confirmed: bool = True, password: str = "") -> str | None:
        """Confirma uma ação pendente.

        Returns:
            Resultado da execução ou None se token inválido.
        """
        pending = self._pending_confirmation.pop(token, None)
        if pending is None:
            return None

        if not confirmed:
            return "Ação cancelada pelo operador."

        pending["params"]["_confirmed"] = True
        pending["params"]["_password"] = password
        return self.execute_intent(**pending)

    def has_pending_confirmation(self) -> bool:
        return len(self._pending_confirmation) > 0

    def get_pending_tokens(self) -> list[str]:
        return list(self._pending_confirmation.keys())

    def has_intent(self, module: str) -> bool:
        return module in self._intent_handlers

    # ── Safety configuration ────────────────────────────────

    def set_safety(self, safety_manager) -> None:
        """Conecta o SafetyManager ao registry."""
        self._safety_manager = safety_manager

    def register_safety_level(self, module: str, level: int) -> None:
        """Define o safety level de um módulo (1=SAFE, 2=CAUTION, 3=DANGER, 4=CRITICAL)."""
        self._safety_levels[module] = level

    def _get_safety_level(self, module: str) -> int:
        """Retorna o safety level de um módulo."""
        if module in self._safety_levels:
            return self._safety_levels[module]
        # Default: CAUTION para módulos não mapeados
        return 2

    # ── Utilidades ──────────────────────────────────────────

    def list_commands(self) -> list[tuple[str, str, list[str]]]:
        result = []
        seen = set()
        for name, meta in self._command_meta.items():
            if name not in seen:
                result.append((name, meta["description"], meta["aliases"]))
                seen.add(name)
        return result

    def list_intents(self) -> list[tuple[str, str]]:
        return [
            (module, meta["description"])
            for module, meta in self._intent_meta.items()
        ]

    def has_command(self, name: str) -> bool:
        return name in self._commands


# Instância global
registry = CommandRegistry()

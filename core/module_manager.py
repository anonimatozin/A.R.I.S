"""Sistema de gerenciamento de módulos do A.R.I.S.

Responsável por carregar, descarregar e gerenciar módulos do sistema.
Suporta módulos internos (modules/) e plugins externos (plugins/).
"""

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from utils.logger import Logger


class ModuleInfo:
    """Informações sobre um módulo carregado."""

    def __init__(self, name: str, instance: Any, enabled: bool = True, is_plugin: bool = False) -> None:
        self.name = name
        self.instance = instance
        self.enabled = enabled
        self.is_plugin = is_plugin

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        kind = "plugin" if self.is_plugin else "module"
        return f"ModuleInfo(name={self.name!r}, status={status}, kind={kind})"


class ModuleManager:
    """Gerenciador central de módulos e plugins.

    Carrega automaticamente:
    - Módulos do diretório modules/
    - Plugins do diretório plugins/

    Registro explícito (DI):
    Módulos cujos construtores possuem dependências reais (contextos,
    credenciais, pastas de dados) NÃO são instanciados por heurística.
    Eles são fornecidos pela aplicação através do container
    (``register_services``) e registrados aqui explicitamente — nada
    de aliases/gambiarras por nome de classe.
    """

    # Nome do módulo → chave do serviço no container.
    # Módulos com dependências são instanciados pelo ARIS e
    # registrados no container central.
    DI_MODULE_BINDINGS: dict[str, str] = {
        "chat": "modules.chat",
        "knowledge_graph": "modules.knowledge",
        "scheduler": "modules.scheduler",
        "notifications": "modules.notifications",
        "safety": "modules.safety",
        "multi_agent": "modules.agents",
        "esp32_hardware": "modules.hardware",
    }

    def __init__(self, modules_dir: Path, plugins_dir: Path, logger: Logger) -> None:
        self._modules_dir = modules_dir
        self._plugins_dir = plugins_dir
        self._logger = logger
        self._modules: dict[str, ModuleInfo] = {}
        self._container = None

    @property
    def loaded_modules(self) -> dict[str, ModuleInfo]:
        return self._modules.copy()

    @property
    def module_count(self) -> int:
        return len(self._modules)

    def load_modules(self, container=None) -> None:
        """Carrega módulos internos e plugins externos.

        Args:
            container: Container de dependências (DI). Quando presente,
                módulos regidos por ``register_services`` são carregados
                explicitamente a partir dele.
        """
        self._container = container
        self._logger.info("Carregando módulos e plugins...")
        self._load_internal_modules()
        self._load_plugins()
        if container is not None:
            self._register_di_modules()
        self._logger.info(f"Total carregado: {self.module_count} ({self.plugin_count} plugins)")

    @property
    def plugin_count(self) -> int:
        return sum(1 for m in self._modules.values() if m.is_plugin)

    # ── Internal modules (modules/) ─────────────────────────

    def _load_internal_modules(self) -> None:
        """Carrega todos os módulos do diretório modules/."""
        modules_init = self._modules_dir / "__init__.py"
        if not modules_init.exists():
            self._logger.warning("Diretório de módulos vazio ou inválido.")
            return

        for module_file in sorted(self._modules_dir.glob("*.py")):
            if module_file.name.startswith("_"):
                continue

            module_name = module_file.stem
            try:
                self._load_single_module(module_name, module_file, is_plugin=False)
            except Exception as e:
                self._logger.error(f"Erro ao carregar módulo '{module_name}': {e}")

    def _load_single_module(self, name: str, file_path: Path, is_plugin: bool = False) -> None:
        """Carrega um único módulo."""
        prefix = "plugins" if is_plugin else "modules"
        module_name = f"{prefix}.{name}"

        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            self._logger.warning(f"Não foi possível criar spec para '{name}'.")
            return

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Auto-registro via registry (para plugins)
        if is_plugin:
            self._try_plugin_register(module, name)

        # Hook DI: módulo pode publicar serviços no container
        if self._container is not None:
            self._try_register_services(module, name)

        # Módulo regido por DI: instância fornecida pela aplicação
        if name in self.DI_MODULE_BINDINGS:
            self._logger.debug(f"Módulo '{name}': registro via injeção de dependências (DI).")
            return

        # Criar instância
        instance = self._create_module_instance(module, name)
        if instance is not None:
            self._modules[name] = ModuleInfo(
                name=name, instance=instance, is_plugin=is_plugin,
            )
            self._logger.debug(f"{'Plugin' if is_plugin else 'Módulo'} '{name}' carregado.")

    # ── External plugins (plugins/) ─────────────────────────

    def _load_plugins(self) -> None:
        """Carrega todos os plugins do diretório plugins/."""
        if not self._plugins_dir.exists():
            self._plugins_dir.mkdir(parents=True, exist_ok=True)
            self._logger.info("Diretório de plugins criado.")
            return

        for plugin_file in sorted(self._plugins_dir.glob("*.py")):
            if plugin_file.name.startswith("_"):
                continue

            plugin_name = plugin_file.stem
            if plugin_name in self._modules:
                self._logger.warning(f"Plugin '{plugin_name}' conflita com módulo interno. Pulando.")
                continue

            try:
                self._load_single_module(plugin_name, plugin_file, is_plugin=True)
            except Exception as e:
                self._logger.error(f"Erro ao carregar plugin '{plugin_name}': {e}")

    def _try_plugin_register(self, module: Any, name: str) -> None:
        """Tenta chamar register(registry) do plugin para auto-registro."""
        try:
            from core.commands import registry
            register_fn = getattr(module, "register", None)
            if callable(register_fn):
                register_fn(registry)
                self._logger.debug(f"Plugin '{name}' registrado via register().")
        except Exception as e:
            self._logger.warning(f"Plugin '{name}' não pôde se auto-registrar: {e}")

    def _try_register_services(self, module: Any, name: str) -> None:
        """Chama o hook ``register_services(container)`` se existir.

        Hook oficial de injeção de dependências: o módulo publica seus
        serviços no container central.
        """
        try:
            register_fn = getattr(module, "register_services", None)
            if callable(register_fn):
                register_fn(self._container)
                self._logger.debug(f"Módulo '{name}' registrou serviços via register_services().")
        except Exception as e:
            self._logger.warning(f"Módulo '{name}' não pôde registrar serviços: {e}")

    def _register_di_modules(self) -> None:
        """Registra módulos instanciados pela aplicação (DI explícita).

        Resolve a instância do container e a expõe ao ModuleManager,
        de forma que o gerenciador reflita o sistema real.
        """
        for module_name, service_key in self.DI_MODULE_BINDINGS.items():
            if module_name in self._modules:
                continue
            instance = self._container.get(service_key) if self._container else None
            if instance is not None:
                self._modules[module_name] = ModuleInfo(name=module_name, instance=instance)
                self._logger.info(f"Módulo '{module_name}' carregado via DI (container).")
            else:
                self._logger.warning(f"Módulo '{module_name}' indisponível no container (DI).")

    # ── Instance creation ───────────────────────────────────

    def _create_module_instance(self, module: Any, name: str) -> Any:
        """Cria uma instância do módulo.

        Dependências OPCIONAIS ausentes (ImportError, ex.: discord.py não
        instalado) logam INFO — não é erro, é recurso desativado. Outras
        exceções seguem como ERROR.
        """
        class_name = "".join(word.capitalize() for word in name.split("_"))

        def _log_optional_or_error(label: str, exc: Exception) -> None:
            if isinstance(exc, ImportError):
                self._logger.info(f"Módulo {label} desativado (dependência opcional ausente): {exc}")
            else:
                self._logger.error(f"Erro ao instanciar {label}: {exc}")

        if hasattr(module, class_name):
            cls = getattr(module, class_name)
            try:
                return cls()
            except Exception as e:
                _log_optional_or_error(class_name, e)
                return None

        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, "execute"):
                try:
                    return attr()
                except Exception as e:
                    _log_optional_or_error(attr_name, e)
                    return None

        return None

    # ── Management ──────────────────────────────────────────

    def get_module(self, name: str) -> ModuleInfo | None:
        return self._modules.get(name)

    def unload_module(self, name: str) -> bool:
        if name in self._modules:
            del self._modules[name]
            module_key = f"modules.{name}"
            if module_key in sys.modules:
                del sys.modules[module_key]
            self._logger.info(f"Módulo '{name}' descarregado.")
            return True
        return False

    def list_plugins(self) -> list[ModuleInfo]:
        """Retorna apenas os plugins carregados."""
        return [m for m in self._modules.values() if m.is_plugin]

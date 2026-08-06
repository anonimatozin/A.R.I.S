"""Sistema de gerenciamento de módulos do J.A.R.V.I.S.

Responsável por carregar, descarregar e gerenciar módulos do sistema.
"""

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from utils.logger import Logger


class ModuleInfo:
    """Informações sobre um módulo carregado.

    Attributes:
        name: Nome do módulo.
        instance: Instância do módulo.
        enabled: Se o módulo está habilitado.
    """

    def __init__(self, name: str, instance: Any, enabled: bool = True) -> None:
        self.name = name
        self.instance = instance
        self.enabled = enabled

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"ModuleInfo(name={self.name!r}, status={status})"


class ModuleManager:
    """Gerenciador central de módulos.

    Carrega automaticamente módulos do diretório modules/
    e gerencia plugins do diretório plugins/.
    """

    def __init__(self, modules_dir: Path, plugins_dir: Path, logger: Logger) -> None:
        """Inicializa o gerenciador de módulos.

        Args:
            modules_dir: Caminho para o diretório de módulos.
            plugins_dir: Caminho para o diretório de plugins.
            logger: Instância do logger.
        """
        self._modules_dir = modules_dir
        self._plugins_dir = plugins_dir
        self._logger = logger
        self._modules: dict[str, ModuleInfo] = {}

    @property
    def loaded_modules(self) -> dict[str, ModuleInfo]:
        """Retorna os módulos carregados."""
        return self._modules.copy()

    @property
    def module_count(self) -> int:
        """Retorna a quantidade de módulos carregados."""
        return len(self._modules)

    def load_modules(self) -> None:
        """Carrega todos os módulos do diretório modules/."""
        self._logger.info("Carregando módulos...")

        modules_init = self._modules_dir / "__init__.py"
        if not modules_init.exists():
            self._logger.warning("Diretório de módulos vazio ou inválido.")
            return

        # Carrega módulos Python do diretório
        for module_file in sorted(self._modules_dir.glob("*.py")):
            if module_file.name.startswith("_"):
                continue

            module_name = module_file.stem
            try:
                self._load_single_module(module_name, module_file)
            except Exception as e:
                self._logger.error(f"Erro ao carregar módulo '{module_name}': {e}")

        self._logger.info(f"Módulos carregados: {self.module_count}")

    def _load_single_module(self, name: str, file_path: Path) -> None:
        """Carrega um único módulo.

        Args:
            name: Nome do módulo.
            file_path: Caminho para o arquivo do módulo.
        """
        module_name = f"modules.{name}"

        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            self._logger.warning(f"Não foi possível criar spec para '{name}'.")
            return

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Procura por uma classe BaseModule ou similar
        instance = self._create_module_instance(module, name)
        if instance is not None:
            self._modules[name] = ModuleInfo(name=name, instance=instance)
            self._logger.debug(f"Módulo '{name}' carregado com sucesso.")

    def _create_module_instance(self, module: Any, name: str) -> Any:
        """Cria uma instância do módulo.

        Procura por uma classe que implemente a interface de módulo.
        """
        # Procura por classe com nome PascalCase do módulo
        class_name = "".join(word.capitalize() for word in name.split("_"))

        if hasattr(module, class_name):
            cls = getattr(module, class_name)
            try:
                return cls()
            except Exception as e:
                self._logger.error(f"Erro ao instanciar {class_name}: {e}")
                return None

        # Fallback: procura por qualquer classe pública
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, "execute"):
                try:
                    return attr()
                except Exception as e:
                    self._logger.error(f"Erro ao instanciar {attr_name}: {e}")
                    return None

        self._logger.warning(f"Nenhuma classe de módulo encontrada em '{name}'.")
        return None

    def get_module(self, name: str) -> ModuleInfo | None:
        """Retorna um módulo pelo nome.

        Args:
            name: Nome do módulo.

        Returns:
            Informações do módulo ou None se não encontrado.
        """
        return self._modules.get(name)

    def unload_module(self, name: str) -> bool:
        """Descarrega um módulo.

        Args:
            name: Nome do módulo.

        Returns:
            True se descarregado com sucesso.
        """
        if name in self._modules:
            del self._modules[name]
            module_key = f"modules.{name}"
            if module_key in sys.modules:
                del sys.modules[module_key]
            self._logger.info(f"Módulo '{name}' descarregado.")
            return True
        return False

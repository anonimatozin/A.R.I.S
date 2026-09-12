"""Contêiner de dependências (Dependency Injection) do A.R.I.S.

O contêiner central registra e resolve serviços de forma explícita:

- ``set(name, instance)``      : singleton já construído.
- ``register_factory(name, factory)`` : construção preguiçosa.

A resolução de dependências é feita pela factory no momento da
obtenção, permitindo inicialização incremental e evitando acoplamento
entre módulos. Não há descoberta por nome de classe aqui: cada serviço
declara explicitamente sua identidade e dependências.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


class ServiceNotFoundError(Exception):
    """Erro ao solicitar um serviço não registrado."""


class ServiceContainer:
    """Contêiner central de serviços.

    Cada serviço é registrado uma única vez, por nome. A resolução é
    preguiçosa: a factory só é executada no primeiro ``get``.
    """

    def __init__(self) -> None:
        self._instances: dict[str, Any] = {}
        self._factories: dict[str, Callable[[ServiceContainer], Any]] = {}
        self._dependencies: dict[str, list[str]] = {}

    # ── Registro ─────────────────────────────────────────────

    def set(self, name: str, instance: Any) -> Any:
        """Registra um singleton já construído."""
        self._instances[name] = instance
        self._factories.pop(name, None)
        return instance

    def register_factory(
        self,
        name: str,
        factory: Callable[[ServiceContainer], Any],
        depends_on: Iterable[str] | None = None,
    ) -> None:
        """Registra uma factory preguiçosa.

        Args:
            name: Nome canônico do serviço.
            factory: Fábrica que recebe o próprio contêiner.
            depends_on: Nomes dos serviços dos quais depende (declarativo).
        """
        self._factories[name] = factory
        if depends_on is not None:
            self._dependencies[name] = list(depends_on)
        self._instances.pop(name, None)

    def unregister(self, name: str) -> None:
        """Remove um serviço do contêiner."""
        self._instances.pop(name, None)
        self._factories.pop(name, None)
        self._dependencies.pop(name, None)

    # ── Consulta ─────────────────────────────────────────────

    def has(self, name: str) -> bool:
        """Verifica se o serviço está registrado (instância ou factory)."""
        return name in self._instances or name in self._factories

    def names(self) -> list[str]:
        """Lista os nomes de serviços registrados."""
        return sorted(set(self._instances) | set(self._factories))

    def registered_count(self) -> int:
        """Quantidade de serviços registrados."""
        return len(self.names())

    def dependencies_of(self, name: str) -> list[str]:
        """Retorna as dependências declaradas de um serviço."""
        return list(self._dependencies.get(name, []))

    # ── Resolução ────────────────────────────────────────────

    def get(self, name: str, default: Any = None) -> Any:
        """Resolve um serviço.

        Se a factory ainda não foi executada, ela é executada agora
        e o resultado passa a ser o singleton do serviço.
        """
        if name in self._instances:
            return self._instances[name]

        factory = self._factories.get(name)
        if factory is None:
            return default

        instance = factory(self)
        self._instances[name] = instance
        self._factories.pop(name, None)
        return instance

    def require(self, name: str) -> Any:
        """Resolve um serviço exigindo que ele exista."""
        instance = self.get(name)
        if instance is None:
            raise ServiceNotFoundError(
                f"Serviço '{name}' não registrado. "
                f"Registrados: {', '.join(self.names()) or 'nenhum'}."
            )
        return instance

    def try_build(self, name: str) -> bool:
        """Força a construção de um serviço preguiçoso.

        Returns:
            True se o serviço pôde ser construído.
        """
        try:
            self.require(name)
            return True
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"ServiceContainer({self.registered_count()} serviços)"

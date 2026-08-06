"""Sistema de comandos do J.A.R.V.I.S.

Registra e executa comandos disponíveis no terminal.
Suporta argumentos e aliases.
"""

from typing import Callable, Any
import shlex

from utils.logger import Logger
from utils.terminal import Terminal


class Command:
    """Representa um comando registrado.

    Attributes:
        name: Nome do comando.
        description: Descrição do comando.
        callback: Função a ser executada.
        aliases: Lista de aliases do comando.
    """

    def __init__(
        self,
        name: str,
        description: str,
        callback: Callable[..., Any],
        aliases: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.callback = callback
        self.aliases = aliases or []

    def execute(self, *args: str) -> Any:
        """Executa o comando com argumentos.

        Args:
            *args: Argumentos passados ao comando.
        """
        return self.callback(*args)

    def __repr__(self) -> str:
        return f"Command(name={self.name!r}, aliases={self.aliases})"


class CommandRegistry:
    """Registro central de comandos.

    Gerencia o cadastro e execução de comandos do sistema.
    Suporta argumentos e aliases.
    """

    def __init__(self, logger: Logger) -> None:
        """Inicializa o registro de comandos.

        Args:
            logger: Instância do logger.
        """
        self._commands: dict[str, Command] = {}
        self._aliases: dict[str, str] = {}
        self._logger = logger

    @property
    def commands(self) -> dict[str, Command]:
        """Retorna todos os comandos registrados."""
        return self._commands.copy()

    def register(
        self,
        name: str,
        description: str,
        callback: Callable[..., Any],
        aliases: list[str] | None = None,
    ) -> None:
        """Registra um novo comando.

        Args:
            name: Nome do comando.
            description: Descrição do comando.
            callback: Função a ser chamada.
            aliases: Lista de aliases (ex: ['s'] para 'search').
        """
        if name in self._commands:
            self._logger.warning(f"Comando '{name}' já registrado. Sobrescrevendo.")

        self._commands[name] = Command(
            name=name,
            description=description,
            callback=callback,
            aliases=aliases or [],
        )

        # Registrar aliases
        for alias in (aliases or []):
            self._aliases[alias] = name

        self._logger.debug(f"Comando registrado: {name} (aliases: {aliases or []})")

    def _resolve_command(self, text: str) -> tuple[str, str]:
        """Resolve comando e argumentos.

        Args:
            text: Texto completo do comando.

        Returns:
            Tupla (nome_comando, argumentos_texto).
        """
        try:
            parts = shlex.split(text)
        except ValueError:
            parts = text.split()

        if not parts:
            return "", ""

        cmd_name = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        # Resolver alias
        if cmd_name in self._aliases:
            cmd_name = self._aliases[cmd_name]

        return cmd_name, " ".join(args)

    def execute(self, text: str) -> bool:
        """Executa um comando com argumentos.

        Args:
            text: Texto completo (comando + argumentos).

        Returns:
            True se executado com sucesso.
        """
        cmd_name, args_text = self._resolve_command(text)
        if not cmd_name:
            return False

        command = self._commands.get(cmd_name)
        if command is None:
            return False

        try:
            if args_text:
                command.execute(args_text)
            else:
                command.execute()
            self._logger.debug(f"Comando executado: {cmd_name}")
            return True
        except Exception as e:
            self._logger.error(f"Erro ao executar comando '{cmd_name}': {e}")
            return False

    def list_commands(self) -> list[tuple[str, str, list[str]]]:
        """Lista todos os comandos disponíveis.

        Returns:
            Lista de tuplas (nome, descrição, aliases).
        """
        return [
            (cmd.name, cmd.description, cmd.aliases)
            for cmd in self._commands.values()
        ]

    def has_command(self, name: str) -> bool:
        """Verifica se um comando existe.

        Args:
            name: Nome do comando ou alias.

        Returns:
            True se o comando existe.
        """
        return name in self._commands or name in self._aliases

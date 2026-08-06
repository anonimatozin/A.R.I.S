"""Utilitários de terminal do J.A.R.V.I.S.

Fornece funções para formatação e exibição de texto no terminal.
"""

import os
import sys
from typing import Optional


class Terminal:
    """Classe utilitária para operações de terminal."""

    # Códigos ANSI de cores
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    # Cores de texto
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Cores de fundo
    BG_BLUE = "\033[44m"
    BG_CYAN = "\033[46m"

    @staticmethod
    def clear() -> None:
        """Limpa a tela do terminal."""
        os.system("cls" if os.name == "nt" else "clear")

    @staticmethod
    def colorize(text: str, color: str) -> str:
        """Aplica cor ao texto.

        Args:
            text: Texto a ser colorido.
            color: Código de cor ANSI.

        Returns:
            Texto com cores aplicadas.
        """
        return f"{color}{text}{Terminal.RESET}"

    @staticmethod
    def bold(text: str) -> str:
        """Aplica estilo negrito ao texto.

        Args:
            text: Texto em negrito.

        Returns:
            Texto formatado.
        """
        return f"{Terminal.BOLD}{text}{Terminal.RESET}"

    @staticmethod
    def dim(text: str) -> str:
        """Aplica estilo apagado ao texto.

        Args:
            text: Texto apagado.

        Returns:
            Texto formatado.
        """
        return f"{Terminal.DIM}{text}{Terminal.RESET}"

    @staticmethod
    def print_colored(text: str, color: str = "") -> None:
        """Imprime texto colorido no terminal.

        Args:
            text: Texto a ser impresso.
            color: Código de cor ANSI (opcional).
        """
        if color:
            print(f"{color}{text}{Terminal.RESET}")
        else:
            print(text)

    @staticmethod
    def input_prompt(prompt: str = "> ", color: str = "") -> str:
        """Exibe um prompt e lê a entrada do usuário.

        Args:
            prompt: Texto do prompt.
            color: Cor do prompt (opcional).

        Returns:
            Texto digitado pelo usuário.
        """
        try:
            if color:
                return input(f"{color}{prompt}{Terminal.RESET}")
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return ""

    @staticmethod
    def print_separator(char: str = "=", length: int = 60) -> None:
        """Imprime uma linha separadora.

        Args:
            char: Caractere para o separador.
            length: Comprimento da linha.
        """
        print(char * length)

    @staticmethod
    def print_centered(text: str, width: int = 60) -> None:
        """Imprime texto centralizado.

        Args:
            text: Texto a ser centralizado.
            width: Largura total da linha.
        """
        print(text.center(width))

    @staticmethod
    def disable_colors() -> bool:
        """Desativa cores se o terminal não suportar.

        Returns:
            True se cores foram desativadas, False caso contrário.
        """
        if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
            for attr in dir(Terminal):
                if attr.isupper() and attr.startswith(("RESET", "BOLD", "DIM", "UNDERLINE", "RED", "GREEN", "YELLOW", "BLUE", "MAGENTA", "CYAN", "WHITE", "BG_")):
                    setattr(Terminal, attr, "")
            return True
        return False

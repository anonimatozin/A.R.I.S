"""Utilitarios de terminal do A.R.I.S.

Interface visual moderna inspirada em OpenCode/Claude Code.
"""

import os
import sys
from typing import Optional
from datetime import datetime


class Terminal:
    """Classe utilitaria para operacoes de terminal."""

    # Codigos ANSI de cores
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    ITALIC = "\033[3m"
    STRIKETHROUGH = "\033[9m"

    # Cores de texto
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    LIGHT_RED = "\033[91m"
    LIGHT_GREEN = "\033[92m"
    LIGHT_YELLOW = "\033[93m"
    LIGHT_BLUE = "\033[94m"
    LIGHT_MAGENTA = "\033[95m"
    LIGHT_CYAN = "\033[96m"

    # Cores de fundo
    BG_BLUE = "\033[44m"
    BG_CYAN = "\033[46m"
    BG_GREEN = "\033[42m"
    BG_RED = "\033[41m"
    BG_YELLOW = "\033[43m"
    BG_MAGENTA = "\033[45m"
    BG_GRAY = "\033[100m"

    @staticmethod
    def clear() -> None:
        """Limpa a tela do terminal."""
        os.system("cls" if os.name == "nt" else "clear")

    @staticmethod
    def colorize(text: str, color: str) -> str:
        """Aplica cor ao texto."""
        return f"{color}{text}{Terminal.RESET}"

    @staticmethod
    def bold(text: str) -> str:
        """Aplica estilo negrito."""
        return f"{Terminal.BOLD}{text}{Terminal.RESET}"

    @staticmethod
    def dim(text: str) -> str:
        """Aplica estilo apagado."""
        return f"{Terminal.DIM}{text}{Terminal.RESET}"

    @staticmethod
    def italic(text: str) -> str:
        """Aplica estilo italico."""
        return f"{Terminal.ITALIC}{text}{Terminal.RESET}"

    @staticmethod
    def strikethrough(text: str) -> str:
        """Aplica estilo riscado."""
        return f"{Terminal.STRIKETHROUGH}{text}{Terminal.RESET}"

    @staticmethod
    def gradient(text: str, color1: str = CYAN, color2: str = BLUE) -> str:
        """Aplica gradiente simples (alternancia de cores)."""
        result = ""
        for i, char in enumerate(text):
            if i % 2 == 0:
                result += f"{color1}{char}"
            else:
                result += f"{color2}{char}"
        return result + Terminal.RESET

    @staticmethod
    def print_colored(text: str, color: str = "") -> None:
        """Imprime texto colorido."""
        if color:
            print(f"{color}{text}{Terminal.RESET}")
        else:
            print(text)

    @staticmethod
    def input_prompt(prompt: str = "> ", color: str = "") -> str:
        """Exibe um prompt e le a entrada do usuario."""
        try:
            if color:
                return input(f"{color}{prompt}{Terminal.RESET}")
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return ""

    @staticmethod
    def print_separator(char: str = "=", length: int = 60) -> None:
        """Imprime uma linha separadora."""
        print(f"{Terminal.DIM}{char * length}{Terminal.RESET}")

    @staticmethod
    def print_centered(text: str, width: int = 60) -> None:
        """Imprime texto centralizado."""
        print(text.center(width))

    @staticmethod
    def disable_colors() -> bool:
        """Desativa cores se o terminal nao suportar."""
        if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
            for attr in dir(Terminal):
                if attr.isupper() and attr.startswith(("RESET", "BOLD", "DIM", "UNDERLINE", "RED", "GREEN", "YELLOW", "BLUE", "MAGENTA", "CYAN", "WHITE", "BG_")):
                    setattr(Terminal, attr, "")
            return True
        return False


class ArisUI:
    """Interface visual moderna do A.R.I.S."""

    # Arte ASCII do ARIS
    LOGO = r"""
    ╔════════════════════════════════════════════╗
    ║                                            ║
    ║   █████╗  ██████╗  ██╗     ██████╗         ║
    ║  ██╔══██╗  ██╔══██╗  ╚██╗    ██╔══██╗      ║
    ║  ███████║  █████╔╝   ██║    █████╔╝        ║
    ║  ██╔══██║  ██╔══██╗   ██║    ╚══██╔═╝      ║
    ║  ██║  ██║  ██║  ██║   ██║    ██║  ██║      ║
    ║  ╚═╝  ╚═╝  ╚═╝  ╚═╝   ╚═╝    ╚█████╔╝      ║
    ║                                            ║
    ║                v{version}                  ║
    ║                                            ║
    ╚════════════════════════════════════════════╝"""

    @staticmethod
    def show_banner(version: str = "1.0.0") -> None:
        """Exibe o banner principal."""
        Terminal.clear()

        # Logo ASCII
        logo = ArisUI.LOGO.format(version=version)
        print(Terminal.colorize(logo, Terminal.CYAN))

        # Status bar
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%d/%m/%Y")

        status_bar = f"  {Terminal.DIM}┌─────────────────────────────────────────────────────┐{Terminal.RESET}"
        status_bar += f"\n  {Terminal.DIM}│{Terminal.RESET}  {Terminal.GRAY}{date_str} {time_str}{Terminal.RESET}"
        status_bar += f"  {Terminal.DIM}│{Terminal.RESET}  {Terminal.GREEN}●{Terminal.RESET} Todos os sistemas operacionais"
        status_bar += f"\n  {Terminal.DIM}└─────────────────────────────────────────────────────┘{Terminal.RESET}"

        print(status_bar)
        print()

    @staticmethod
    def show_status_bar(
        version: str = "1.0.0",
        provider: str = "groq",
        mem_count: int = 0,
        task_count: int = 0,
        context: str = "",
    ) -> str:
        """Gera barra de status estilizada."""
        # Indicadores
        provider_icon = {
            "groq": "⚡",
            "gemini": "✦",
            "ollama": "◎",
        }.get(provider, "●")

        parts = []

        # Versao
        parts.append(f"{Terminal.DIM}v{version}{Terminal.RESET}")

        # Provider
        parts.append(f"{Terminal.CYAN}{provider_icon} {provider}{Terminal.RESET}")

        # Memorias
        if mem_count > 0:
            mem_color = Terminal.GREEN if mem_count < 100 else Terminal.YELLOW
            parts.append(f"{mem_color}mem:{mem_count}{Terminal.RESET}")

        # Tarefas
        if task_count > 0:
            parts.append(f"{Terminal.YELLOW}tasks:{task_count}{Terminal.RESET}")

        # Contexto
        if context:
            parts.append(f"{Terminal.GRAY}{context}{Terminal.RESET}")

        bar = " ─ ".join(parts)
        return f"  {bar}"

    @staticmethod
    def show_prompt(
        version: str = "1.0.0",
        provider: str = "groq",
        mem_count: int = 0,
    ) -> str:
        """Gera prompt estilizado."""
        provider_icon = {
            "groq": "⚡",
            "gemini": "✦",
            "ollama": "◎",
        }.get(provider, "●")

        return (
            f"{Terminal.DIM}╭─{Terminal.RESET}"
            f"{Terminal.CYAN} {provider_icon} ARIS {Terminal.DIM}│{Terminal.RESET}"
            f"{Terminal.GRAY} v{version}{Terminal.DIM} │{Terminal.RESET}"
            f"{Terminal.GREEN} {mem_count} mem{Terminal.DIM} {Terminal.RESET}"
            f"{Terminal.DIM}─╮{Terminal.RESET}"
            f"\n  {Terminal.DIM}╰─▸{Terminal.RESET} "
        )

    @staticmethod
    def show_response(response: str) -> None:
        """Exibe resposta do ARIS formatada."""
        print()
        lines = response.split("\n")
        for line in lines:
            # Escapar { } para evitar erro de f-string
            safe = line.replace("{", "{{").replace("}", "}}")
            print(f"  {Terminal.GREEN}{safe}{Terminal.RESET}")
        print()

    @staticmethod
    def show_action(module: str, action: str, params: dict = None) -> None:
        """Mostra acao sendo executada."""
        param_str = ""
        if params:
            param_items = [f"{k}={v}" for k, v in params.items() if v]
            if param_items:
                param_str = f" {Terminal.DIM}({', '.join(param_items[:3])}){Terminal.RESET}"

        print(f"  {Terminal.CYAN}▸{Terminal.RESET} {Terminal.BOLD}{module}{Terminal.RESET}.{action}{param_str}")

    @staticmethod
    def show_actions_count(count: int) -> None:
        """Mostra quantas acoes foram detectadas."""
        if count > 1:
            print(f"  {Terminal.DIM}({count} comandos detectados){Terminal.RESET}")

    @staticmethod
    def show_error(error: str) -> None:
        """Mostra erro formatado."""
        print(f"  {Terminal.RED}✗ {error}{Terminal.RESET}")

    @staticmethod
    def show_success(message: str) -> None:
        """Mostra sucesso formatado."""
        print(f"  {Terminal.GREEN}✓ {message}{Terminal.RESET}")

    @staticmethod
    def show_warning(message: str) -> None:
        """Mostra aviso formatado."""
        print(f"  {Terminal.YELLOW}⚠ {message}{Terminal.RESET}")

    @staticmethod
    def show_info(message: str) -> None:
        """Mostra informacao formatada."""
        print(f"  {Terminal.CYAN}ℹ {message}{Terminal.RESET}")

    @staticmethod
    def show_thinking() -> None:
        """Mostra indicador de processamento."""
        print(f"  {Terminal.DIM}● Processando...{Terminal.RESET}", end="", flush=True)

    @staticmethod
    def clear_thinking() -> None:
        """Limpa indicador de processamento."""
        print(f"\r{' ' * 30}\r", end="", flush=True)

    @staticmethod
    def show_help_header() -> None:
        """Exibe cabecalho de ajuda."""
        print()
        print(f"  {Terminal.BOLD}{Terminal.CYAN}A.R.I.S.{Terminal.RESET} {Terminal.DIM}— Comandos Disponiveis{Terminal.RESET}")
        print(f"  {Terminal.DIM}{'─' * 50}{Terminal.RESET}")

    @staticmethod
    def show_help_section(title: str, commands: list[tuple[str, str]]) -> None:
        """Exibe secao de ajuda."""
        print(f"\n  {Terminal.BOLD}{Terminal.YELLOW}{title}{Terminal.RESET}")
        for cmd, desc in commands:
            print(f"    {Terminal.CYAN}{cmd:<20}{Terminal.RESET} {Terminal.DIM}{desc}{Terminal.RESET}")

    @staticmethod
    def show_module_status(modules: dict[str, bool]) -> None:
        """Mostra status dos modulos."""
        print(f"\n  {Terminal.BOLD}Modulos:{Terminal.RESET}")
        for name, active in modules.items():
            icon = f"{Terminal.GREEN}●{Terminal.RESET}" if active else f"{Terminal.RED}○{Terminal.RESET}"
            print(f"    {icon} {name}")

    @staticmethod
    def show_banner_compact(version: str = "1.0.0", provider: str = "groq") -> None:
        """Banner compacto para uso diario."""
        Terminal.clear()

        provider_icon = {
            "groq": "⚡",
            "gemini": "✦",
            "ollama": "◎",
        }.get(provider, "●")

        print()
        print(f"  {Terminal.CYAN}{Terminal.BOLD}A.R.I.S.{Terminal.RESET} {Terminal.DIM}v{version}{Terminal.RESET}")
        print(f"  {Terminal.DIM}─────────────────────────────────────{Terminal.RESET}")
        print(f"  {Terminal.GREEN}●{Terminal.RESET} Sistemas operacionais  {Terminal.DIM}│{Terminal.RESET}  {Terminal.CYAN}{provider_icon} {provider}{Terminal.RESET}")
        print()

    @staticmethod
    def input_modern(
        version: str = "1.0.0",
        provider: str = "groq",
        mem_count: int = 0,
        task_count: int = 0,
    ) -> str:
        """Input moderno com indicadores de status."""
        provider_icon = {
            "groq": "⚡",
            "gemini": "✦",
            "ollama": "◎",
        }.get(provider, "●")

        # Montar indicadores
        indicators = []
        indicators.append(f"{Terminal.DIM}v{version}{Terminal.RESET}")
        indicators.append(f"{Terminal.CYAN}{provider_icon}{Terminal.RESET}")

        if mem_count > 0:
            indicators.append(f"{Terminal.GREEN}mem:{mem_count}{Terminal.RESET}")

        if task_count > 0:
            indicators.append(f"{Terminal.YELLOW}tasks:{task_count}{Terminal.RESET}")

        indicator_str = f" {Terminal.DIM}│{Terminal.RESET} ".join(indicators)

        # Prompt formatado
        prompt = (
            f"\n  {Terminal.DIM}╭─{Terminal.RESET}"
            f"{Terminal.CYAN} ARIS {Terminal.DIM}│{Terminal.RESET}"
            f" {indicator_str}"
            f" {Terminal.DIM}─╮{Terminal.RESET}"
            f"\n  {Terminal.DIM}╰─▸{Terminal.RESET} "
        )

        try:
            user_input = input(prompt)
            return user_input
        except (EOFError, KeyboardInterrupt):
            print()
            return ""


def disable_colors() -> bool:
    """Desativa cores se o terminal nao suportar."""
    return Terminal.disable_colors()

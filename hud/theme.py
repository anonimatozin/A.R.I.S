"""Theme futurista do J.A.R.V.I.S. NEXUS.

Barras, bordas e formatação para terminal estilo HUD.
"""


class FuturisticTheme:
    """Tema visual futurista para o terminal."""

    # Caracteres de borda
    TOP_LEFT = "╔"
    TOP_RIGHT = "╗"
    BOT_LEFT = "╚"
    BOT_RIGHT = "╝"
    H_LINE = "═"
    V_LINE = "║"
    T_DOWN = "╠"
    T_UP = "╣"
    CROSS = "╬"

    # Símbolos de status
    ONLINE = "●"
    OFFLINE = "○"
    WARNING = "▲"
    ERROR = "✖"
    OK = "✔"
    ARROW = "►"
    BULLET = "◆"
    DIAMOND = "◇"
    STAR = "★"

    # Barras de progresso
    BAR_FILLED = "█"
    BAR_EMPTY = "░"
    BAR_HALF = "▓"

    @staticmethod
    def box(content: list[str], width: int = 60, color: str = "\033[36m") -> str:
        """Cria uma caixa com bordas.

        Args:
            content: Linhas de conteúdo.
            width: Largura interna.
            color: Cor ANSI.

        Returns:
            String formatada.
        """
        reset = "\033[0m"
        lines = []
        lines.append(f"{color}{FuturisticTheme.TOP_LEFT}{FuturisticTheme.H_LINE * width}{FuturisticTheme.TOP_RIGHT}{reset}")

        for line in content:
            padded = line.ljust(width)
            lines.append(f"{color}{FuturisticTheme.V_LINE}{reset}{padded}{color}{FuturisticTheme.V_LINE}{reset}")

        lines.append(f"{color}{FuturisticTheme.BOT_LEFT}{FuturisticTheme.H_LINE * width}{FuturisticTheme.BOT_RIGHT}{reset}")
        return "\n".join(lines)

    @staticmethod
    def section(title: str, width: int = 60, color: str = "\033[36m") -> str:
        """Cria uma linha de seção.

        Args:
            title: Título da seção.
            width: Largura.
            color: Cor ANSI.

        Returns:
            String formatada.
        """
        reset = "\033[0m"
        padding = width - len(title) - 4
        left = padding // 2
        right = padding - left
        return f"{color}{FuturisticTheme.T_DOWN}{FuturisticTheme.H_LINE * left} {title} {FuturisticTheme.H_LINE * right}{FuturisticTheme.T_UP}{reset}"

    @staticmethod
    def progress_bar(percent: float, width: int = 20) -> str:
        """Gera barra de progresso colorida.

        Args:
            percent: Porcentagem (0-100).
            width: Largura da barra.

        Returns:
            String com barra formatada.
        """
        filled = int(width * percent / 100)
        empty = width - filled

        if percent > 80:
            color = "\033[31m"  # Vermelho
        elif percent > 60:
            color = "\033[33m"  # Amarelo
        else:
            color = "\033[32m"  # Verde

        reset = "\033[0m"
        bar = f"{color}{FuturisticTheme.BAR_FILLED * filled}{FuturisticTheme.BAR_EMPTY * empty}{reset}"
        return f"[{bar}] {percent:5.1f}%"

    @staticmethod
    def status_line(label: str, value: str, width: int = 60) -> str:
        """Gera uma linha de status formatada.

        Args:
            label: Rótulo.
            value: Valor.
            width: Largura total.

        Returns:
            String formatada.
        """
        spaces = width - len(label) - len(value) - 4
        return f"  {label}{' ' * max(1, spaces)}{value}"

    @staticmethod
    def header(title: str, subtitle: str = "", width: int = 60) -> str:
        """Gera cabeçalho decorado.

        Args:
            title: Título principal.
            subtitle: Subtítulo.
            width: Largura.

        Returns:
            String formatada.
        """
        reset = "\033[0m"
        cyan = "\033[36m"
        lines = []
        lines.append(f"{cyan}{FuturisticTheme.TOP_LEFT}{FuturisticTheme.H_LINE * width}{FuturisticTheme.TOP_RIGHT}{reset}")

        title_line = title.center(width)
        lines.append(f"{cyan}{FuturisticTheme.V_LINE}{reset}{cyan}{title_line}{reset}{cyan}{FuturisticTheme.V_LINE}{reset}")

        if subtitle:
            sub_line = subtitle.center(width)
            lines.append(f"{cyan}{FuturisticTheme.V_LINE}{reset}{sub_line}{cyan}{FuturisticTheme.V_LINE}{reset}")

        lines.append(f"{cyan}{FuturisticTheme.T_DOWN}{FuturisticTheme.H_LINE * width}{FuturisticTheme.T_UP}{reset}")
        return "\n".join(lines)

"""HUD Principal do J.A.R.V.I.S. NEXUS.

Painel de controle central com dados em tempo real.
"""

import os
import time
from datetime import datetime

from system.analyzer import PersonalAnalyzer
from utils.terminal import Terminal


class HUD:
    """Heads-Up Display do sistema.

    Exibe painel de controle central com informações em tempo real.
    """

    def __init__(self, analyzer: PersonalAnalyzer) -> None:
        self._analyzer = analyzer
        self._start_time = datetime.now()

    def _bar(self, percent: float, width: int = 20) -> str:
        """Gera uma barra de progresso.

        Args:
            percent: Porcentagem (0-100).
            width: Largura da barra.

        Returns:
            String com a barra formatada.
        """
        filled = int(width * percent / 100)
        empty = width - filled

        if percent > 80:
            color = Terminal.RED
        elif percent > 60:
            color = Terminal.YELLOW
        else:
            color = Terminal.GREEN

        bar = color + "█" * filled + Terminal.DIM + "░" * empty + Terminal.RESET
        return f"[{bar}] {percent:5.1f}%"

    def _status_icon(self, ok: bool) -> str:
        """Ícone de status."""
        return Terminal.colorize("●", Terminal.GREEN) if ok else Terminal.colorize("●", Terminal.RED)

    def render(self) -> None:
        """Renderiza o HUD completo."""
        # Coletar dados
        cpu = self._analyzer.cpu_info()
        mem = self._analyzer.memory_info()
        disk = self._analyzer.disk_info()
        net = self._analyzer.network_info()
        bat = self._analyzer.battery_info()
        sys_info = self._analyzer.system_info()
        procs = self._analyzer.process_count()

        # Tempo ligado
        uptime_delta = datetime.now() - self._start_time
        hours = int(uptime_delta.total_seconds() // 3600)
        minutes = int((uptime_delta.total_seconds() % 3600) // 60)

        os.system("cls" if os.name == "nt" else "clear")

        # Header
        print(Terminal.colorize("╔" + "═" * 58 + "╗", Terminal.CYAN))
        print(Terminal.colorize("║" + " J.A.R.V.I.S. NEXUS ".center(58) + "║", Terminal.CYAN))
        print(Terminal.colorize("║" + " CENTRO DE CONTROLE ".center(58) + "║", Terminal.CYAN))
        print(Terminal.colorize("╠" + "═" * 58 + "╣", Terminal.CYAN))

        # Status geral
        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  Status Geral:  {self._status_icon(True)} "
              f"{Terminal.colorize('ONLINE', Terminal.GREEN)}" +
              " " * 22 +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  Horário:       {datetime.now().strftime('%H:%M:%S')}" +
              " " * 30 +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  Sessão:        {hours:02d}h {minutes:02d}m" +
              " " * 32 +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("╠" + "═" * 58 + "╣", Terminal.CYAN))

        # CPU
        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  CPU            {self._bar(cpu['usage_percent'])}" +
              " " * 8 +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("║", Terminal.CYAN) +
              f"                 {cpu['cores_physical']}C/{cpu['cores_logical']}T "
              f"@ {cpu['frequency_mhz']:.0f}MHz" +
              " " * 28 +
              Terminal.colorize("║", Terminal.CYAN))

        # RAM
        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  RAM            {self._bar(mem['percent'])}" +
              " " * 8 +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("║", Terminal.CYAN) +
              f"                 {mem['used_gb']:.1f}GB / {mem['total_gb']:.1f}GB" +
              " " * 30 +
              Terminal.colorize("║", Terminal.CYAN))

        # Disco
        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  Disco (C:)     {self._bar(disk['percent'])}" +
              " " * 8 +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("║", Terminal.CYAN) +
              f"                 {disk['used_gb']:.1f}GB / {disk['total_gb']:.1f}GB" +
              " " * 30 +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("╠" + "═" * 58 + "╣", Terminal.CYAN))

        # Rede
        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  Rede           ↓ {net['bytes_recv_gb']:.2f}GB  ↑ {net['bytes_sent_gb']:.2f}GB" +
              " " * 16 +
              Terminal.colorize("║", Terminal.CYAN))

        # Bateria
        if bat["percent"] is not None:
            bat_status = "Carregando" if bat["plugged"] else f"{bat['percent']:.0f}%"
            print(Terminal.colorize("║", Terminal.CYAN) +
                  f"  Bateria        {bat_status}" +
                  " " * 40 +
                  Terminal.colorize("║", Terminal.CYAN))
        else:
            print(Terminal.colorize("║", Terminal.CYAN) +
                  f"  Bateria        N/A (desktop)" +
                  " " * 34 +
                  Terminal.colorize("║", Terminal.CYAN))

        # Processos
        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  Processos      {procs} ativos" +
              " " * 36 +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("╠" + "═" * 58 + "╣", Terminal.CYAN))

        # Top processos
        top = self._analyzer.top_processes(3)
        print(Terminal.colorize("║", Terminal.CYAN) +
              "  TOP PROCESSOS" +
              " " * 43 +
              Terminal.colorize("║", Terminal.CYAN))

        for p in top:
            print(Terminal.colorize("║", Terminal.CYAN) +
                  f"    {p['name']:<18} CPU:{p['cpu']:>5.1f}%  RAM:{p['ram']:>5.1f}%" +
                  " " * 9 +
                  Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("╠" + "═" * 58 + "╣", Terminal.CYAN))

        # Diagnóstico
        alerts = self._analyzer.diagnose()
        for alert in alerts[:3]:
            color = Terminal.RED if "CRÍTICO" in alert else Terminal.YELLOW if "AVISO" in alert else Terminal.GREEN
            print(Terminal.colorize("║", Terminal.CYAN) +
                  f"  {Terminal.colorize(alert, color)}" +
                  " " * (54 - len(alert)) +
                  Terminal.colorize("║", Terminal.CYAN))

        # Footer
        print(Terminal.colorize("╠" + "═" * 58 + "╣", Terminal.CYAN))
        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  SO: {sys_info['os']} {sys_info['os_version'][:20]}" +
              " " * (54 - len(f"SO: {sys_info['os']} {sys_info['os_version'][:20]}")) +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("║", Terminal.CYAN) +
              f"  Host: {sys_info['hostname']}" +
              " " * (54 - len(f"Host: {sys_info['hostname']}")) +
              Terminal.colorize("║", Terminal.CYAN))

        print(Terminal.colorize("╚" + "═" * 58 + "╝", Terminal.CYAN))

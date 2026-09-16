"""CLL1 Main — orquestrador da instancia edge da A.R.I.S.

Inicia gateway, Discord bot e roteador. Gerencia o ciclo de vida
de todos os componentes do CLL1.

Uso:
    python -m cll1.main
    # ou
    python cll1/main.py
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

# Adiciona o diretorio raiz ao path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cll1.router import Router  # noqa: E402
from utils.logger import Logger  # noqa: E402


class CLL1Main:
    """Orquestrador principal do CLL1.

    Gerencia:
    - Gateway TCP (porta 8765)
    - Discord Bot (DM)
    - Roteador PC/Edge
    - Heartbeat
    """

    def __init__(self) -> None:
        self._logger = Logger(
            name="cll1",
            log_dir=str(Path.home() / "cll1" / "logs"),
            level="INFO",
            max_size_mb=5,
        )
        self._router: Router | None = None
        self._discord_bot: object | None = None
        self._gateway_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Inicia todos os componentes do CLL1."""
        self._logger.info("CLL1 Iniciando...")

        self._running = True

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        self._start_gateway()

        self._start_router()

        self._start_discord()

        self._logger.info("CLL1 Todos os componentes iniciados.")
        self._print_status()

        self._main_loop()

    def _start_gateway(self) -> None:
        """Inicia o gateway TCP em thread separada."""
        try:
            from gateway import main as gateway_main

            def run_gateway():
                try:
                    gateway_main()
                except Exception as e:
                    self._logger.error(f"Gateway erro: {e}")

            self._gateway_thread = threading.Thread(
                target=run_gateway,
                name="cll1-gateway",
                daemon=True,
            )
            self._gateway_thread.start()
            self._logger.info("Gateway TCP iniciado (porta 8765)")
        except Exception as e:
            self._logger.error(f"Falha ao iniciar gateway: {e}")

    def _start_router(self) -> None:
        """Inicia o roteador PC/Edge."""
        try:
            self._router = Router(logger=self._logger)
            self._router.check_pc_online()
            self._logger.info(
                f"Roteador iniciado — PC: "
                f"{'online' if self._router.state.pc_online else 'offline'}"
            )
        except Exception as e:
            self._logger.error(f"Falha ao iniciar roteador: {e}")

    def _start_discord(self) -> None:
        """Inicia o bot Discord."""
        token = os.getenv("DISCORD_BOT_TOKEN", "")
        if not token:
            self._logger.info("DISCORD_BOT_TOKEN nao configurado — Discord desativado")
            return

        try:
            from modules.discord_bot import DiscordBot

            def on_message(text: str, origin_info: dict) -> str | None:
                if self._router:
                    return self._router.route_message(text, origin_info)
                return "Sistema indisponivel no momento."

            self._discord_bot = DiscordBot(
                token=token,
                on_message=on_message,
                logger=self._logger,
            )
            self._discord_bot.start()
            self._logger.info("Discord Bot iniciado (DM)")
        except ImportError:
            self._logger.warning("discord.py nao instalado — Discord desativado")
        except Exception as e:
            self._logger.error(f"Falha ao iniciar Discord: {e}")

    def _main_loop(self) -> None:
        """Loop principal — mantem o CLL1 rodando."""
        try:
            while self._running:
                time.sleep(30)
                if self._running:
                    self._check_health()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def _check_health(self) -> None:
        """Verificacao periodica de saude dos componentes."""
        if self._router:
            self._router.check_pc_online()

        if self._discord_bot and not self._discord_bot.is_running:
            self._logger.warning("Discord bot desconectado — tentando reconexao")
            try:
                self._discord_bot.start()
            except Exception:
                pass

    def _print_status(self) -> None:
        """Imprime status dos componentes."""
        status = self.get_status()
        self._logger.info(f"Status: {status}")

    def get_status(self) -> dict:
        """Retorna status de todos os componentes."""
        return {
            "running": self._running,
            "gateway": self._gateway_thread is not None and self._gateway_thread.is_alive(),
            "router": self._router.get_status() if self._router else None,
            "discord": self._discord_bot.is_running if self._discord_bot else False,
        }

    def shutdown(self) -> None:
        """Encerra todos os componentes."""
        self._logger.info("CLL1 Encerrando...")
        self._running = False

        if self._discord_bot:
            try:
                self._discord_bot.stop()
            except Exception:
                pass

        self._logger.info("CLL1 Encerrado.")

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Trata sinais de encerramento."""
        self._logger.info(f"Sinal {signum} recebido — encerrando...")
        self.shutdown()
        sys.exit(0)


def main() -> None:
    """Ponto de entrada principal."""
    cll1 = CLL1Main()
    cll1.start()


if __name__ == "__main__":
    main()

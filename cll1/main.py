"""CLL1 Main — entry point canônico da A.R.I.S.

Inicia todos os componentes: Gateway, Router, Discord, EventBus,
HUD Panel, e opcionalmente Notificação Bridge.

Uso:
    python cll1/main.py                # Inicia tudo (Gateway + HUD)
    python cll1/main.py --no-hud       # Sem HUD
    python cll1/main.py --text-only    # Modo texto (sem interação visual)
    python -m cll1.main                # Alternativo
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# Adiciona o diretorio raiz ao path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _load_dotenv(path: Path) -> None:
    """Carrega .env simples (sem dependencia externa)."""
    if not path.is_file():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and value:
                os.environ[key] = value

_load_dotenv(ROOT / ".env")

from cll1.router import Router  # noqa: E402
from utils.logger import Logger  # noqa: E402


class CLL1Main:
    """Orquestrador principal da A.R.I.S.

    Gerencia:
    - Gateway TCP+HTTP (portas 8765/8766)
    - Discord Bot (DM)
    - Roteador PC/Edge
    - Heartbeat
    - HUD Panel (pywebview)
    - Notification Bridge (Termux:API, opcional)
    """

    def __init__(self, no_hud: bool = False, text_only: bool = False) -> None:
        self._logger = Logger(
            name="cll1",
            log_dir=str(ROOT / "logs"),
            level="INFO",
            max_size_mb=5,
        )
        self._router: Router | None = None
        self._discord_bot: object | None = None
        self._gateway_thread: threading.Thread | None = None
        self._notification_bridge: object | None = None
        self._hud_process: subprocess.Popen | None = None
        self._pc_listener_process: subprocess.Popen | None = None
        self._no_hud = no_hud
        self._text_only = text_only
        self._running = False
        self._event_bus: object | None = None

    def start(self) -> None:
        """Inicia todos os componentes do sistema."""
        self._logger.info("A.R.I.S. Iniciando...")

        # Initialize version tracking
        try:
            from core.version import initialize_version
            initialize_version()
        except Exception:
            pass

        self._running = True

        # Create local event bus for real-time dashboard updates
        try:
            from core.neural.event_bus import EventBus
            self._event_bus = EventBus(logger=self._logger)
        except Exception as e:
            self._logger.warning(f"EventBus local indisponível ({e}) — dashboard usará polling")
            self._event_bus = None

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        self._start_gateway()
        self._start_router()
        self._start_pc_listener()
        self._start_discord()

        if not self._no_hud:
            self._start_hud()

        self._logger.info("Todos os componentes iniciados.")
        self._print_status()

        self._main_loop()

    def _start_gateway(self) -> None:
        """Inicia o gateway TCP + HTTP em thread separada."""
        try:
            from gateway.server import run_gateway

            def run_gw():
                try:
                    run_gateway(str(ROOT), event_bus=self._event_bus, logger=self._logger)
                except Exception as e:
                    self._logger.error(f"Gateway erro: {e}")

            self._gateway_thread = threading.Thread(
                target=run_gw,
                name="cll1-gateway",
                daemon=True,
            )
            self._gateway_thread.start()
            self._logger.info("Gateway TCP+HTTP iniciado (TCP :8765, HTTP :8766)")
        except Exception as e:
            self._logger.error(f"Falha ao iniciar gateway: {e}")

    def _start_router(self) -> None:
        """Inicia o roteador PC/Edge."""
        try:
            self._router = Router(logger=self._logger, event_bus=self._event_bus)
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
            try:
                from modules.discord_bot import DiscordBot
            except ImportError:
                from discord_bot import DiscordBot  # fallback raiz (build único)

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

    def _start_notification_bridge(self) -> None:
        """Inicia a ponte de notificações Android via Termux:API."""
        try:
            from cll1.notification_bridge import NotificationBridgeManager

            package_filter = os.getenv("CLL1_NOTIFICATION_FILTER", "").split(",")
            package_filter = [p.strip() for p in package_filter if p.strip()] or None

            self._notification_bridge = NotificationBridgeManager(
                event_bus=self._event_bus,
                logger=self._logger,
            )
            if self._notification_bridge.start(package_filter=package_filter):
                self._logger.info("Notification Bridge iniciado (Termux:API)")
            else:
                self._logger.warning("Notification Bridge falhou ao iniciar (termux-api não disponível?)")
                self._notification_bridge = None
        except ImportError:
            self._logger.warning("Notification Bridge não disponível")
        except Exception as e:
            self._logger.error(f"Falha ao iniciar Notification Bridge: {e}")

    def _start_pc_listener(self) -> None:
        """Inicia o pc_listener (:8770/api/llm) como processo separado.

        Sem ele, EdgeChat._call_llm_via_pc sempre retorna None e o HUD cai
        no fallback "PC indisponível" mesmo rodando no próprio PC.
        """
        try:
            listener_script = ROOT / "agent" / "pc_listener.py"
            if not listener_script.exists():
                self._logger.warning(f"pc_listener não encontrado: {listener_script}")
                return

            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            self._pc_listener_process = subprocess.Popen(
                [sys.executable, "-u", str(listener_script)],
                cwd=str(ROOT),
                creationflags=creationflags,
            )
            self._logger.info(f"pc_listener iniciado (PID {self._pc_listener_process.pid})")
        except Exception as e:
            self._logger.error(f"Falha ao iniciar pc_listener: {e}")

    def _start_hud(self) -> None:
        """Inicia o HUD Panel (Pygame nativo) como processo separado."""
        try:
            hud_script = ROOT / "core" / "vision" / "hud" / "server.py"
            if not hud_script.exists():
                self._logger.warning(f"HUD script não encontrado: {hud_script}")
                return

            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            self._hud_process = subprocess.Popen(
                [sys.executable, "-u", str(hud_script), "--pygame"],
                cwd=str(ROOT),
                creationflags=creationflags,
            )
            self._logger.info(f"HUD Pygame iniciado (PID {self._hud_process.pid})")
        except Exception as e:
            self._logger.error(f"Falha ao iniciar HUD: {e}")

    def _main_loop(self) -> None:
        """Loop principal — mantem o CLL1 rodando."""
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        try:
            while self._running:
                try:
                    time.sleep(30)
                    if not self._running:
                        break
                    self._check_health()
                    consecutive_errors = 0  # Reset on success
                except Exception as e:
                    consecutive_errors += 1
                    self._logger.error(f"Erro no loop principal (#{consecutive_errors}): {e}")
                    if consecutive_errors >= max_consecutive_errors:
                        self._logger.critical(f"Muitos erros consecutivos ({max_consecutive_errors}), encerrando...")
                        break
                    time.sleep(5)  # Brief pause before retry
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def _check_health(self) -> None:
        """Verificacao periodica de saude dos componentes com logging detalhado."""
        # Check router/PC connectivity
        if self._router:
            try:
                pc_online = self._router.check_pc_online()
                self._logger.debug(f"Heartbeat: PC {'online' if pc_online else 'offline'}")
            except Exception as e:
                self._logger.error(f"Heartbeat router falhou: {e}")

        # Check Discord bot
        if self._discord_bot:
            if not self._discord_bot.is_running:
                self._logger.warning("Discord bot desconectado — tentando reconexao automatica")
                try:
                    self._discord_bot.start()
                    self._logger.info("Discord bot reconectado com sucesso")
                except Exception as e:
                    self._logger.error(f"Falha ao reconectar Discord bot: {e}")
            else:
                self._logger.debug("Heartbeat: Discord bot online")

        # Check Gateway thread
        if self._gateway_thread:
            if not self._gateway_thread.is_alive():
                self._logger.warning("Gateway thread morta — tentando reiniciar")
                try:
                    self._start_gateway()
                    self._logger.info("Gateway reiniciado com sucesso")
                except Exception as e:
                    self._logger.error(f"Falha ao reiniciar gateway: {e}")
            else:
                self._logger.debug("Heartbeat: Gateway thread viva")

        # Check pc_listener process
        if self._pc_listener_process:
            if self._pc_listener_process.poll() is not None:
                self._logger.warning("pc_listener morto — tentando reiniciar")
                try:
                    self._start_pc_listener()
                    self._logger.info("pc_listener reiniciado com sucesso")
                except Exception as e:
                    self._logger.error(f"Falha ao reiniciar pc_listener: {e}")

        # Check Notification Bridge
        if self._notification_bridge:
            try:
                status = self._notification_bridge.get_status()
                if not status.get("running", False):
                    self._logger.warning("Notification Bridge parado — tentando reiniciar")
                    self._start_notification_bridge()
                else:
                    self._logger.debug("Heartbeat: Notification Bridge ativo")
            except Exception as e:
                self._logger.error(f"Heartbeat notification bridge falhou: {e}")

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
            "notification_bridge": self._notification_bridge.get_status() if self._notification_bridge else None,
        }

    def shutdown(self) -> None:
        """Encerra todos os componentes."""
        self._logger.info("A.R.I.S. Encerrando...")
        self._running = False

        if self._hud_process:
            try:
                self._hud_process.terminate()
                self._hud_process.wait(timeout=5)
            except Exception:
                try:
                    self._hud_process.kill()
                except Exception:
                    pass

        if self._pc_listener_process:
            try:
                self._pc_listener_process.terminate()
                self._pc_listener_process.wait(timeout=5)
            except Exception:
                try:
                    self._pc_listener_process.kill()
                except Exception:
                    pass

        if self._notification_bridge:
            try:
                self._notification_bridge.stop()
            except Exception:
                pass

        if self._discord_bot:
            try:
                self._discord_bot.stop()
            except Exception:
                pass

        self._logger.info("A.R.I.S. Encerrado.")

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Trata sinais de encerramento."""
        self._logger.info(f"Sinal {signum} recebido — encerrando...")
        self.shutdown()
        sys.exit(0)


def main() -> None:
    """Ponto de entrada principal."""
    parser = argparse.ArgumentParser(
        description="A.R.I.S. — Assistente de Raciocínio e Integração de Sistemas",
    )
    parser.add_argument("--no-hud", action="store_true", help="Não iniciar o HUD Panel")
    parser.add_argument("--text-only", action="store_true", help="Modo texto (sem voz nem visão)")
    args = parser.parse_args()

    cll1 = CLL1Main(no_hud=args.no_hud, text_only=args.text_only)
    cll1.start()


if __name__ == "__main__":
    main()

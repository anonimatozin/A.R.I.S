"""Monta e executa a aplicacao.

Uso:
    python -m aris_eyes                  # abre no modo configurado (padrao: tela cheia)
    python -m aris_eyes --mini           # abre ja na miniatura
    python -m aris_eyes --send toggle    # comanda uma instancia que ja esta rodando
    python -m aris_eyes --check          # mostra o ambiente grafico detectado
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from typing import Optional

from . import __version__
from .client import send
from .config import Config, control_socket_path, default_config_path

log = logging.getLogger("aris_eyes")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aris_eyes", description="Olhos digitais animados da ARIS.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--fullscreen", action="store_true", help="inicia em tela cheia")
    mode.add_argument("--mini", action="store_true", help="inicia na miniatura")
    mode.add_argument("--hidden", action="store_true", help="inicia escondido (use a bandeja ou --send show)")
    p.add_argument("--send", nargs="+", metavar="COMANDO",
                   help="envia um comando a instancia em execucao (ex.: --send toggle, --send mood happy)")
    p.add_argument("--config", help=f"caminho do config.json (padrao: {default_config_path()})")
    p.add_argument("--x11", action="store_true", help="forca X11/XWayland (sempre no topo e posicao funcionam)")
    p.add_argument("--no-tray", action="store_true", help="nao cria icone na bandeja")
    p.add_argument("--demo", action="store_true", help="troca a expressao sozinho a cada 3 s")
    p.add_argument("--check", action="store_true", help="mostra o ambiente grafico e sai")
    p.add_argument("--debug", action="store_true", help="mais mensagens no terminal")
    p.add_argument("--version", action="version", version=f"aris_eyes {__version__}")
    return p


def _send_main(words: list[str]) -> int:
    reply = send(" ".join(words), timeout=2.0)
    if reply is None:
        print("A interface da ARIS nao esta rodando. Inicie com: python -m aris_eyes", file=sys.stderr)
        return 1
    print(reply)
    return 1 if reply.startswith("erro") else 0


def _check_main() -> int:
    session = os.environ.get("XDG_SESSION_TYPE", "?")
    print(f"Sessao: {session}  (DISPLAY={os.environ.get('DISPLAY')}, WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY')})")
    print(f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP', '?')}")
    try:
        import PySide6
        print(f"PySide6: {PySide6.__version__}")
    except ImportError:
        print("PySide6: NAO INSTALADO (pip install -r requirements.txt)")
        return 1
    if session == "wayland":
        print("Wayland: posicao da miniatura e 'sempre no topo' dependem do compositor; "
              "use --x11 se precisar deles (veja o README).")
    print(f"Canal de controle: {control_socket_path()}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", datefmt="%H:%M:%S")
    if args.send:
        return _send_main(args.send)
    if args.check:
        return _check_main()

    cfg = Config.load(args.config)
    if args.fullscreen:
        cfg.start_mode = "fullscreen"
    elif args.mini:
        cfg.start_mode = "mini"
    elif args.hidden:
        cfg.start_mode = "hidden"
    if args.no_tray:
        cfg.tray = False

    # instancia unica: se ja esta rodando, so traz a janela de volta
    if send("ping") == "pong":
        send("show")
        print("A ARIS ja esta rodando; trouxe a interface de volta.")
        return 0

    # a plataforma grafica precisa ser escolhida ANTES de criar o QApplication
    platform = "xcb" if args.x11 else cfg.platform
    if platform in ("xcb", "wayland") and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = platform

    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 nao esta instalado. Rode: pip install -r requirements.txt", file=sys.stderr)
        return 1

    from .api import EyesAPI
    from .control import ControlServer
    from .eyes.presets import MOOD_ORDER
    from .modes import DisplayController, Mode, parse_mode
    from .shortcuts import install_shortcuts
    from .tray import install_tray, make_icon
    from .ui.window import EyesWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("aris-eyes")
    app.setQuitOnLastWindowClosed(False)          # esconder a janela NAO encerra o programa
    icon = make_icon(cfg.eye_color)
    app.setWindowIcon(icon)

    window = EyesWindow(cfg)
    controller = DisplayController(window)
    api = EyesAPI(window.eyes, controller, cfg, quit_callback=lambda: QTimer.singleShot(0, app.quit))

    window.mode_requested.connect(lambda name: controller.set_mode(parse_mode(name)))
    window.quit_requested.connect(app.quit)
    window.always_on_top_requested.connect(api.set_always_on_top)
    window.mood_requested.connect(api.set_mood)
    window.scene_requested.connect(lambda name: api.execute(f"scene {name}"))

    actions = {
        "toggle_fullscreen": controller.toggle_fullscreen,
        "mini": lambda: controller.set_mode(Mode.MINI),
        "fullscreen": lambda: controller.set_mode(Mode.FULLSCREEN),
        "hide": lambda: controller.set_mode(Mode.HIDDEN),
        "cycle": controller.cycle,
        "quit": app.quit,
    }
    shortcuts = install_shortcuts(window, cfg.shortcuts, actions, [m.value for m in MOOD_ORDER],
                                  api.set_mood, cfg.dev_keys)

    tray = None
    if cfg.tray:
        tray = install_tray(icon, on_toggle_hidden=controller.toggle_hidden,
                            on_fullscreen=lambda: controller.set_mode(Mode.FULLSCREEN),
                            on_mini=lambda: controller.set_mode(Mode.MINI), on_quit=app.quit)

    server = ControlServer(api.execute, control_socket_path())
    server.start()

    # Ctrl+C / kill no terminal encerram limpo (o timer deixa o Python tratar o sinal)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    heartbeat = QTimer()
    heartbeat.start(250)
    heartbeat.timeout.connect(lambda: None)

    demo_timer = None
    if args.demo:
        demo_timer = QTimer()
        index = {"i": 0}

        def next_mood() -> None:
            index["i"] = (index["i"] + 1) % len(MOOD_ORDER)
            api.set_mood(MOOD_ORDER[index["i"]].value)
        demo_timer.timeout.connect(next_mood)
        demo_timer.start(3000)

    controller.set_mode(parse_mode(cfg.start_mode) or Mode.FULLSCREEN)
    log.info("ARIS eyes %s | plataforma=%s | modo=%s | sair: Ctrl+Q, Ctrl+C ou --send quit",
             __version__, app.platformName(), cfg.start_mode)

    code = app.exec()
    window._remember_position()
    try:
        cfg.save()
    except OSError as exc:
        log.warning("nao consegui salvar a configuracao: %s", exc)
    server.stop()
    del shortcuts, tray, demo_timer
    return code

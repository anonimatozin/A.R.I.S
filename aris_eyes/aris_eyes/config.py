"""Configuracao do aris_eyes: valores padrao e leitura/gravacao em JSON.

Arquivo do usuario: ~/.config/aris_eyes/config.json (criado na primeira execucao com os padroes).
Chaves desconhecidas sao ignoradas; valores invalidos voltam ao padrao, com aviso no log.
Este modulo nao depende de Qt.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aris_eyes.config")

APP_NAME = "aris_eyes"
START_MODES = ("fullscreen", "mini", "hidden")
CORNERS = ("bottom-right", "bottom-left", "top-right", "top-left")
PLATFORMS = ("auto", "xcb", "wayland")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# acao -> sequencia de teclas (vale quando uma janela da ARIS esta em foco). "" desativa.
DEFAULT_SHORTCUTS = {
    "toggle_fullscreen": "F11",   # tela cheia <-> miniatura
    "mini": "Esc",                # vai para a miniatura
    "hide": "Ctrl+H",             # esconde a interface (o programa continua rodando)
    "cycle": "F10",               # tela cheia -> miniatura -> escondida -> tela cheia
    "quit": "Ctrl+Q",             # encerra o programa
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def default_config_path() -> Path:
    return config_dir() / "config.json"


def control_socket_path() -> str:
    """Socket local (so o seu usuario acessa) por onde atalhos do desktop e a ARIS comandam os olhos."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return str(Path(runtime) / "aris_eyes.sock")
    return str(Path(tempfile.gettempdir()) / f"aris_eyes_{os.getuid()}.sock")


@dataclass
class Config:
    # --- inicio ---
    start_mode: str = "fullscreen"         # fullscreen | mini | hidden
    initial_mood: str = "neutral"
    # --- cores ---
    eye_color: str = "#2f9bff"
    glow_color: str = "#1f78ff"
    background_color: str = "#000000"
    glow: bool = True                      # brilho em volta dos olhos (desligue em PC fraco)
    # --- miniatura ---
    mini_width: int = 300
    mini_height: int = 170
    mini_corner: str = "bottom-right"      # usado quando nao ha posicao salva (so X11)
    mini_margin: int = 24
    mini_position: Optional[list] = None   # [x, y] lembrada ao arrastar (so X11)
    always_on_top: bool = True             # funciona no X11; veja o README para Wayland
    skip_taskbar: bool = True              # miniatura nao aparece na barra de tarefas
    # --- tela ---
    screen: int = -1                       # -1 = monitor atual; 0, 1, ... = escolher monitor
    fps_fullscreen: int = 60
    fps_mini: int = 30
    hide_cursor_ms: int = 2000             # esconde o mouse parado em tela cheia (0 desativa)
    # --- comportamento dos olhos ---
    blink_min_s: float = 2.0
    blink_max_s: float = 6.0
    saccades: bool = True                  # olhadinhas aleatorias quando parado
    breathing: bool = True                 # respiracao sutil
    # --- enfeites e cenas ---
    props_enabled: bool = True             # False = sem enfeites/cenas (olhos como antes)
    # --- ambiente ---
    platform: str = "auto"                 # auto | xcb (X11/XWayland) | wayland
    tray: bool = True                      # icone na bandeja, se o desktop tiver
    dev_keys: bool = True                  # teclas 1..0 trocam a expressao (para testar)
    shortcuts: dict = field(default_factory=lambda: dict(DEFAULT_SHORTCUTS))

    # ------------------------------------------------------------------ validacao
    def validate(self) -> None:
        defaults = Config()
        for f in fields(self):
            name, value, default = f.name, getattr(self, f.name), getattr(defaults, f.name)
            if name == "shortcuts":
                if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                          for k, v in value.items()):
                    self._reset(name, "deve ser {acao: 'Tecla'}")
                continue
            if name == "mini_position":
                if value is not None and not (isinstance(value, list) and len(value) == 2
                                              and all(isinstance(n, int) and not isinstance(n, bool) for n in value)):
                    self._reset(name, "deve ser [x, y] ou null")
                continue
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
            elif isinstance(default, float):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                if ok:
                    setattr(self, name, float(value))
            else:
                ok = isinstance(value, str)
            if not ok:
                self._reset(name, f"tipo invalido ({type(value).__name__})")
        self._check_choice("start_mode", START_MODES)
        self._check_choice("mini_corner", CORNERS)
        self._check_choice("platform", PLATFORMS)
        for name in ("eye_color", "glow_color", "background_color"):
            if not _HEX.match(getattr(self, name)):
                self._reset(name, "use o formato #rrggbb")
        self.mini_width = _clamp(self.mini_width, 120, 1200)
        self.mini_height = _clamp(self.mini_height, 70, 800)
        self.mini_margin = _clamp(self.mini_margin, 0, 400)
        self.fps_fullscreen = _clamp(self.fps_fullscreen, 5, 144)
        self.fps_mini = _clamp(self.fps_mini, 5, 144)
        self.hide_cursor_ms = max(0, self.hide_cursor_ms)
        self.blink_min_s = max(0.3, self.blink_min_s)
        self.blink_max_s = max(self.blink_min_s, self.blink_max_s)

    def _reset(self, name: str, why: str) -> None:
        default = getattr(Config(), name)
        log.warning("config: '%s' %s; usando o padrao (%r)", name, why, default)
        setattr(self, name, default)

    def _check_choice(self, name: str, choices: tuple) -> None:
        if getattr(self, name) not in choices:
            self._reset(name, f"deve ser um de {', '.join(choices)}")

    # ------------------------------------------------------------------ arquivo
    @classmethod
    def load(cls, path: Optional[os.PathLike] = None) -> "Config":
        path = Path(path) if path else default_config_path()
        cfg = cls()
        cfg.path = path
        if not path.exists():
            try:
                cfg.save()          # cria o arquivo com os padroes para voce editar
            except OSError as e:
                log.warning("nao consegui criar %s: %s", path, e)
            return cfg
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("config ilegivel (%s); usando os padroes. Arquivo: %s", e, path)
            return cfg
        if not isinstance(raw, dict):
            log.warning("config deve ser um objeto JSON; usando os padroes")
            return cfg
        known = {f.name for f in fields(cls)}
        for key, value in raw.items():
            if key not in known:
                log.warning("config: chave desconhecida ignorada: %s", key)
            elif key == "shortcuts" and isinstance(value, dict):
                merged = dict(DEFAULT_SHORTCUTS)   # atalhos que voce nao citou continuam padrao
                merged.update(value)
                cfg.shortcuts = merged
            else:
                setattr(cfg, key, value)
        cfg.validate()
        return cfg

    def save(self, path: Optional[os.PathLike] = None) -> None:
        target = Path(path) if path else getattr(self, "path", None) or default_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {f.name: getattr(self, f.name) for f in fields(self)}
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, target)


def _clamp(value, low, high):
    return max(low, min(high, value))

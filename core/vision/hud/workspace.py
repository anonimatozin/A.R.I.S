"""Workspace de pastas/3D do HUD — aba ARQUIVOS.

Lógica pura (sem pygame) para abrir pastas num jail seguro, manipular
itens com gestos (abrir/mover/expandir/girar) e o motor de 2 mãos com
hysteresis. Inspirado em github.com/jaredrhod/barehands
(Jared Rhodenizer, AGPL-3.0-or-later) — jail de mídia, tap abre/fecha,
pinça arrasta, 2 mãos = zoom+rotação, garra = force-pull, R = grid.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from core.vision.hud.barehands import release_bar

# Hysteresis da pinça (entra fácil, sai difícil — anti-jitter)
PINCH_ENTER = 0.05
PINCH_EXIT = 0.07

# Pinça por RAZÃO gap/tamanho-mão (barehands): invariante de escala —
# mesmo limiar perto ou longe da câmera, ao contrário da distância crua.
RATIO_ENTER = 0.32        # ceiling padrão (aspect >= 2.0)
RATIO_ENTER_SIDE = 0.38   # ceiling em visão frontal/encurtada (aspect < 2.0)
RATIO_RELEASE = 0.55      # barra lenta de soltura (release_bar(0) do barehands)
RATIO_RELEASE_FAST = 0.70 # barra rápida (release_bar(>800px/s) do barehands)
HIST_WINDOW = 0.20        # janela do histórico pré-release em segundos
SPEED_FAST = 800.0        # px/s: acima disso a soltura é rápida (barehands)

# Card do HUD mede 210x130 — o hit-test é retangular: o raio antigo de 90px
# perdia os cantos e o tap "não abria" a pasta.
CARD_W, CARD_H = 210, 130
TAP_MAX_DUR = 0.5         # janela do tap (mirar devagar não vira place)
TAP_MAX_MOVE = 48.0       # px: soltura parada perto do início = tap (mesmo segurando)
FIST_CURL_ENTER = 0.65    # 0 = mão aberta, ~1 = punho (2 punhos = reset)
HOLO_HIT_MIN = 70.0       # raio mínimo do central (escala mínima)
HOLO_HIT_R = 130.0        # raio do central = cantos desenhados (130 * escala)
THROW_DAMP = 2.2          # amortecimento do arremesso (1/s)
THROW_STOP = 4.0          # px/s: abaixo disso o card parou de voar

# Extensões que a aba do HUD sabe abrir: texto = leitura 3D, modelo = viewer
TEXT_EXTS = frozenset({".txt", ".md", ".log", ".py", ".json", ".csv",
                       ".ini", ".cfg", ".rst", ".srt", ".yml", ".yaml", ".toml"})
MODEL_EXTS = frozenset({".obj", ".stl", ".glb", ".gltf"})
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
                        ".ico", ".tga", ".ppm"})
ARCHIVE_EXTS = frozenset({".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2"})
MEDIA_EXTS = frozenset({".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv",
                        ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"})
DOC_EXTS = frozenset({".pdf", ".doc", ".docx", ".xls", ".xlsx",
                      ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf"})
EXE_EXTS = frozenset({".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh", ".com"})


def file_category(path: Path) -> str:
    """Categoria do arquivo -> define ícone, cor e ação do card.

    'text' e 'model' abrem a aba do HUD; 'image'/'archive' têm aba própria;
    'media'/'doc'/'exe'/'file' abrem no programa padrão do sistema.
    """
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return "text"
    if ext in MODEL_EXTS:
        return "model"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in ARCHIVE_EXTS:
        return "archive"
    if ext in MEDIA_EXTS:
        return "media"
    if ext in DOC_EXTS:
        return "doc"
    if ext in EXE_EXTS:
        return "exe"
    return "file"


def is_text_path(path: Path) -> bool:
    """Arquivo de texto que a aba de leitura abre."""
    return path.suffix.lower() in TEXT_EXTS


def is_model_path(path: Path) -> bool:
    """Modelo 3D (só .obj/.stl têm renderizador — glTF é binário)."""
    return path.suffix.lower() in MODEL_EXTS


def _norm(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


_FOLDER_CMD = re.compile(
    r"(?:abre|abrir|mostra(?:r)?|exibe|exibir)\s+(?:a\s+)?(?:pasta\s+)?(.+?)"
    r"(?:\s+na\s+(?:camera|tela|câmera))?\s*$"
)

# Nomes amigáveis -> pastas conhecidas do Windows (só leitura/lista)
KNOWN_FOLDERS = {
    "documentos": "Documents",
    "downloads": "Downloads",
    "imagens": "Pictures",
    "fotos": "Pictures",
    "videos": "Videos",
    "vídeos": "Videos",
    "musicas": "Music",
    "músicas": "Music",
    "musica": "Music",
    "desktop": "Desktop",
    "area de trabalho": "Desktop",
    "área de trabalho": "Desktop",
}


def match_folder_command(text: str) -> str | None:
    """'aris abre pasta docs na camera' -> 'docs'; 'abre a lixeira' -> 'a lixeira'.

    Retorna o alvo cru; a resolução decide se existe (senão, a ARIS trata).
    """
    m = _FOLDER_CMD.search(_norm(text))
    if not m:
        return None
    name = m.group(1).strip().strip("'\"")
    if not name or len(name) > 120:
        return None
    return name


def _home() -> Path:
    return Path.home()


def list_recycle_bin() -> list[str] | None:
    """Lista a lixeira via winshell (opcional); None se indisponível."""
    try:
        import winshell
        return [str(item.original_filename())
                for item in list(winshell.recycle_bin())][:50]
    except Exception:
        return None


def resolve_folder(name: str, jail: Path) -> tuple[Path | None, str, str]:
    """Resolve nome -> (path, rótulo, modo).

    Retorna path None com modo 'recycle' (lixeira sem winshell) ou
    'missing'. Listagem é só-leitura: qualquer pasta existente vale.
    """
    key = _norm(name).strip()
    if key in ("lixeira", "a lixeira", "recycle", "recycle bin"):
        names = list_recycle_bin()
        if names is not None:
            return names, "Lixeira", "recycle-list"
        return None, "Lixeira", "recycle"
    if key in KNOWN_FOLDERS:
        cand = _home() / KNOWN_FOLDERS[key]
        if cand.is_dir():
            return cand, key, "dir"
    # Nome simples: jail primeiro, depois pastas do home
    if "/" not in key and "\\" not in key and ".." not in key:
        jb = safe_join(jail, key)
        if jb is not None and jb.is_dir():
            return jb, key, "dir"
        for base in (_home(), _home() / "Documents", _home() / "Desktop",
                     _home() / "Downloads"):
            try:
                cand = next((p for p in base.iterdir()
                             if p.is_dir() and _norm(p.name) == key), None)
            except OSError:
                cand = None
            if cand is not None:
                return cand, cand.name, "dir"
    # Caminho explícito existente (só-leitura)
    try:
        cand = Path(name).expanduser()
        if cand.is_dir():
            return cand, cand.name, "dir"
    except Exception:
        pass
    return None, key, "missing"


def safe_join(root: Path, name: str) -> Path | None:
    """Junta nome ao jail; None se traversal ou inexistente."""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    target = (root / name).resolve()
    if target != (root.resolve() / name):
        return None
    if not target.exists():
        return None
    return target


@dataclass
class WorkspaceItem:
    id: str
    name: str
    kind: str  # 'folder' | 'file' | 'model3d' | 'back'
    cat: str = ""  # categoria do arquivo: text/image/archive/media/doc/exe/file
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    open: bool = False
    children: list = field(default_factory=list)
    vx: float = 0.0  # arremesso (flick): px/s; a física some o card da tela
    vy: float = 0.0


def _span(hand) -> float:
    """Tamanho da mão: pulso -> base do médio + pulso -> base do mindinho."""
    w0 = hand[0]
    return (math.hypot(hand[5][0] - w0[0], hand[5][1] - w0[1])
            + math.hypot(hand[17][0] - w0[0], hand[17][1] - w0[1]))


def pinch_ratio(hand) -> float:
    """Razão gap(4,8)/tamanho da mão — pinça relativa ao tamanho (barehands).

    Invariante de escala/tradução: perto ou longe da câmera o mesmo gesto
    gera o mesmo número (0 = pontas coladas, >0.45 = mão aberta).
    """
    span = _span(hand)
    if span <= 1e-6:
        return 1.0
    gap = math.hypot(hand[4][0] - hand[8][0], hand[4][1] - hand[8][1])
    return gap / span


def hand_aspect(hand) -> float:
    """span/palmW — encurtamento da palma (barehands aspect; >6 = punho/fake)."""
    span = _span(hand)
    palm = math.hypot(hand[5][0] - hand[17][0], hand[5][1] - hand[17][1])
    return span / palm if palm > 1e-6 else 9.0


def ratio_enter_ceiling(aspect: float) -> float:
    """Ceiling de entrada por regime de orientação (barehands v3.8)."""
    return RATIO_ENTER_SIDE if aspect < 2.0 else RATIO_ENTER


def card_hit(it: WorkspaceItem, x: float, y: float) -> bool:
    """Hit-test retangular do card 210x130 (contam os cantos, não o raio)."""
    return (abs(x - it.x) <= CARD_W * 0.5 * it.scale
            and abs(y - it.y) <= CARD_H * 0.5 * it.scale)


def holo_hit(x: float, y: float, cx: float, cy: float, scale: float) -> bool:
    """Acerto do central holográfico — bate com os cantos desenhados (130*s)."""
    return math.hypot(x - cx, y - cy) <= max(HOLO_HIT_MIN, HOLO_HIT_R * scale)


def fist_curl(hand: Sequence[tuple[float, float]]) -> float:
    """Curl das pontas: 0 = mão aberta, ~1 = punho fechado.

    Média das pontas (8,12,16,20) ao pulso dividida pelo tamanho da mão —
    invariante de escala, como o resto da camada. Pinça com dedos esticados
    fica ~0.3 (não confunde com punho); punho real fica >0.7.
    """
    span = _span(hand)
    if span <= 1e-6:
        return 0.0
    w0 = hand[0]
    tips = (8, 12, 16, 20)
    mean = sum(math.hypot(hand[i][0] - w0[0], hand[i][1] - w0[1])
               for i in tips) / len(tips)
    # 0.85 = pontas longe do pulso (aberta); 0.45 = punho; span normaliza
    return max(0.0, min(1.0, (0.85 - mean / span) / 0.45))


class HandPinch:
    """Máquina de estado da pinça com hysteresis (uma instância por mão).

    Dois regimes:
      * padrão: distância absoluta normalizada (PINCH_ENTER/PINCH_EXIT);
      * speed_aware: razão gap/tamanho-mão com release bar sensível à
        velocidade pré-release — 0.55 lento, 0.70 rápido (barehands).
    """

    def __init__(self, enter: float | None = None, exit_: float | None = None,
                 *, speed_aware: bool = False) -> None:
        self.speed_aware = speed_aware
        self.enter = (RATIO_ENTER if speed_aware else PINCH_ENTER) if enter is None else enter
        self.exit = (RATIO_RELEASE if speed_aware else PINCH_EXIT) if exit_ is None else exit_
        self.pinched = False
        self.down_at = 0.0  # para tap (pinça rápida = abrir/fechar)
        self.down_x = 0.0   # onde a pinça começou (tap vale pela soltura)
        self.down_y = 0.0
        self.armed = False  # uma soltura por pinça (sem re-fire no quadro aberto)
        self.x = 0.0
        self.y = 0.0
        self.last_speed = 0.0  # px/s medidos antes da soltura (pré-release)
        self.open_prev = False
        self._hist: list[tuple[float, float, float]] = []  # (t, x, y) tela px

    def pre_release_speed(self, now: float) -> float:
        """Velocidade px/s na janela ~200ms anterior a `now` (barehands hspd).

        Só amostras já gravadas contam: o quadro atual nunca entra, então a
        velocidade usada para soltar é sempre a pré-release.
        """
        cut = now - HIST_WINDOW
        while self._hist and self._hist[0][0] < cut:
            self._hist.pop(0)
        if len(self._hist) < 2:
            return 0.0
        t0, x0, y0 = self._hist[0]
        t1, x1, y1 = self._hist[-1]
        dt = t1 - t0
        if dt <= 0:
            return 0.0
        return math.hypot(x1 - x0, y1 - y0) / dt

    def update(self, dist: float, x: float, y: float, now: float,
               aspect: float | None = None) -> bool:
        """Avalia o gesto; `dist` é distância (padrão) ou razão (speed_aware)."""
        speed = self.pre_release_speed(now)
        self.last_speed = speed
        if self.speed_aware:
            enter_at = self.enter if aspect is None else ratio_enter_ceiling(aspect)
            exit_at = release_bar(speed)
            open_read = dist >= exit_at
            # Rápido: exige dois quadros "abertos" para não soltar no tremor
            rel = (open_read and self.open_prev) if speed > SPEED_FAST else open_read
            self.open_prev = open_read
        else:
            enter_at, rel = self.enter, dist > self.exit
        if not self.pinched and dist < enter_at:
            self.pinched = True
            self.down_at = now
            self.down_x, self.down_y = x, y
            self.armed = True
        elif self.pinched and rel:
            self.pinched = False
        # smoothing 0.45 (barehands)
        self.x += (x - self.x) * 0.45 if (self.x or self.y) else x
        self.y += (y - self.y) * 0.45 if (self.x or self.y) else y
        if not self.pinched:
            self.x, self.y = x, y
        self._hist.append((now, x, y))
        return self.pinched

    def is_tap(self, now: float, max_dur: float = TAP_MAX_DUR) -> bool:
        return (now - self.down_at) <= max_dur

    def moved(self, x: float, y: float) -> float:
        """Distância da soltura até o ponto em que a pinça começou (px)."""
        return math.hypot(x - self.down_x, y - self.down_y)

    def reset(self) -> None:
        """Mão perdida: zera pinça, histórico e velocidade."""
        self.pinched = False
        self.armed = False
        self.open_prev = False
        self.last_speed = 0.0
        self._hist.clear()


def map_landmark(ix: float, iy: float, mirror: bool, w: float, h: float) -> tuple[float, float]:
    """Landmark normalizado -> pixel na tela, com UM espelho só.

    Os landmarks vêm do sensor cru (sem flip); o display e o cursor usam
    o mesmo flag `mirror`, então a mão nunca inverte em relação ao cursor.
    """
    sx = ((1.0 - ix) if mirror else ix) * w
    sy = iy * h
    sx = max(0.0, min(w, sx))
    sy = max(0.0, min(h, sy))
    return sx, sy


def pinch_scale(prev_dist: float, dist: float, gain: float = 2.0) -> float:
    """Delta de escala a partir da variação da distância entre mãos."""
    if prev_dist <= 0:
        return 0.0
    return (dist - prev_dist) * gain


def pinch_angle_delta(prev_ang: float, ang: float) -> float:
    """Delta angular normalizado (-pi, pi] para rotação com 2 mãos."""
    d = ang - prev_ang
    while d > math.pi:
        d -= 2 * math.pi
    while d <= -math.pi:
        d += 2 * math.pi
    return d


def zoom_factor(prev_dist: float, dist: float) -> float:
    """dist/prev — fator de zoom relativo (1.0 = parado, invariante de escala).

    O delta absurdo (px * gain) jogava o card direto no teto de escala com
    1px de ruído; o fator relativo mantém o zoom proporcional à abertura.
    """
    if prev_dist <= 1e-6 or dist <= 1e-6:
        return 1.0
    return dist / prev_dist


class WorkspaceManager:
    """Pastas abertas como itens manipuláveis (jail em workspace/)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.items: list[WorkspaceItem] = []
        self.current: str | None = None
        self._current_path: Path | None = None
        # Pilha de navegação (tap em pasta entra, card "VOLTAR" sai)
        self._stack: list[tuple[str | None, Path | None, list[WorkspaceItem]]] = []

    def open_default(self) -> list[WorkspaceItem]:
        """Abre 'docs' se existir, senão a primeira pasta do jail."""
        if (self.root / "docs").is_dir():
            return self.open_folder("docs")
        try:
            first = sorted(p.name for p in self.root.iterdir() if p.is_dir())
        except OSError:
            first = []
        if first:
            return self.open_folder(first[0])
        return []

    def open_folder(self, name: str) -> list[WorkspaceItem]:
        """Abre qualquer pasta pedida: jail, conhecidas, caminho ou lixeira."""
        self._stack.clear()  # raiz da navegação: sem card VOLTAR
        resolved, label, mode = resolve_folder(name, self.root)
        if mode == "recycle-list":
            return self._load_names("Lixeira", ["🗑 " + n for n in (resolved or [])])
        if mode == "recycle":
            self.items = [WorkspaceItem(id="lixeira", name="Lixeira (abrir no Explorer)",
                                        kind="folder", x=640, y=300, open=True,
                                        children=["Toque para abrir no Explorer"])]
            self.current = "Lixeira"
            self._current_path = None
            return self.items
        if resolved is None or not resolved.is_dir():
            return []
        return self._load_items(label, resolved)

    def _load_items(self, label: str, path: Path) -> list[WorkspaceItem]:
        items: list[WorkspaceItem] = []
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return []
        for i, p in enumerate(entries[:12]):
            if p.is_dir():
                kind, cat = "folder", ""
            else:
                kind = "model3d" if is_model_path(p) else "file"
                cat = file_category(p)
            items.append(WorkspaceItem(
                id=f"{label}/{p.name}", name=p.name, kind=kind, cat=cat,
                x=120 + (i % 4) * 260, y=140 + (i // 4) * 200,
            ))
        self.items = items
        self.current = label
        self._current_path = path
        return items

    def _load_names(self, label: str, names: list[str]) -> list[WorkspaceItem]:
        items = [WorkspaceItem(
            id=f"{label}/{n}", name=n, kind="file",
            x=120 + (i % 4) * 260, y=140 + (i // 4) * 200,
        ) for i, n in enumerate(names[:12])]
        self.items = items
        self.current = label
        self._current_path = None
        return items

    def tap(self, x: float, y: float, now: float) -> WorkspaceItem | None:
        """Tap navega na pasta, volta ou expande item (hit-test retangular)."""
        for it in reversed(self.items):
            if not card_hit(it, x, y):
                continue
            if it.kind == "back":
                self.back()
                return it
            if it.id == "lixeira":
                try:
                    import os as _os
                    _os.startfile("shell:RecycleBinFolder")
                except Exception:
                    pass
                it.open = True
                return it
            if it.kind == "folder":
                # Tap em pasta = ENTRAR nela (sub-itens viram cards)
                if self.enter(it):
                    return it
                # Subpasta indisponível: expande/recolhe no lugar
                if not it.open:
                    base = self._current_path
                    sub = (base / it.name) if base is not None else None
                    if sub is not None and sub.is_dir():
                        try:
                            kids = sorted(sub.iterdir(), key=lambda p: p.name.lower())[:8]
                        except OSError:
                            kids = []
                        it.children = [c.name for c in kids]
                    it.open = True
                else:
                    it.open = False
                return it
            it.open = not it.open
            return it
        return None

    def enter(self, item: WorkspaceItem) -> bool:
        """Empilha a vista atual e carrega os sub-itens de `item` como cards."""
        path = self._child_path(item)
        if path is None:
            return False
        self._stack.append((self.current, self._current_path, list(self.items)))
        self._load_items(path.name, path)
        self._append_back()
        return True

    def back(self) -> list[WorkspaceItem]:
        """Volta para a pasta anterior (restaura a vista empilhada)."""
        if not self._stack:
            return self.items
        label, path, items = self._stack.pop()
        self.items = items
        self.current = label
        self._current_path = path
        return self.items

    def clear(self) -> None:
        """Reset do HUD: some todos os cards (nada do disco é tocado)."""
        self.items = []
        self.current = None
        self._current_path = None
        self._stack.clear()

    def dismiss(self, item: WorkspaceItem) -> bool:
        """Remove o card da vista atual (arquivo intocado; VOLTAR é fixo)."""
        if item.kind == "back" or item not in self.items:
            return False
        self.items.remove(item)
        return True

    def step(self, dt: float, width: float, height: float,
             skip: WorkspaceItem | None = None) -> list[WorkspaceItem]:
        """Integra o arremesso (flick) e remove o que saiu inteiro da tela."""
        removed: list[WorkspaceItem] = []
        if dt > 0 and self.items:
            damp = math.exp(-THROW_DAMP * dt)
            alive: list[WorkspaceItem] = []
            for it in self.items:
                if it.vx or it.vy:
                    it.vx *= damp
                    it.vy *= damp
                    if abs(it.vx) < THROW_STOP and abs(it.vy) < THROW_STOP:
                        it.vx = it.vy = 0.0
                    it.x += it.vx * dt
                    it.y += it.vy * dt
                if it is not skip and self._outside(it, width, height):
                    removed.append(it)
                    continue
                alive.append(it)
            if removed:
                self.items = alive
        return removed

    @staticmethod
    def _outside(it: WorkspaceItem, width: float, height: float) -> bool:
        hw = CARD_W * 0.5 * it.scale
        hh = CARD_H * 0.5 * it.scale
        return (it.x + hw < 0 or it.x - hw > width
                or it.y + hh < 0 or it.y - hh > height)

    def _child_path(self, item: WorkspaceItem) -> Path | None:
        """Caminho da subpasta de `item` (nome vem do listing: sem traversal)."""
        name = item.name
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            return None
        base = self._current_path if self._current_path is not None else self.root
        cand = base / name
        return cand if cand.is_dir() else None

    def _append_back(self) -> None:
        """Card VOLTAR no rodapé livre (fora da TELEMETRIA, sem sobrepor o grid)."""
        if not self._stack or any(i.kind == "back" for i in self.items):
            return
        self.items.append(WorkspaceItem(id="__back__", name="VOLTAR",
                                        kind="back", x=350.0, y=690.0))

    def grab_at(self, x: float, y: float) -> WorkspaceItem | None:
        for it in reversed(self.items):
            if it.kind != "back" and card_hit(it, x, y):
                return it
        return None

    def path_of(self, item: WorkspaceItem) -> Path | None:
        """Arquivo de disco por trás do card (None se não for arquivo real)."""
        name = item.name
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            return None
        base = self._current_path if self._current_path is not None else self.root
        cand = base / name
        return cand if cand.is_file() else None

    def grid(self) -> None:
        for i, it in enumerate(self.items):
            it.x = 120 + (i % 4) * 260
            it.y = 140 + (i // 4) * 200
            it.vx = it.vy = 0.0

    def claw_pull(self, x: float, y: float) -> WorkspaceItem | None:
        """Garra puxa o item mais distante para perto do cursor."""
        if not self.items:
            return None
        far = max(self.items, key=lambda it: math.hypot(x - it.x, y - it.y))
        if math.hypot(x - far.x, y - far.y) > 150:
            far.x, far.y = x, y
            far.vx = far.vy = 0.0
            return far
        return None

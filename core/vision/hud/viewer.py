"""Aba do HUD para documentos: página de texto em 3D + modelo 3D.

Sem OpenGL: a página é deformada em perspectiva por homografia exata
(rotação do plano — bordas sempre retas, remapeamento bilinear em numpy),
então o gesto de girar com 2 mãos vira rotação de verdade. O modelo 3D tem
renderizador próprio (model3d.py).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pygame
from PIL import Image

from core.vision.hud.model3d import Mesh

# Geometria da aba (px na tela, antes da escala do gesto)
VIEW_W, VIEW_H = 680, 470
TITLE_H = 26
LINE_H = 18            # altura de linha da fonte Consolas 14
FOCAL = 1100.0         # distância focal da projeção (px)
PAD = 4                # margem da superfície warpada (cantos não cortam)

# Limites do gesto (2 mãos: giro = yaw+pitch, abertura = escala, médio = pan)
YAW_MAX = 1.35         # ~77°
PITCH_MAX = 0.95       # ~54°
PITCH_RATIO = 0.5      # pitch acompanha o yaw (a câmera só enxerga 2 eixos)
SCALE_MIN, SCALE_MAX = 0.45, 1.5

MAX_TEXT_LINES = 400
MAX_TEXT_BYTES = 131072


def read_text_lines(path: str | Path, max_lines: int = MAX_TEXT_LINES,
                    max_bytes: int = MAX_TEXT_BYTES) -> list[str]:
    """Linhas do arquivo com fallback de encoding (utf-8 -> cp1252)."""
    data = Path(path).read_bytes()[:max_bytes]
    for enc in ("utf-8", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode(enc, errors="replace")
    return text.splitlines()[:max_lines]


def load_image_surface(path: str | Path, max_w: int = VIEW_W,
                       max_h: int = VIEW_H) -> pygame.Surface:
    """Imagem (qualquer formato Pillow) ajustada para caber na aba."""
    im = Image.open(path).convert("RGBA")
    im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    return pygame.image.frombytes(im.tobytes(), im.size, "RGBA")


def read_archive_lines(path: str | Path, max_entries: int = 300) -> list[str]:
    """Lista o conteúdo de .zip/.tar/.gz como linhas (para a aba de leitura).

    Formatos sem leitor em Python puro (.rar/.7z) lançam ValueError — o
    chamador cai no "abrir no programa padrão" do sistema.
    """
    import tarfile
    import zipfile

    p = Path(path)
    names: list[str] = []
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as zf:
            infos = zf.infolist()
            total = len(infos)
            names = [i.filename for i in infos[:max_entries]]
            size_sum = sum(i.file_size for i in infos)
    elif tarfile.is_tarfile(p):
        with tarfile.open(p) as tf:
            members = tf.getmembers()
            total = len(members)
            names = [m.name for m in members[:max_entries]]
            size_sum = sum(m.size for m in members[:max_entries])
    else:
        raise ValueError(f"{p.name}: formato compactado sem leitor")
    head = [f"{p.name}  //  {total} itens  ·  {size_sum // 1024} KB", ""]
    return head + names


def _homography_yaw(yaw: float, focal: float = FOCAL) -> np.ndarray:
    """Homografia da rotação do plano em torno do eixo vertical (yaw)."""
    c, s = math.cos(yaw), math.sin(yaw)
    out: np.ndarray = np.array([
        [focal * c, 0.0, 0.0],
        [0.0, focal, 0.0],
        [-s, 0.0, focal],
    ], dtype=np.float64)
    return out


def _homography_pitch(pitch: float, focal: float = FOCAL) -> np.ndarray:
    """Homografia da rotação em torno do eixo horizontal (pitch > 0 = topo p/ trás)."""
    c, s = math.cos(pitch), math.sin(pitch)
    out: np.ndarray = np.array([
        [focal, 0.0, 0.0],
        [0.0, focal * c, 0.0],
        [0.0, -s, focal],
    ], dtype=np.float64)
    return out


def _corners(w: int, h: int) -> np.ndarray:
    """Cantos do retângulo centrado na origem (coordenadas do plano)."""
    cx, cy = w / 2.0, h / 2.0
    out: np.ndarray = np.array([[-cx, -cy], [cx, -cy], [cx, cy], [-cx, cy]],
                               dtype=np.float64)
    return out


def _forward(hom: np.ndarray, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Projeta pts (N,2) pela homografia hom; devolve (x, y, w) do denominador."""
    x = hom[0, 0] * pts[:, 0] + hom[0, 1] * pts[:, 1] + hom[0, 2]
    y = hom[1, 0] * pts[:, 0] + hom[1, 1] * pts[:, 1] + hom[1, 2]
    w = hom[2, 0] * pts[:, 0] + hom[2, 1] * pts[:, 1] + hom[2, 2]
    ws = np.where(np.abs(w) < 1e-9, 1e-9, w)
    return x / ws, y / ws, w


def _bilinear(img: np.ndarray, sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    """Amostragem bilinear (img: (W, H, C) float32; sx/sy em px de origem)."""
    iw, ih = img.shape[0], img.shape[1]
    valid = (sx >= 0) & (sx <= iw - 1) & (sy >= 0) & (sy <= ih - 1)
    sx = np.clip(sx, 0.0, iw - 1.0)
    sy = np.clip(sy, 0.0, ih - 1.0)
    x0: np.ndarray = sx.astype(np.intp)
    y0: np.ndarray = sy.astype(np.intp)
    x1 = np.minimum(x0 + 1, iw - 1)
    y1 = np.minimum(y0 + 1, ih - 1)
    fx = (sx - x0).astype(np.float32)[..., None]
    fy = (sy - y0).astype(np.float32)[..., None]
    i00 = img[x0, y0]
    i10 = img[x1, y0]
    i01 = img[x0, y1]
    i11 = img[x1, y1]
    out: np.ndarray = ((i10 * fx + i00 * (1.0 - fx)) * (1.0 - fy)
                       + (i11 * fx + i01 * (1.0 - fx)) * fy)
    out[~valid] = 0.0
    return out


def _warp_pil(surf: pygame.Surface, hom: np.ndarray, ox: float, oy: float,
              out_w: int, out_h: int) -> pygame.Surface:
    """Remapeamento homográfico via Pillow (C puro, ~9x mais rápido que numpy)."""
    w, h = surf.get_size()
    inv = np.linalg.inv(hom)
    a, b = inv[2, 0], inv[2, 1]
    c = a * ox + b * oy + inv[2, 2]
    if abs(c) < 1e-9:
        raise ValueError("denominador homográfico nulo")
    d0 = inv[0, 0] * ox + inv[0, 1] * oy + inv[0, 2]
    d1 = inv[1, 0] * ox + inv[1, 1] * oy + inv[1, 2]
    # PIL pede src = f(dst) em coords de pixel (canto superior esquerdo);
    # compõe inversa + centro do plano + offset da saída numa única homografia.
    coeffs = (
        (inv[0, 0] + (w / 2.0) * a) / c,
        (inv[0, 1] + (w / 2.0) * b) / c,
        (d0 + (w / 2.0) * c) / c,
        (inv[1, 0] + (h / 2.0) * a) / c,
        (inv[1, 1] + (h / 2.0) * b) / c,
        (d1 + (h / 2.0) * c) / c,
        a / c,
        b / c,
    )
    src = Image.frombytes("RGBA", (w, h), pygame.image.tobytes(surf, "RGBA"))
    dst = src.transform((out_w, out_h), Image.Transform.PERSPECTIVE, coeffs,
                        Image.Resampling.BILINEAR, fillcolor=(0, 0, 0, 0))
    return pygame.image.frombytes(dst.tobytes(), (out_w, out_h), "RGBA")


def _warp_numpy(surf: pygame.Surface, hom: np.ndarray, ox: float, oy: float,
                out_w: int, out_h: int) -> pygame.Surface:
    """Remapeamento homográfico em numpy (fallback seguro sem Pillow)."""
    w, h = surf.get_size()
    try:
        inv = np.linalg.inv(hom)
    except np.linalg.LinAlgError:
        return surf
    gx = np.arange(out_w, dtype=np.float64) + ox
    gy = np.arange(out_h, dtype=np.float64) + oy
    grid_x: np.ndarray
    grid_y: np.ndarray
    grid_x, grid_y = np.meshgrid(gx, gy)
    wp = inv[2, 0] * grid_x + inv[2, 1] * grid_y + inv[2, 2]
    wp = np.where(np.abs(wp) < 1e-9, 1e-9, wp)
    sx = (inv[0, 0] * grid_x + inv[0, 1] * grid_y + inv[0, 2]) / wp + w / 2.0
    sy = (inv[1, 0] * grid_x + inv[1, 1] * grid_y + inv[1, 2]) / wp + h / 2.0
    rgb = pygame.surfarray.array3d(surf)
    alpha = pygame.surfarray.array_alpha(surf)[..., None]
    img = np.dstack([rgb, alpha]).astype(np.float32)
    out: np.ndarray = _bilinear(img, sx, sy).astype(np.uint8)
    return pygame.image.frombytes(out.tobytes(), (out_w, out_h), "RGBA")


def _warp_perspective(surf: pygame.Surface, hom: np.ndarray) -> pygame.Surface:
    """Remapeia a superfície pela homografia hom (bordas retas, bilinear)."""
    w, h = surf.get_size()
    xs, ys, den = _forward(hom, _corners(w, h))
    if (not np.all(np.isfinite(xs)) or not np.all(np.isfinite(ys))
            or np.any(den <= 1e-6)):
        return surf
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    out_w = max(4, int(math.ceil(x1 - x0)) + 2 * PAD)
    out_h = max(4, int(math.ceil(y1 - y0)) + 2 * PAD)
    ox, oy = x0 - PAD, y0 - PAD
    try:
        return _warp_pil(surf, hom, ox, oy, out_w, out_h)
    except Exception:   # noqa: BLE001 - qualquer falha cai no caminho numpy
        return _warp_numpy(surf, hom, ox, oy, out_w, out_h)


def warp_yaw(surf: pygame.Surface, yaw: float, focal: float = FOCAL) -> pygame.Surface:
    """Gira a página em torno do eixo vertical (homografia exata do plano).

    Rotação 3D real: as bordas saem sempre retas e a página afina ao girar
    (lado mais perto cresce, o mais longe encolhe) — sem costura de tira.
    """
    if abs(yaw) < 0.02:
        return surf
    w, h = surf.get_size()
    if w < 2 or h < 2:
        return surf
    return _warp_perspective(surf, _homography_yaw(yaw, focal))


def warp_pitch(surf: pygame.Surface, pitch: float, focal: float = FOCAL) -> pygame.Surface:
    """Inclina a página em torno do eixo horizontal (mesma homografia exata)."""
    if abs(pitch) < 0.02:
        return surf
    w, h = surf.get_size()
    if w < 2 or h < 2:
        return surf
    return _warp_perspective(surf, _homography_pitch(pitch, focal))


def warped_size(w: int, h: int, yaw: float, pitch: float,
                focal: float = FOCAL) -> tuple[int, int]:
    """Tamanho final da página após warp_yaw + warp_pitch (layout e hit-test).

    Reproduz o pipeline etapa a etapa (bbox + margem por warp) para casar
    com a superfície realmente desenhada em _viewer_body.
    """
    if abs(yaw) >= 0.02:
        xs, ys, den = _forward(_homography_yaw(yaw, focal), _corners(w, h))
        if (not np.all(np.isfinite(xs)) or not np.all(np.isfinite(ys))
                or np.any(den <= 1e-6)):
            return w, h
        w = max(4, int(math.ceil(float(xs.max() - xs.min()))) + 2 * PAD)
        h = max(4, int(math.ceil(float(ys.max() - ys.min()))) + 2 * PAD)
    if abs(pitch) >= 0.02:
        xs, ys, den = _forward(_homography_pitch(pitch, focal), _corners(w, h))
        if (not np.all(np.isfinite(xs)) or not np.all(np.isfinite(ys))
                or np.any(den <= 1e-6)):
            return w, h
        w = max(4, int(math.ceil(float(xs.max() - xs.min()))) + 2 * PAD)
        h = max(4, int(math.ceil(float(ys.max() - ys.min()))) + 2 * PAD)
    return w, h


class DocViewer:
    """Aba flutuante: texto (página 3D), imagem ou modelo 3D."""

    def __init__(self) -> None:
        self.visible = False
        self.kind = "text"          # 'text' | 'model' | 'image'
        self.path: Path | None = None
        self.name = ""
        self.lines: list[str] = []
        self.mesh: Mesh | None = None  # quando kind == 'model'
        self.image: pygame.Surface | None = None  # quando kind == 'image'
        self.scroll = 0.0           # primeira linha visível (fracionária)
        self.x = 640.0
        self.y = 400.0
        self.scale = 1.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.rev = 0                # invalida caches de render

    # ── abertura/fechamento ────────────────────────────────────
    def open_text(self, path: str | Path,
                  center: tuple[float, float] | None = None) -> list[str]:
        self.path = Path(path)
        self.name = self.path.name
        self.lines = read_text_lines(self.path)
        self.mesh = None
        self.image = None
        self.kind = "text"
        self._reset(yaw=0.0, pitch=0.0, center=center)
        return self.lines

    def open_model(self, path: str | Path, mesh: Mesh,
                   center: tuple[float, float] | None = None) -> None:
        self.path = Path(path)
        self.name = self.path.name
        self.mesh = mesh
        self.lines = []
        self.image = None
        self.kind = "model"
        self._reset(yaw=0.7, pitch=0.4, center=center)

    def open_image(self, path: str | Path,
                   center: tuple[float, float] | None = None) -> None:
        self.path = Path(path)
        self.name = self.path.name
        self.image = load_image_surface(self.path)
        self.mesh = None
        self.lines = []
        self.kind = "image"
        self._reset(yaw=0.0, pitch=0.0, center=center)

    def _reset(self, yaw: float, pitch: float,
               center: tuple[float, float] | None) -> None:
        self.visible = True
        self.scroll = 0.0
        self.scale = 1.0
        self.yaw = yaw
        self.pitch = pitch
        if center is not None:
            self.x, self.y = float(center[0]), float(center[1])
        self.rev += 1

    def close(self) -> None:
        self.visible = False
        self.rev += 1

    # ── gestos ─────────────────────────────────────────────────
    def rotate(self, delta: float) -> None:
        """Giro do gesto de 2 mãos: yaw + pitch travado na proporção."""
        self.yaw = max(-YAW_MAX, min(YAW_MAX, self.yaw + delta))
        self.pitch = max(-PITCH_MAX, min(PITCH_MAX,
                                         self.pitch + delta * PITCH_RATIO))

    def zoom(self, factor: float) -> None:
        self.scale = max(SCALE_MIN, min(SCALE_MAX, self.scale * factor))

    def move_by(self, dx: float, dy: float, width: float, height: float) -> None:
        self.x = max(0.0, min(float(width), self.x + dx))
        # o corpo inteiro precisa continuar na tela (sem barra de título)
        top_min = min(self.body_rect().h / 2.0, float(height) / 2.0)
        self.y = max(top_min, min(float(height), self.y + dy))

    def scroll_by_lines(self, delta: float) -> None:
        self.scroll = max(0.0, min(self.max_scroll(), self.scroll + delta))

    def max_scroll(self) -> float:
        if self.kind != "text":
            return 0.0
        visible = max(1, VIEW_H // LINE_H - 2)
        return max(0.0, float(len(self.lines) - visible))

    @property
    def first_line(self) -> int:
        return int(self.scroll)

    def line_offset_px(self) -> float:
        """Deslocamento vertical da primeira linha (subpixel do scroll)."""
        return -(self.scroll - int(self.scroll)) * LINE_H

    # ── geometria (hit-test em coordenadas de tela) ────────────
    def body_rect(self) -> pygame.Rect:
        if self.kind == "model":
            w, h = VIEW_W, VIEW_H          # modelo: superfície fixa (não afina)
        else:
            w, h = warped_size(VIEW_W, VIEW_H, self.yaw, self.pitch)
        w = max(40, int(w * self.scale))
        h = max(40, int(h * self.scale))
        rect = pygame.Rect(0, 0, w, h)
        rect.center = (int(self.x), int(self.y))
        return rect

    def title_rect(self) -> pygame.Rect:
        # Compat: a barra de título sumiu (fechar = 2 taps), mas a geometria
        # continua acima do corpo para os testes de layout.
        body = self.body_rect()
        rect = pygame.Rect(0, 0, max(160, body.w), TITLE_H)
        rect.center = (int(self.x), body.top - TITLE_H // 2 - 2)
        return rect

    def close_rect(self) -> pygame.Rect:
        title = self.title_rect()
        return pygame.Rect(title.right - 26, title.top + 3, 20, TITLE_H - 6)

    def hit(self, x: float, y: float) -> bool:
        return self.body_rect().collidepoint((int(x), int(y)))

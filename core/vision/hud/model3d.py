"""Modelo 3D em software: carrega .obj/.stl e renderiza com numpy + pygame.

Sem OpenGL/PyOpenGL (nada instalado): projeção em perspectiva + face culling
+ painter's algorithm com flat shading. Chega para capacete/armadura/personagem
de poucos milhares de faces a 60 fps.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pygame

# Câmera/escala da projeção (malha normalizada para caber em [-1, 1])
CAM_DIST = 2.8
LIGHT = (0.45, 0.75, 0.85)   # direção da luz (normalizada no cálculo)
AMBIENT = 0.30               # luz ambiente (0..1)
BASE_COLOR = (0, 176, 224)   # ciano do HUD
FALLBACK_COLOR = (170, 92, 255)  # roxo: cor quando o modelo não tem .mtl


@dataclass(eq=False)
class Mesh:
    """Malha já centralizada e ajustada para caber em [-1, 1]."""

    verts: np.ndarray   # (N, 3) float64
    faces: np.ndarray   # (M, 3) int64
    name: str = ""
    face_colors: np.ndarray | None = None  # (M, 3) uint8 — cor original (Kd do .mtl)

    @property
    def face_count(self) -> int:
        return int(len(self.faces))


def _normalize(verts: Sequence[Sequence[float]], faces: Sequence[Sequence[int]],
               name: str = "",
               colors: Sequence[tuple[int, int, int]] | None = None) -> Mesh:
    v: np.ndarray = np.asarray(verts, dtype=np.float64)
    f: np.ndarray = np.asarray(faces, dtype=np.int64)
    if v.ndim != 2 or v.shape[1] != 3 or len(v) == 0:
        raise ValueError(f"{name}: malha sem vértices")
    if f.ndim != 2 or f.shape[1] != 3 or len(f) == 0:
        raise ValueError(f"{name}: malha sem faces")
    if f.min() < 0 or f.max() >= len(v):
        raise ValueError(f"{name}: índice de face fora do intervalo")
    center = (v.min(axis=0) + v.max(axis=0)) / 2.0
    v = v - center
    extent = float(np.max(v.max(axis=0) - v.min(axis=0)))
    if extent > 1e-9:
        v = v * (2.0 / extent)
    fc: np.ndarray | None = None
    if colors is not None and len(colors) == len(f):
        fc = np.asarray(colors, dtype=np.uint8)
    return Mesh(verts=v, faces=f, name=name, face_colors=fc)


def _load_mtl(path: Path) -> dict[str, tuple[int, int, int]]:
    """Lê materiais Wavefront (.mtl): newmtl -> Kd (cor de difusão) em RGB 0..255."""
    mats: dict[str, tuple[int, int, int]] = {}
    current = ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return mats
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "newmtl" and len(parts) > 1:
            current = parts[1]
        elif parts[0] == "Kd" and current and len(parts) >= 4:
            try:
                r, g, b = (float(parts[1]), float(parts[2]), float(parts[3]))
            except ValueError:
                continue
            def clamp(c: float) -> int:
                return max(0, min(255, int(round(c * 255.0))))
            mats[current] = (clamp(r), clamp(g), clamp(b))
    return mats


def load_obj(path: str | Path) -> Mesh:
    """Lê Wavefront .obj (v/f + mtllib/usemtl para a cor original de cada face)."""
    p = Path(path)
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    face_cols: list[tuple[int, int, int]] = []
    mats: dict[str, tuple[int, int, int]] = {}
    use_mtl = False
    current: tuple[int, int, int] | None = None
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("v "):
                parts = line.split()
                verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif line.startswith("mtllib ") and not use_mtl:
                mtl_name = line.split(None, 1)[1].strip()
                mats = _load_mtl(p.parent / mtl_name)
                use_mtl = bool(mats)
            elif line.startswith("usemtl ") and use_mtl:
                current = mats.get(line.split(None, 1)[1].strip())
            elif line.startswith("f "):
                idx = []
                for tok in line.split()[1:]:
                    head = tok.split("/")[0]
                    if not head:
                        continue
                    n = int(head)
                    idx.append(n - 1 if n > 0 else len(verts) + n)
                for j in range(1, len(idx) - 1):
                    faces.append([idx[0], idx[j], idx[j + 1]])
                    if use_mtl:
                        face_cols.append(current or (185, 185, 185))
    return _normalize(verts, faces, p.name, face_cols if use_mtl else None)


def load_stl(path: str | Path) -> Mesh:
    """Lê STL ASCII (binário não é texto — manda exportar ASCII ou .obj)."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    low = text.lower()
    if not low.lstrip().startswith("solid") or "facet" not in low:
        raise ValueError(f"{p.name}: STL binário não suportado (use .obj)")
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    tri: list[list[float]] = []
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "vertex" and len(parts) >= 4:
            tri.append([float(parts[1]), float(parts[2]), float(parts[3])])
            if len(tri) == 3:
                base = len(verts)
                verts.extend(tri)
                faces.append([base, base + 1, base + 2])
                tri = []
    return _normalize(verts, faces, p.name)


def load_mesh(path: str | Path) -> Mesh:
    """Dispatch por extensão; .glb/.gltf são binários (sem renderizador)."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".obj":
        return load_obj(p)
    if suffix == ".stl":
        return load_stl(p)
    raise ValueError(f"formato {suffix or '?'} sem renderizador (use .obj ou .stl)")


def render_mesh(mesh: Mesh, width: int, height: int, yaw: float = 0.7,
                pitch: float = 0.4, color: tuple[int, int, int] = BASE_COLOR,
                ) -> pygame.Surface:
    """Renderiza a malha: perspectiva + backface culling + flat shading."""
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    v = mesh.verts
    # Ry(yaw) e depois Rx(pitch)
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)
    x, y, z = v[:, 0], v[:, 1], v[:, 2]
    x1 = x * cos_y + z * sin_y
    z1 = -x * sin_y + z * cos_y
    y2 = y * cos_p - z1 * sin_p
    z2 = y * sin_p + z1 * cos_p
    rot = np.stack([x1, y2, z2], axis=1)

    # Projeção em perspectiva (câmera em +z) com fit-to-frame:
    # todo modelo sai centralizado ocupando ~86% do quadro (tamanho uniforme)
    k = CAM_DIST / np.maximum(CAM_DIST - rot[:, 2], 0.35)
    ux = rot[:, 0] * k
    uy = rot[:, 1] * k
    span = max(float(ux.max() - ux.min()), float(uy.max() - uy.min()), 1e-9)
    fit = 0.86 * min(width, height) / span
    cx = width / 2.0 - (float(ux.max()) + float(ux.min())) / 2.0 * fit
    cy = height / 2.0 + (float(uy.max()) + float(uy.min())) / 2.0 * fit
    pts = np.stack([cx + ux * fit, cy - uy * fit], axis=1)

    tri = rot[mesh.faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nz = normals[:, 2]
    order = np.argsort(tri[:, :, 2].mean(axis=1))  # mais longe primeiro
    visible = order[nz[order] > 1e-9]
    if len(visible) < max(1, int(len(order) * 0.02)):
        visible = order  # windings invertidos: sem culling, o painter resolve

    norm = np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9)
    unit = normals / norm
    light: np.ndarray = np.asarray(LIGHT, dtype=np.float64)
    light = light / np.linalg.norm(light)
    lam = np.clip(unit @ light, 0.0, 1.0)
    shade = AMBIENT + (1.0 - AMBIENT) * lam
    if mesh.face_colors is not None:
        # Cor original do material (.mtl) por face, com o mesmo shading flat
        base: np.ndarray = mesh.face_colors.astype(np.float64)
        rgb: np.ndarray = np.clip(base * shade[:, None], 0, 255)
        palette = [tuple(int(c) for c in row) for row in rgb]
    else:
        palette = [(int(min(255, color[0] * shade[i])),
                    int(min(255, color[1] * shade[i])),
                    int(min(255, color[2] * shade[i]))) for i in range(len(order))]

    for i in visible:
        poly = [(int(pts[j, 0]), int(pts[j, 1])) for j in mesh.faces[i]]
        pygame.draw.polygon(surf, palette[i], poly)
    return surf

"""Gera a pasta de teste 'ARIS Testes' em Documentos.

Cria modelos 3D (.obj procedurais) e textos para exercitar a aba do HUD:
navegação por cards, rotação 3D em 2 mãos, scroll de texto e fechamento.

Uso:
    python assets/make_test_folder.py
"""

import math
import shutil
from pathlib import Path

OUT = Path.home() / "Documents" / "ARIS Testes"


# ── Primitivas (vértices normalizados depois pelo renderizador) ─────────
def _sphere(segs: int = 18, rings: int = 12, cut: float | None = None):
    """Esfera unitária; `cut` mantém apenas faces com centro y >= cut."""
    verts: list[tuple[float, float, float]] = []
    for r in range(rings + 1):
        phi = math.pi * r / rings
        y = math.cos(phi)
        rad = math.sin(phi)
        for s in range(segs):
            th = 2 * math.pi * s / segs
            verts.append((rad * math.cos(th), y, rad * math.sin(th)))
    faces = []
    for r in range(rings):
        for s in range(segs):
            a = r * segs + s
            b = r * segs + (s + 1) % segs
            c = (r + 1) * segs + (s + 1) % segs
            d = (r + 1) * segs + s
            faces += [[a, b, c], [a, c, d]]
    if cut is not None:
        kept = []
        for f in faces:
            cy = sum(verts[i][1] for i in f) / len(f)
            if cy >= cut:
                kept.append(f)
        faces = kept
    return verts, faces


def _box(sx: float, sy: float, sz: float):
    x, y, z = sx / 2, sy / 2, sz / 2
    verts = [(a, b, c) for a in (-x, x) for b in (-y, y) for c in (-z, z)]
    quads = [
        [0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1],
        [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3],
    ]
    faces = [[q[0], q[1], q[2]] for q in quads] + [[q[0], q[2], q[3]] for q in quads]
    return verts, faces


def _cylinder(segs: int = 14, radius: float = 1.0, height: float = 1.0):
    verts: list[tuple[float, float, float]] = []
    top, bot = height / 2, -height / 2
    for s in range(segs):
        th = 2 * math.pi * s / segs
        x, z = radius * math.cos(th), radius * math.sin(th)
        verts += [(x, top, z), (x, bot, z)]
    faces = []
    for s in range(segs):
        a, b = 2 * s, 2 * s + 1
        c, d = 2 * ((s + 1) % segs), 2 * ((s + 1) % segs) + 1
        faces += [[a, c, d], [a, d, b]]
    return verts, faces


def _place(part, dx=0.0, dy=0.0, dz=0.0, scale=1.0, sy=None, sz=None):
    verts, faces = part
    sy = scale if sy is None else sy
    sz = scale if sz is None else sz
    moved = [(x * scale + dx, y * sy + dy, z * sz + dz) for x, y, z in verts]
    return moved, [list(f) for f in faces]


def _write_obj(path: Path, parts, header: str) -> None:
    verts: list[tuple[float, float, float]] = []
    lines = [f"# {header}", "# gerado por assets/make_test_folder.py"]
    for pv, pf in parts:
        off = len(verts)
        verts += pv
        for f in pf:
            lines.append("f " + " ".join(str(i + off + 1) for i in f))
    for x, y, z in verts:
        lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")
    # v primeiro é o padrão; reordena: comentários + vs + faces
    vs = [row for row in lines if row.startswith("v ")]
    rest = [row for row in lines if not row.startswith("v ")]
    path.write_text("\n".join(rest[:2] + vs + rest[2:]) + "\n", encoding="utf-8")


# ── Modelos ─────────────────────────────────────────────────────────────
def build_helmet() -> tuple[list, list]:
    dome = _place(_sphere(cut=-0.15), scale=1.0)
    visor = _place(_box(1.5, 0.55, 0.35), dy=-0.15, dz=0.95)
    crest = _place(_box(0.16, 0.7, 1.7), dy=0.75)
    rim = _place(_box(1.9, 0.18, 1.9), dy=-0.62)
    return _merge(dome, visor, crest, rim)


def build_armor() -> tuple[list, list]:
    torso = _place(_box(1.5, 1.7, 0.9), dy=0.45)
    belt = _place(_box(1.4, 0.32, 0.8), dy=-0.62)
    pauldron_l = _place(_sphere(), dx=-1.0, dy=1.25, scale=0.5, sy=0.35, sz=0.5)
    pauldron_r = _place(_sphere(), dx=1.0, dy=1.25, scale=0.5, sy=0.35, sz=0.5)
    arm_l = _place(_cylinder(radius=0.22, height=1.6), dx=-1.0, dy=0.15)
    arm_r = _place(_cylinder(radius=0.22, height=1.6), dx=1.0, dy=0.15)
    leg_l = _place(_cylinder(radius=0.26, height=1.7), dx=-0.4, dy=-1.75)
    leg_r = _place(_cylinder(radius=0.26, height=1.7), dx=0.4, dy=-1.75)
    return _merge(torso, belt, pauldron_l, pauldron_r, arm_l, arm_r, leg_l, leg_r)


def build_character() -> tuple[list, list]:
    head = _place(_sphere(), dy=1.6, scale=0.45)
    torso = _place(_box(0.85, 1.0, 0.5), dy=0.65)
    arm_l = _place(_cylinder(radius=0.14, height=1.1), dx=-0.6, dy=0.6)
    arm_r = _place(_cylinder(radius=0.14, height=1.1), dx=0.6, dy=0.6)
    leg_l = _place(_cylinder(radius=0.17, height=1.1), dx=-0.23, dy=-0.55)
    leg_r = _place(_cylinder(radius=0.17, height=1.1), dx=0.23, dy=-0.55)
    eye_l = _place(_box(0.12, 0.1, 0.12), dx=-0.16, dy=1.68, dz=0.4)
    eye_r = _place(_box(0.12, 0.1, 0.12), dx=0.16, dy=1.68, dz=0.4)
    return _merge(head, torso, arm_l, arm_r, leg_l, leg_r, eye_l, eye_r)


def _merge(*parts):
    verts: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    for pv, pf in parts:
        off = len(verts)
        verts += pv
        faces += [[i + off for i in f] for f in pf]
    return verts, faces


# ── Textos ──────────────────────────────────────────────────────────────
def build_text_files() -> list[tuple[Path, str]]:
    longo = "\n".join(
        f"{i:04d}  linha {i} do documento de teste — role, gire em 3D, feche no tap"
        for i in range(1, 301))
    leia = (
        "Pasta de teste do ARIS\n"
        "======================\n\n"
        "1. Diga 'abre pasta documentos' (ou toque no botao da pasta).\n"
        "2. Toque no card 'ARIS Testes' para entrar.\n"
        "3. Em 'modelos': capacete.obj, armadura.obj, personagem.obj.\n"
        "   Tap num card de modelo abre a aba 3D; 2 maos giram e dao zoom.\n"
        "4. Em 'textos' e na raiz: .txt/.md abrem na aba de leitura\n"
        "   (2 maos giram a pagina em 3D, arrastar rola, tap fecha).\n"
        "5. .glb nao e suportado pelo visualizador (mensagem no chat).\n")
    notas = (
        "Notas de teste\n"
        "==============\n\n"
        "- Tap rapido em card = abrir.\n"
        "- Segurar parado e soltar = tambem tap (nao vira 'place').\n"
        "- Mao perdida no quadro = soltura na ultima posicao.\n"
        "- 2 maos na aba: giro, zoom relativo e pan pelo ponto medio.\n"
        "- Soltar apos 2 maos nao fecha a aba.\n")
    guia = (
        "# Guia rapido\n\n"
        "## Gestos\n\n"
        "- **Pinca**: segurar pinca o item mais perto.\n"
        "- **Tap**: soltar curto e perto do inicio.\n"
        "- **Flick**: soltar rapido = lancamento.\n"
        "- **2 maos**: zoom pela distancia; giro pela inclinacao.\n\n"
        "## Aba de documento\n\n"
        "Tap no X (ou tap firme na pagina) fecha.\n")
    return [
        (Path("leia-me.txt"), leia),
        (Path("texto-longo.txt"), longo),
        (Path("textos") / "notas.txt", notas),
        (Path("textos") / "guia-do-usuario.md", guia),
    ]


# ── Main ────────────────────────────────────────────────────────────────
def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "modelos").mkdir(parents=True)
    (OUT / "textos").mkdir()
    _write_obj(OUT / "modelos" / "capacete.obj", [build_helmet()], "capacete de teste")
    _write_obj(OUT / "modelos" / "armadura.obj", [build_armor()], "armadura de teste")
    _write_obj(OUT / "modelos" / "personagem.obj", [build_character()],
               "personagem de teste")
    for rel, text in build_text_files():
        path = OUT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(f"Pasta criada: {OUT}")
    for p in sorted(OUT.rglob("*")):
        print("  ", p.relative_to(OUT))


if __name__ == "__main__":
    main()

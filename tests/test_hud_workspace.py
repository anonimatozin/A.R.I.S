"""Workspace ARQUIVOS + motor 2-mãos (sem pygame, lógica pura)."""

import math
from pathlib import Path

import pytest

from core.vision.hud.workspace import (
    HandPinch,
    WorkspaceManager,
    map_landmark,
    match_folder_command,
    pinch_angle_delta,
    pinch_scale,
    safe_join,
)


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("a")
    (tmp_path / "docs" / "sub").mkdir()
    (tmp_path / "fotos").mkdir()
    return tmp_path


def test_match_folder_command_pt():
    assert match_folder_command("aris abre pasta docs na camera") == "docs"
    assert match_folder_command("abrir pasta fotos") == "fotos"
    assert match_folder_command("mostra a pasta docs na tela") == "docs"
    assert match_folder_command("abre a lixeira") == "lixeira"
    assert match_folder_command("abre documentos") == "documentos"
    assert match_folder_command("qual a hora?") is None
    # relativo com traversal casa mas a resolução bloqueia (ver abaixo)
    assert match_folder_command("abre pasta ../segredo") == "../segredo"


def test_resolve_known_and_absolute_and_missing(root, tmp_path):
    from core.vision.hud.workspace import resolve_folder
    home_docs = Path.home() / "Documents"
    if home_docs.is_dir():
        path, label, mode = resolve_folder("documentos", root)
        assert mode == "dir" and path == home_docs
    path, _, mode = resolve_folder(str(tmp_path), root)
    assert mode == "dir" and path == tmp_path
    path, _, mode = resolve_folder("pasta que nao existe xyz", root)
    assert mode == "missing" and path is None
    # traversal relativo continua bloqueado
    assert resolve_folder("../segredo", root)[2] == "missing"
    from core.vision.hud.workspace import safe_join
    assert safe_join(root, "..") is None


def test_open_any_folder_and_recycle(root, tmp_path, monkeypatch):
    from core.vision.hud import workspace as wsmod
    ws = WorkspaceManager(root)
    items = ws.open_folder(str(tmp_path))
    assert ws.current == tmp_path.name
    assert len(items) >= 1
    # lixeira sem winshell -> modo recycle (cartão Explorer)
    monkeypatch.setattr(wsmod, "list_recycle_bin", lambda: None)
    items = ws.open_folder("lixeira")
    assert ws.current == "Lixeira" and len(items) == 1
    # lixeira com winshell -> lista arquivos
    monkeypatch.setattr(wsmod, "list_recycle_bin", lambda: ["nota.txt"])
    items = ws.open_folder("a lixeira")
    assert ws.current == "Lixeira" and items[0].name == "🗑 nota.txt"


def test_safe_join_blocks_traversal(root):
    assert safe_join(root, "docs") is not None
    assert safe_join(root, "..") is None
    assert safe_join(root, "a/b") is None
    assert safe_join(root, "inexistente") is None


def test_open_folder_lists_items(root):
    ws = WorkspaceManager(root)
    items = ws.open_folder("docs")
    assert len(items) == 2
    assert items[0].kind == "folder"  # sub antes de a.txt
    assert ws.current == "docs"


def test_tap_navigates_into_folder_and_back(root):
    ws = WorkspaceManager(root)
    ws.open_folder("docs")
    sub = next(i for i in ws.items if i.name == "sub")
    got = ws.tap(sub.x, sub.y, 1.0)
    # Tap em pasta ENTRA nela: sub-itens viram cards + card VOLTAR
    assert got is not None
    assert ws.current == "sub"
    assert any(i.kind == "back" for i in ws.items)
    back = next(i for i in ws.items if i.kind == "back")
    # VOLTAR não é arrastável (é controle, não conteúdo)
    assert ws.grab_at(back.x, back.y) is None
    ws.tap(back.x, back.y, 2.0)
    assert ws.current == "docs"
    assert [i.name for i in ws.items] == ["sub", "a.txt"]


def test_card_hit_is_rectangular_not_circular(root):
    from core.vision.hud.workspace import card_hit
    ws = WorkspaceManager(root)
    ws.open_folder("docs")
    it = ws.items[0]
    # Canto do card (100,0) fica fora do raio antigo de 90 mas dentro do card
    assert card_hit(it, it.x + 100, it.y) is True
    assert math.hypot(100, 0) > 90
    # Centro-vertical 80px ficava dentro do raio antigo, mas é fora do card
    assert card_hit(it, it.x, it.y + 80) is False
    assert math.hypot(0, 80) < 90
    # Tap cai no card mesmo assim (era o bug: pasta não abria)
    assert ws.tap(it.x + 100, it.y, 1.0) is not None


def test_dismiss_removes_only_the_view(root):
    ws = WorkspaceManager(root)
    ws.open_folder("docs")
    victim = ws.items[0]
    assert ws.dismiss(victim) is True
    assert victim not in ws.items
    assert ws.dismiss(victim) is False  # já fora da vista
    assert (root / "docs" / "sub").is_dir()  # disco intocado


def test_step_throws_and_removes_card_that_leaves_screen(root):
    ws = WorkspaceManager(root)
    ws.open_folder("docs")
    it = ws.items[0]
    it.x, it.y, it.vx, it.vy = 640.0, 400.0, 4000.0, 0.0
    # Voando: anda e permanece visível
    for _ in range(6):
        removed = ws.step(0.03, 1280, 800, None)
    assert it in ws.items and removed == []
    assert it.x > 640.0 and it.vx > 0.0
    # Cruzou a borda direita inteiro -> some da tela (arquivo intacto)
    it.x = 1400.0
    removed = ws.step(0.03, 1280, 800, None)
    assert it not in ws.items and removed == [it]
    assert (root / "docs" / "sub").is_dir()
    # Card segurado pela mão nunca é removido no meio do arrasto
    held = ws.items[0]
    held.x, held.y = 2000.0, 400.0
    assert ws.step(0.03, 1280, 800, held) == []
    assert held in ws.items


def test_clear_wipes_cards_and_stack(root):
    ws = WorkspaceManager(root)
    ws.open_folder("docs")
    ws.enter(next(i for i in ws.items if i.name == "sub"))
    assert ws._stack
    ws.clear()
    assert ws.items == [] and ws.current is None and ws._stack == []


def test_fist_curl_open_vs_fist_vs_pinch():
    from core.vision.hud.workspace import FIST_CURL_ENTER, fist_curl
    # Landmark sintético de 21 pontos (pulso 0, MCPs 5/17, pontas 4/8/12/16/20)
    hand = [
        (0.50, 1.00),  # 0 pulso
        (0.40, 0.92), (0.33, 0.85), (0.25, 0.74), (0.18, 0.62),  # 1-4 polegar
        (0.44, 0.55), (0.45, 0.42), (0.46, 0.29), (0.46, 0.18),  # 5-8 indicador
        (0.52, 0.54), (0.52, 0.40), (0.52, 0.32), (0.52, 0.24),  # 9-12 médio
        (0.60, 0.56), (0.61, 0.43), (0.61, 0.35), (0.61, 0.28),  # 13-16 anelar
        (0.67, 0.60), (0.69, 0.49), (0.70, 0.42), (0.70, 0.36),  # 17-20 mindinho
    ]
    # Mão aberta: pontas longe do pulso
    assert fist_curl(hand) < 0.2
    # Punho: todas as pontas coladas no palmo
    fist = list(hand)
    fist[8], fist[12], fist[16], fist[20] = ((0.46, 0.60), (0.52, 0.60),
                                             (0.61, 0.60), (0.70, 0.62))
    assert fist_curl(fist) >= FIST_CURL_ENTER
    # Pinça (só polegar+indicador juntos, dedos esticados) NÃO é punho
    pinch = list(hand)
    pinch[4], pinch[8] = (0.41, 0.44), (0.43, 0.45)
    assert fist_curl(pinch) < FIST_CURL_ENTER


def test_zoom_factor_is_relative_and_safe():
    from core.vision.hud.workspace import zoom_factor
    assert zoom_factor(200.0, 400.0) == pytest.approx(2.0)
    assert zoom_factor(400.0, 200.0) == pytest.approx(0.5)
    assert zoom_factor(200.0, 201.0) > 1.0
    assert zoom_factor(0.0, 100.0) == 1.0  # primeira amostra: sem salto


def test_open_default_prefers_docs(root):
    ws = WorkspaceManager(root)
    assert [i.name for i in ws.open_default()] == [i.name for i in ws.open_folder("docs")]
    assert ws.current == "docs"


def test_grid_and_claw(root):
    ws = WorkspaceManager(root)
    ws.open_folder("docs")
    ws.items[0].x, ws.items[0].y = 9999, 9999
    ws.grid()
    assert ws.items[0].x < 2000
    pulled = ws.claw_pull(0, 0)
    assert pulled is not None
    assert (pulled.x, pulled.y) == (0, 0)


def test_pinch_hysteresis():
    p = HandPinch()
    assert p.update(0.10, 0, 0, 0.0) is False
    assert p.update(0.04, 0, 0, 0.1) is True   # entra < 0.05
    assert p.update(0.06, 0, 0, 0.2) is True   # segura até 0.07
    assert p.update(0.08, 0, 0, 0.3) is False  # solta > 0.07
    assert p.is_tap(0.3) is True
    assert p.is_tap(1.0) is False


def test_map_landmark_single_mirror():
    # Mão na direita do sensor (ix=0.8) com espelho -> direita da tela
    sx, _ = map_landmark(0.8, 0.5, True, 1280, 800)
    assert sx == pytest.approx(256)
    # Sem espelho -> segue o sensor
    sx, _ = map_landmark(0.8, 0.5, False, 1280, 800)
    assert sx == pytest.approx(1024)
    # Clamp nas bordas
    assert map_landmark(1.5, -0.5, True, 1280, 800) == (0.0, 0.0)


def test_pinch_scale_and_angle():
    assert pinch_scale(0.0, 0.5) == 0.0
    assert pinch_scale(0.2, 0.3) > 0
    assert pinch_scale(0.3, 0.2) < 0
    assert abs(pinch_angle_delta(3.0, -3.0)) < 0.5  # wrap-around
    assert pinch_angle_delta(0.0, math.pi / 2) == pytest.approx(math.pi / 2)

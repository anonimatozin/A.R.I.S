"""Wizard Pygame do ARIS Gesture Trainer (identidade ARIS: ciano/escuro).

Fluxo: HOME -> AJUSTE -> MÃO -> TREINO (dir -> esq -> 2 mãos) ->
VALIDAÇÃO -> GERENCIAR -> CONCLUÍDO. Mouse + teclado.
"""

import math
import time

import cv2
import numpy as np
import pygame

from . import training as T
from .api import emit
from .calibration import PositionCheck
from .config import (BOTH_HANDS_GESTURES, COOLDOWN_S, DATA_DIR,
                     DEFAULT_GESTURES, MIN_CONFIDENCE, MIN_SAMPLES,
                     TARGET_SAMPLES, VARIATION_PROMPTS)
from .dataset import Dataset
from .features import normalize, wrist_track
from .gestures import add_gesture, delete_gesture, registry, rename_gesture
from .models import load as load_model
from .models import save as save_model
from .recognition import Recognizer

W, H = 1100, 700
BG = (6, 8, 15)
CYAN = (0, 212, 255)
GREEN = (34, 211, 167)
AMBER = (245, 158, 11)
RED = (239, 68, 68)
WHITE = (232, 237, 245)
GRAY = (136, 150, 170)

_FONTS = {}


def font(size, bold=False):
    k = (size, bold)
    if k not in _FONTS:
        try:
            _FONTS[k] = pygame.font.SysFont("Consolas", size, bold=bold)
        except Exception:
            _FONTS[k] = pygame.font.Font(None, size)
    return _FONTS[k]


class Button:
    def __init__(self, rect, label, action):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.action = action

    def draw(self, surf):
        pygame.draw.rect(surf, (6, 12, 22), self.rect, border_radius=8)
        pygame.draw.rect(surf, CYAN, self.rect, 2, border_radius=8)
        t = font(16, True).render(self.label, True, CYAN)
        surf.blit(t, t.get_rect(center=self.rect.center))

    def hit(self, pos):
        return self.rect.collidepoint(pos)


class Wizard:
    def __init__(self, camera, tracker, dataset, event_bus=None):
        pygame.init()
        pygame.display.set_caption("ARIS Gesture Trainer")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.cam = camera
        self.tracker = tracker
        self.ds = dataset
        self.bus = event_bus
        self.screen_name = "home"
        self.buttons = []
        self.msg = ""
        self.check = PositionCheck()
        self.checks = {}
        self.hand_target = "right"
        self.train_queue = []
        self.train_idx = 0
        self.rep = 0
        self.track = []
        self.model = {}
        self.recognizer = None
        self.val_queue = []
        self.val_idx = 0
        self.val_score = {}
        self.val_conf = {}
        self.manage_sel = 0
        self.typing = None
        self.type_buf = ""
        self.min_conf = MIN_CONFIDENCE
        self.running = True
        self.frame = None
        self.lms = []

    # ── helpers ──
    def title(self, text, sub=""):
        t = font(30, True).render(text, True, CYAN)
        self.screen.blit(t, (40, 24))
        if sub:
            s = font(15).render(sub, True, GRAY)
            self.screen.blit(s, (40, 62))

    def cam_view(self, x=40, y=110, w=560, h=420):
        if self.frame is not None:
            surf = pygame.image.frombuffer(
                self.frame.tobytes(), (self.frame.shape[1], self.frame.shape[0]), "RGB")
            surf = pygame.transform.scale(surf, (w, h)).convert()
            self.screen.blit(surf, (x, y))
        pygame.draw.rect(self.screen, CYAN, (x, y, w, h), 2)
        return (x, y, w, h)

    def stat(self, x, y, label, value, color=WHITE):
        self.screen.blit(font(13).render(label, True, GRAY), (x, y))
        self.screen.blit(font(18, True).render(str(value), True, color), (x, y + 18))

    def progress(self, x, y, w, frac, label=""):
        pygame.draw.rect(self.screen, (20, 28, 40), (x, y, w, 22), border_radius=6)
        pygame.draw.rect(self.screen, CYAN, (x, y, int(w * max(0.0, min(1.0, frac))), 22), border_radius=6)
        if label:
            self.screen.blit(font(13).render(label, True, WHITE), (x, y + 26))

    # ── telas ──
    def show_home(self):
        self.title("ARIS GESTURE TRAINER", "Vamos configurar seus gestos.")
        res = self.cam.resolution
        self.stat(40, 120, "CÂMERA", "OK" if self.cam.cap else "FALHOU", GREEN if self.cam.cap else RED)
        self.stat(220, 120, "RESOLUÇÃO", f"{res[0]}x{res[1]}")
        self.stat(420, 120, "FPS", f"{self.cam.fps:.0f}")
        self.stat(560, 120, "MÃOS", str(len(self.lms)))
        self.buttons = [Button((40, 220, 320, 56), "[ INICIAR CONFIGURAÇÃO ]", "adjust")]

    def show_adjust(self):
        self.title("AJUSTE SUA POSIÇÃO", "Coloque sua mão dentro da área indicada.")
        cx, cy, cw, ch = self.cam_view()
        pygame.draw.ellipse(self.screen, GREEN, (cx + cw // 2 - 130, cy + ch // 2 - 160, 260, 320), 2)
        y = 120
        for label, ok in self.checks.items():
            c = GREEN if ok else GRAY
            mark = "✓" if ok else "·"
            self.screen.blit(font(16).render(f"{mark} {label}", True, c), (660, y))
            y += 30
        if self.checks and all(self.checks.values()):
            self.screen.blit(font(16, True).render("Posição configurada.", True, GREEN), (660, y + 10))
            self.buttons = [Button((660, y + 44, 220, 48), "[ CONTINUAR ]", "hand")]
        else:
            self.buttons = []

    def show_hand(self):
        side = "DIREITA" if self.hand_target == "right" else "ESQUERDA"
        self.title(f"CONFIGURAÇÃO DA MÃO {side}", "Levante somente sua mão correspondente.")
        self.cam_view()
        found = [s for _, s, _ in self.lms]
        if self.hand_target in found:
            self.screen.blit(font(18, True).render(f"Mão {side.lower()} identificada.", True, GREEN), (660, 140))
            self.buttons = [Button((660, 190, 320, 48), "[ APRENDER GESTOS ]", "train")]
        else:
            self.buttons = []

    def show_train(self):
        if self.train_idx >= len(self.train_queue):
            self._finish_hand()
            return
        hand, gid, label, dyn = self.train_queue[self.train_idx]
        got = self.ds.count(hand, gid)
        frac = min(1.0, got / TARGET_SAMPLES)
        self.title(f"GESTO: {label}", f"Faça o gesto com a mão {hand}.")
        self.cam_view()
        prompt = VARIATION_PROMPTS[(got // max(1, TARGET_SAMPLES // 7)) % len(VARIATION_PROMPTS)]
        self.screen.blit(font(15).render(prompt, True, AMBER), (660, 130))
        self.progress(660, 170, 380, frac, f"Exemplos: {got}/{TARGET_SAMPLES}")
        q, why = self.ds.quality(hand, gid)
        self.screen.blit(font(15).render(f"Qualidade: {q} — {why}", True, GREEN if q == "BOA" else AMBER), (660, 220))
        side = "DIREITA" if hand == "right" else ("ESQUERDA" if hand == "left" else "2 MÃOS")
        self.stat(660, 260, "MÃO", side, CYAN)
        self.stat(800, 260, "FPS", f"{self.cam.fps:.0f}")
        self.buttons = [Button((660, 330, 220, 44), "[ PULAR ]", "skip")]

    def show_validate(self):
        self.title("TESTE SEUS GESTOS", "Execute o gesto esperado livremente.")
        self.cam_view()
        if self.val_idx >= len(self.val_queue):
            self._report()
            return
        hand, gid, label, dyn = self.val_queue[self.val_idx]
        self.screen.blit(font(20, True).render(f"ESPERADO: {label}", True, AMBER), (660, 130))
        g, conf = self.recognizer.last if self.recognizer else (None, 0.0)
        self.screen.blit(font(18).render(f"DETECTADO: {(g or '—').upper()}", True, CYAN), (660, 170))
        self.screen.blit(font(18).render(f"CONFIANÇA: {conf:.0%}", True, WHITE), (660, 200))
        tot = sum(self.val_score.values())
        ok = sum(1 for k, v in self.val_score.items() if k == v)
        self.screen.blit(font(15).render(f"Acertos: {ok}/{tot}", True, GRAY), (660, 240))
        self.buttons = [Button((660, 290, 220, 44), "[ PRÓXIMO ]", "vnext")]

    def show_manage(self):
        self.title("MEUS GESTOS", "A:Add R:Renomear D:Excluir T:Re-treinar E:Exportar I:Importar X:Zerar")
        y = 110
        rows = []
        for hand in ("right", "left", "both"):
            for gid, label, dyn, n in registry(self.ds).get(hand, []):
                rows.append((hand, gid, label, n))
        self._manage_rows = rows[:16]
        for i, (hand, gid, label, n) in enumerate(self._manage_rows):
            c = CYAN if i == self.manage_sel else GRAY
            self.screen.blit(font(15).render(f"{hand:>5}  {label:<28} {n:>4} ex.", True, c), (60, y))
            y += 26
        if self.typing:
            self.screen.blit(font(15).render(f"{self.typing}: {self.type_buf}_", True, AMBER), (60, y + 10))
        self.buttons = [Button((60, H - 80, 260, 48), "[ CONCLUIR ]", "done")]

    def show_done(self):
        self.title("Configuração concluída.", "Modelo salvo. A ARIS já pode usar seus gestos.")
        self.buttons = [Button((40, 160, 220, 48), "[ SAIR ]", "quit")]

    # ── fluxo ──
    def _build_queue(self, hand):
        table = DEFAULT_GESTURES if hand in ("right", "left") else BOTH_HANDS_GESTURES
        return [(hand, gid, label, dyn) for gid, label, dyn in table]

    def _finish_hand(self):
        self._train_models()
        if self.hand_target == "right":
            self.hand_target = "left"
            self.screen_name = "hand"
        elif self.hand_target == "left":
            self.hand_target = "both"
            self.screen_name = "hand"
        else:
            self.val_queue = []
            for hand in ("right", "left", "both"):
                for gid, label, dyn, n in registry(self.ds).get(hand, []):
                    if n >= 5:
                        self.val_queue.append((hand, gid, label, dyn))
            self.val_idx = 0
            self.val_score = {}
            self.screen_name = "validate"

    def _train_models(self):
        static, dynamic = {}, {}
        for hand in ("right", "left", "both"):
            for gid, label, dyn, n in registry(self.ds).get(hand, []):
                xs = self.ds.load(hand, gid)
                if len(xs) < 5:
                    continue
                key = f"{hand}:{gid}"
                if dyn:
                    dynamic.update(T.train_dynamic({key: xs}))
                else:
                    static.update(T.train_static({key: xs}))
        self.model = {**static, **dynamic}
        save_model(DATA_DIR / "models" / "aris_gestures.model", static, dynamic,
                   {"hands": ["right", "left", "both"]})
        self.ds.save_meta({"trained_at": time.time(), "gestures": len(self.model)})
        self.recognizer = Recognizer(self.model)

    def _report(self):
        tot = len(self.val_score)
        ok = sum(1 for k, v in self.val_score.items() if k == v)
        self.msg = f"Acurácia: {ok}/{tot}"
        self.screen_name = "manage"

    # ── coleta ──
    def _collect(self):
        if self.screen_name != "train" or self.train_idx >= len(self.train_queue):
            return
        hand, gid, label, dyn = self.train_queue[self.train_idx]
        for pts, side, conf in self.lms:
            if side != hand and not (hand == "both"):
                continue
            if conf < 0.5:
                continue
            if dyn:
                self.track.append((pts[0][0], pts[0][1], time.time()))
                if len(self.track) >= 24:
                    var = VARIATION_PROMPTS[(self.ds.count(hand, gid) // 40) % len(VARIATION_PROMPTS)]
                    self.ds.add_dynamic(hand, gid, list(self.track), var)
                    self.track = []
            else:
                var = VARIATION_PROMPTS[(self.ds.count(hand, gid) // max(1, TARGET_SAMPLES // 7)) % len(VARIATION_PROMPTS)]
                self.ds.add_static(hand, gid, pts, var)
        if self.ds.count(hand, gid) >= TARGET_SAMPLES:
            self.train_idx += 1
            self.track = []

    def _validate_live(self):
        if self.screen_name != "validate" or not self.recognizer:
            return
        if self.val_idx >= len(self.val_queue):
            return
        hand, gid, label, dyn = self.val_queue[self.val_idx]
        for pts, side, conf in self.lms:
            if side != hand and hand != "both":
                continue
            from .features import normalize, wrist_track
            if dyn:
                self.track.append((pts[0][0], pts[0][1], time.time()))
                if len(self.track) >= 24:
                    g, c = self.recognizer.predict_dynamic(wrist_track(self.track))
                    self.track = []
                    if g:
                        emit(g, side, c, event_bus=self.bus)
            else:
                g, c = self.recognizer.predict_static(normalize(pts))
                if g:
                    emit(g, side, c, event_bus=self.bus)

    # ── loop ──
    def handle(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for b in self.buttons:
                if b.hit(ev.pos):
                    self._action(b.action)
        elif ev.type == pygame.KEYDOWN:
            if self.typing:
                if ev.key == pygame.K_RETURN:
                    self._typing_done()
                elif ev.key == pygame.K_BACKSPACE:
                    self.type_buf = self.type_buf[:-1]
                elif ev.key == pygame.K_ESCAPE:
                    self.typing = None
                else:
                    self.type_buf += ev.unicode
                return
            if self.screen_name == "manage":
                rows = getattr(self, "_manage_rows", [])
                if ev.key == pygame.K_UP:
                    self.manage_sel = max(0, self.manage_sel - 1)
                elif ev.key == pygame.K_DOWN:
                    self.manage_sel = min(len(rows) - 1, self.manage_sel + 1)
                elif rows:
                    hand, gid, _, _ = rows[self.manage_sel]
                    k = ev.unicode.lower()
                    if k == "d":
                        from .gestures import delete_gesture
                        delete_gesture(self.ds, hand, gid)
                    elif k == "t":
                        from .gestures import retrain_gesture
                        retrain_gesture(self.ds, hand, gid)
                    elif k in ("a", "r", "e", "i", "x"):
                        self.typing, self.type_buf = k, ""

    def _typing_done(self):
        from . import gestures as G
        rows = getattr(self, "_manage_rows", [])
        k, buf = self.typing, self.type_buf.strip()
        self.typing = None
        if k == "a" and buf:
            add_gesture(self.ds, "right", buf)
        elif rows and k == "r" and buf:
            hand, gid, _, _ = rows[self.manage_sel]
            rename_gesture(self.ds, hand, gid, buf)
        elif k == "e" and buf:
            G.export_model(DATA_DIR / "models" / "aris_gestures.model", __import__("pathlib").Path(buf))
        elif k == "i" and buf:
            G.import_model(__import__("pathlib").Path(buf), DATA_DIR / "models" / "aris_gestures.model")
        elif k == "x":
            import shutil
            shutil.rmtree(DATA_DIR, ignore_errors=True)
            DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _action(self, name):
        if name == "adjust":
            self.screen_name = "adjust"
        elif name == "hand":
            self.screen_name = "hand"
        elif name == "train":
            self.train_queue = self._build_queue(self.hand_target)
            self.train_idx = 0
            self.screen_name = "train"
        elif name == "skip":
            self.train_idx += 1
        elif name == "vnext":
            if self.val_idx < len(self.val_queue):
                hand, gid, label, dyn = self.val_queue[self.val_idx]
                g, _ = self.recognizer.last if self.recognizer else (None, 0)
                self.val_score[f"{hand}:{gid}@{self.val_idx}"] = (f"{hand}:{gid}" if not dyn else (g or ""))
                self.val_idx += 1
        elif name == "done":
            self.screen_name = "done"
        elif name == "quit":
            self.running = False

    def frame_step(self):
        ok, frame = self.cam.read()
        if not ok or frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.lms = self.tracker.process(rgb)
        for pts, side, conf in self.lms:
            self.tracker.draw(frame, pts)
        self.frame = np.ascontiguousarray(rgb)
        bright = float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())
        if self.lms:
            pts, side, conf = self.lms[0]
            self.checks = self.check.check(pts, conf, bright)
        # handedness no canto
        y = 560
        for _, side, conf in self.lms:
            t = font(14).render(f"{side} {conf:.0%}", True, CYAN)
            self.screen.blit(t, (660, y))
            y += 22

    def run(self):
        while self.running:
            dt = self.clock.tick(30) / 1000.0
            for ev in pygame.event.get():
                self.handle(ev)
            self.frame_step()
            self.screen.fill(BG)
            self.buttons = []
            {"home": self.show_home, "adjust": self.show_adjust,
             "hand": self.show_hand, "train": self.show_train,
             "validate": self.show_validate, "manage": self.show_manage,
             "done": self.show_done}[self.screen_name]()
            if self.screen_name == "train":
                self._collect()
            if self.screen_name == "validate":
                self._validate_live()
            for b in self.buttons:
                b.draw(self.screen)
            pygame.display.flip()
        pygame.quit()

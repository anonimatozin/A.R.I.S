"""A.R.I.S. HUD — Pygame Native Interface.

HUD nativo com Pygame + MediaPipe hand tracking.
Estilo Jarvis: hologramas, particulas, scan lines, webcam ao fundo,
controle por duas maos (pinch pra arrastar, duas maos pra escalar).

Sem comandos por gesto — apenas controle direto dos elementos na tela.
"""

import json
import math
import random
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
import pygame

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import mediapipe as mp_lib
    mp_vision = mp_lib.tasks.vision
    _MEDIAPIPE = True
except (ImportError, AttributeError):
    _MEDIAPIPE = False

# ── Constants ────────────────────────────────────────────────
WIDTH, HEIGHT = 1280, 800
FPS = 60

# Limiares do HandLandmarker (luz baixa: 0.5/0.5; presenca acompanha
# deteccao p/ nao matar a mao quando o dedo sai de quadro)
HAND_DETECTION_CONFIDENCE = 0.5
HAND_PRESENCE_CONFIDENCE = 0.5
HAND_TRACKING_CONFIDENCE = 0.5

# Conexoes do esqueleto MediaPipe (21 pontos, 21 arestas)
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)
# Pontos "chave" desenhados maior (ponta do indicador/polegar + pulso)
HAND_KEY_POINTS = (0, 4, 8, 12, 16, 20)

# 2 mãos: deadband + teto por quadro (jitter de 1px não pode dar zoom/giro)
TWO_HAND_GRACE = 0.10   # s de pausa depois que as 2 mãos pinçam
TWO_HAND_EMA = 0.3      # suaviza a distância/ângulo antes do passo
ZOOM_DEADBAND = 0.006   # passo relativo mínimo (0.6% da distância)
ZOOM_MAX_STEP = 0.05    # teto de escala relativa por quadro
ROT_DEADBAND = 0.02     # rad por quadro (~1.1°)
ROT_MAX_STEP = 0.12     # rad por quadro

# Reset do HUD: 2 punhos fechados segurados por 1s
FIST_CURL = 0.65
FIST_HOLD_S = 1.0
RESET_COOLDOWN_S = 2.0

# Arremesso (flick): card voa com física e some SÓ ao sair da tela
THROW_POWER = 0.45

# Colors — paleta Jarvis: ciano elétrico + dourado de alerta
BG_COLOR = (4, 7, 14)
CYAN = (0, 226, 255)
CYAN_DIM = (0, 96, 136)
CYAN_GLOW = (94, 240, 255)
GREEN = (57, 255, 176)
GREEN_DIM = (20, 118, 92)
AMBER = (255, 196, 61)
RED = (255, 96, 96)
WHITE = (236, 244, 255)
GRAY = (126, 146, 172)
DARK_GRAY = (64, 78, 100)
GRID_COLOR = (13, 20, 34)
PURPLE = (168, 85, 247)
PANEL_FILL = (5, 10, 20)

# Cards do workspace: cor + tag por categoria de arquivo
WS_CAT_COLORS = {
    "text": CYAN,
    "image": (255, 110, 170),
    "archive": AMBER,
    "media": (255, 140, 60),
    "doc": (120, 175, 255),
    "exe": GREEN,
    "file": GRAY,
}
WS_CAT_TAGS = {
    "text": "TXT", "image": "IMG", "archive": "ZIP", "media": "MED",
    "doc": "DOC", "exe": "EXE", "file": "ARQ",
}

# Chat panel
CHAT_WIDTH = 360
CHAT_X = WIDTH - CHAT_WIDTH - 10
CHAT_Y = 50
CHAT_HEIGHT = HEIGHT - 60

# ── Data ─────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
METRICS_URL = "http://127.0.0.1:8790/api/hud/metrics"
STATUS_URL = "http://127.0.0.1:8790/api/hud/status"

# Cache de fonts (evita SysFont por frame — gargalo com 2 mãos)
_FONT_CACHE: dict = {}

# Fonte pixel HUD (ao lado deste módulo) com fallback Consolas
_VT323_PATH = Path(__file__).parent / "assets" / "VT323-Regular.ttf"


def _font(name: str, size: int, bold: bool = False):
    key = (name, size, bold)
    f = _FONT_CACHE.get(key)
    if f is None:
        if name.lower() == "vt323" and _VT323_PATH.exists():
            try:
                f = pygame.font.Font(str(_VT323_PATH), size)
            except Exception:
                f = pygame.font.SysFont("Consolas", size, bold=bold)
        else:
            try:
                f = pygame.font.SysFont(name, size, bold=bold)
            except Exception:
                f = pygame.font.Font(None, size)
        _FONT_CACHE[key] = f
    return f


class HandTracker:
    """MediaPipe Hands wrapper for real-time hand tracking."""

    def __init__(self):
        self.hand_landmarker = None
        self.cap = None
        self.running = False
        self.landmarks = []
        self.hand_count = 0
        self.hand_confidence = 0.0
        self.last_frame = None
        self.lock = threading.Lock()
        # Inferência em thread separada: captura nunca bloqueia
        self._infer_src = None
        self._infer_lock = threading.Lock()
        self._frame_warned = False
        # Câmera: espelho (flip) + índice (frontal/traseira) + rotação
        self.mirror = True
        self.camera_index = 0
        self.rotation = 0  # 0/90/180/270

    def start(self, camera_index=0):
        if not _CV2:
            print("HandTracker: cv2 indisponivel — camera desabilitada")
            return False
        try:
            if _MEDIAPIPE:
                model_path = str(DATA_DIR / "hand_landmarker.task")
                if not Path(model_path).exists():
                    self._download_model(model_path)
                if Path(model_path).exists():
                    base_options = mp_lib.tasks.BaseOptions(model_asset_path=model_path)
                    options = mp_vision.HandLandmarkerOptions(
                        base_options=base_options,
                        running_mode=mp_vision.RunningMode.VIDEO,
                        num_hands=2,
                        min_hand_detection_confidence=HAND_DETECTION_CONFIDENCE,
                        min_hand_presence_confidence=HAND_PRESENCE_CONFIDENCE,
                        min_tracking_confidence=HAND_TRACKING_CONFIDENCE,
                    )
                    self.hand_landmarker = mp_vision.HandLandmarker.create_from_options(options)
                    print("HandTracker: HandLandmarker carregado")
            self.cap = cv2.VideoCapture(camera_index)
            if not self.cap.isOpened():
                print(f"HandTracker: camera {camera_index} nao abriu")
                return False
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.running = True
            threading.Thread(target=self._loop, daemon=True).start()
            threading.Thread(target=self._infer_loop, daemon=True).start()
            print(f"HandTracker: camera {camera_index} aberta")
            return True
        except Exception as e:
            print(f"HandTracker start error: {e}")
            return False

    def _download_model(self, path):
        import urllib.request
        url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
        try:
            print("HandTracker: baixando hand_landmarker.task...")
            urllib.request.urlretrieve(url, path)
        except Exception as e:
            print(f"HandTracker: falha ao baixar modelo: {e}")

    def _loop(self):
        # Captura pura: nunca bloqueia na inferência
        while self.running and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            # Inferência SEM espelho: map_landmark() aplica o flip UMA vez só,
            # igual ao display. O frame exibido é o mesmo quadro da inferência
            # (sem rot90 extra), então o esqueleto cai em cima dos dedos.
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            raw = np.rot90(rgb, k=self.rotation // 90) if self.rotation else rgb
            raw = np.ascontiguousarray(raw)
            display = np.ascontiguousarray(np.fliplr(raw)) if self.mirror else raw

            with self.lock:
                self.last_frame = display
            # Entrega cópia p/ inferência (descarta se ocupada)
            if self.hand_landmarker and self._infer_lock.acquire(blocking=False):
                try:
                    self._infer_src = raw
                finally:
                    self._infer_lock.release()
            time.sleep(0.005)

    def _infer_loop(self):
        # Inferência no último frame disponível (throttle ~15fps)
        frame_idx = 0
        while self.running:
            rgb = None
            if self._infer_lock.acquire(blocking=False):
                try:
                    rgb, self._infer_src = self._infer_src, None
                finally:
                    self._infer_lock.release()
            if rgb is None or not self.hand_landmarker:
                time.sleep(0.03)
                continue
            try:
                mp_image = mp_lib.Image(image_format=mp_lib.ImageFormat.SRGB, data=rgb)
                frame_idx += 1
                result = self.hand_landmarker.detect_for_video(mp_image, frame_idx * 66)
                hands_data = []
                if result.hand_landmarks:
                    for hand_lm in result.hand_landmarks:
                        hands_data.append([(lm.x, lm.y) for lm in hand_lm])
                scores = []
                for cats in (getattr(result, "handedness", None) or []):
                    if cats:
                        scores.append(float(cats[0].score))
                with self.lock:
                    self.landmarks = hands_data
                    self.hand_count = len(hands_data)
                    self.hand_confidence = max(scores) if scores else 0.0
            except Exception as e:
                if not self._frame_warned:
                    print(f"HandTracker inferência: {e}")
                    self._frame_warned = True
            time.sleep(0.03)

    def get_frame(self):
        with self.lock:
            frame = self.last_frame
        if frame is None:
            return None
        try:
            h, w = frame.shape[:2]
            surf = pygame.image.frombuffer(frame.tobytes(), (w, h), 'RGB')
            surf = surf.convert()
            surf = pygame.transform.scale(surf, (WIDTH, HEIGHT))
            return surf
        except Exception as e:
            if not self._frame_warned:
                print(f"HandTracker frame: {e}")
                self._frame_warned = True
            return None

    def get_hands(self):
        with self.lock:
            return [list(h) for h in self.landmarks]

    def get_debug_stats(self) -> tuple[int, float]:
        """(mãos detectadas, confiança máxima da última inferência)."""
        with self.lock:
            return self.hand_count, self.hand_confidence

    def cycle_camera(self) -> int:
        """Troca frontal/traseira (índices 0→1→2→0)."""
        nxt = (self.camera_index + 1) % 3
        cap = None
        try:
            cap = cv2.VideoCapture(nxt)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    try:
                        if self.cap:
                            self.cap.release()
                    except Exception:
                        pass
                    self.cap = cap
                    self.camera_index = nxt
                    print(f"Camera trocada para índice {nxt}")
                    return nxt
            cap.release()
        except Exception:
            try:
                if cap:
                    cap.release()
            except Exception:
                pass
        print(f"Camera {nxt} indisponível — mantida {self.camera_index}")
        return self.camera_index

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()


class Particle:
    """Floating holographic particle."""

    def __init__(self, cx, cy, radius_range=(80, 200)):
        self.cx = cx
        self.cy = cy
        angle = random.uniform(0, 2 * math.pi)
        r = random.uniform(*radius_range)
        self.x = cx + r * math.cos(angle)
        self.y = cy + r * math.sin(angle)
        self.angle = angle
        self.radius = r
        self.speed = random.uniform(0.3, 1.2)
        self.size = random.uniform(1, 3)
        self.color_idx = random.choice([0, 1, 2])

    def update(self, dt, cx, cy):
        self.angle += self.speed * dt
        self.x = cx + self.radius * math.cos(self.angle)
        self.y = cy + self.radius * math.sin(self.angle)

    def draw(self, surface):
        colors = [CYAN, GREEN, PURPLE]
        c = colors[self.color_idx]
        pygame.draw.circle(surface, c, (int(self.x), int(self.y)), int(self.size))


class DataStream:
    """Flowing data lines around the hologram."""

    def __init__(self, cx, cy):
        self.cx = cx
        self.cy = cy
        self.lines = []
        for _ in range(6):
            self._spawn_line()

    def _spawn_line(self):
        angle = random.uniform(0, 2 * math.pi)
        r = random.uniform(110, 180)
        self.lines.append({
            'angle': angle,
            'radius': r,
            'length': random.uniform(20, 60),
            'speed': random.uniform(20, 50),
        })

    def update(self, dt):
        for line in self.lines:
            line['angle'] += line['speed'] * dt * 0.02

    def draw(self, surface):
        for line in self.lines:
            a = line['angle']
            r = line['radius']
            x1 = self.cx + r * math.cos(a)
            y1 = self.cy + r * math.sin(a)
            x2 = self.cx + (r + line['length']) * math.cos(a)
            y2 = self.cy + (r + line['length']) * math.sin(a)
            pygame.draw.line(surface, CYAN_DIM, (int(x1), int(y1)), (int(x2), int(y2)), 1)


class Hologram:
    """Central holographic element with multiple rings and effects."""

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.target_x = self.x
        self.target_y = self.y
        self.scale = 1.0
        self.target_scale = 1.0
        self.rotation = 0.0
        self.glow_intensity = 0.0
        self.ring_angles = [0.0, 0.0, 0.0, 0.0, 0.0]
        self.pulse = 0.0
        self.vx = 0.0  # arremesso (flick): o central nunca sai da tela
        self.vy = 0.0

    def update(self, dt):
        from core.vision.hud.workspace import THROW_DAMP, THROW_STOP
        if self.vx or self.vy:
            self.target_x += self.vx * dt
            self.target_y += self.vy * dt
            damp = math.exp(-THROW_DAMP * dt)
            self.vx *= damp
            self.vy *= damp
            if abs(self.vx) < THROW_STOP and abs(self.vy) < THROW_STOP:
                self.vx = self.vy = 0.0
            self.target_x = max(100.0, min(WIDTH - 100.0, self.target_x))
            self.target_y = max(100.0, min(HEIGHT - 100.0, self.target_y))
        self.x += (self.target_x - self.x) * 5 * dt
        self.y += (self.target_y - self.y) * 5 * dt
        self.scale += (self.target_scale - self.scale) * 5 * dt
        self.rotation += 40 * dt
        self.ring_angles[0] += 60 * dt
        self.ring_angles[1] -= 45 * dt
        self.ring_angles[2] += 30 * dt
        self.ring_angles[3] -= 20 * dt
        self.ring_angles[4] += 15 * dt
        self.glow_intensity = 0.5 + 0.5 * math.sin(time.time() * 2)
        self.pulse = 0.5 + 0.5 * math.sin(time.time() * 3)

    def draw(self, surface):
        cx, cy = int(self.x), int(self.y)
        s = self.scale

        # Glow radial suave (concentric outline, custo baixo)
        for r in range(int(140 * s), int(106 * s), -6):
            alpha = int(15 * (1 - (r - 106 * s) / (34 * s)))
            if alpha > 0:
                glow_surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                pygame.draw.circle(glow_surf, (*CYAN_DIM, alpha), (r, r), r)
                surface.blit(glow_surf, (cx - r, cy - r))

        # Anel externo: 3 arcos segmentados girando (linguagem de HUD militar)
        self._draw_arc_ring(surface, cx, cy, int(124 * s), CYAN, 2,
                            self.ring_angles[0], 3, 78)
        # Hexágono técnico
        self._draw_hex(surface, cx, cy, int(108 * s), CYAN_DIM, 1,
                       -self.ring_angles[3])
        # Tick ring (instrumento — a cada 5 ticks um maior)
        self._draw_ticks(surface, cx, cy, int(100 * s), self.ring_angles[0])
        # Anel tracejado
        self._draw_dashed_ring(surface, cx, cy, int(84 * s), GREEN_DIM,
                               self.ring_angles[4])
        # Anel interno: 2 arcos girando no sentido contrário
        self._draw_arc_ring(surface, cx, cy, int(68 * s), CYAN_DIM, 1,
                            self.ring_angles[1], 2, 118)
        # Cross hairs curtos
        self._draw_crosshair(surface, cx, cy, int(44 * s), int(58 * s))

        # Core pulsante com halo
        core_r = int((24 + 4 * self.pulse) * s)
        pad = 5
        core = pygame.Surface((core_r * 2 + pad * 2, core_r * 2 + pad * 2),
                              pygame.SRCALPHA)
        pygame.draw.circle(core, (*CYAN_GLOW, int(46 + 34 * self.pulse)),
                           (core_r + pad, core_r + pad), core_r + pad)
        pygame.draw.circle(core, (*CYAN, 235), (core_r + pad, core_r + pad),
                           core_r, 2)
        surface.blit(core, (cx - core_r - pad, cy - core_r - pad))

        # ARIS text (fonte pixel do HUD)
        font = _font("vt323", max(15, int(17 * s)))
        txt = font.render("A.R.I.S.", True, CYAN)
        txt_rect = txt.get_rect(center=(cx, cy + int(80 * s)))
        surface.blit(txt, txt_rect)

        # Corner brackets
        self._draw_corners(surface, cx, cy, int(134 * s))

    def _draw_arc_ring(self, surface, cx, cy, radius, color, width,
                       angle_offset, spans, span_deg):
        """Arcos segmentados girando (anel 'aberto' de HUD)."""
        rect = pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2)
        step = 360.0 / max(1, spans)
        for i in range(spans):
            start = math.radians(angle_offset + i * step)
            end = math.radians(angle_offset + i * step + span_deg)
            pygame.draw.arc(surface, color, rect, start, end, width)

    def _draw_dashed_ring(self, surface, cx, cy, radius, color, angle_offset):
        for i in range(0, 360, 15):
            a1 = math.radians(angle_offset + i)
            a2 = math.radians(angle_offset + i + 8)
            x1 = cx + int(radius * math.cos(a1))
            y1 = cy + int(radius * math.sin(a1))
            x2 = cx + int(radius * math.cos(a2))
            y2 = cy + int(radius * math.sin(a2))
            pygame.draw.line(surface, color, (x1, y1), (x2, y2), 1)

    def _draw_hex(self, surface, cx, cy, radius, color, width, angle_offset):
        points = []
        for i in range(6):
            a = math.radians(angle_offset + i * 60)
            x = cx + int(radius * math.cos(a))
            y = cy + int(radius * math.sin(a))
            points.append((x, y))
        points.append(points[0])
        pygame.draw.lines(surface, color, False, points, width)

    def _draw_crosshair(self, surface, cx, cy, inner_r, outer_r):
        for angle in [0, 90, 180, 270]:
            a = math.radians(angle)
            x1 = cx + int(inner_r * math.cos(a))
            y1 = cy + int(inner_r * math.sin(a))
            x2 = cx + int(outer_r * math.cos(a))
            y2 = cy + int(outer_r * math.sin(a))
            pygame.draw.line(surface, CYAN_DIM, (x1, y1), (x2, y2), 1)

    def _draw_corners(self, surface, cx, cy, size):
        corner_len = 20
        corners = [
            (cx - size, cy - size, 1, 1),
            (cx + size, cy - size, -1, 1),
            (cx - size, cy + size, 1, -1),
            (cx + size, cy + size, -1, -1),
        ]
        for x, y, dx, dy in corners:
            pygame.draw.line(surface, CYAN, (x, y), (x + corner_len * dx, y), 2)
            pygame.draw.line(surface, CYAN, (x, y), (x, y + corner_len * dy), 2)

    def _draw_ticks(self, surface, cx, cy, radius, angle_offset):
        for i in range(60):
            a = math.radians(angle_offset + i * 6)
            inner = radius - (8 if i % 5 == 0 else 4)
            x1 = cx + int(inner * math.cos(a))
            y1 = cy + int(inner * math.sin(a))
            x2 = cx + int(radius * math.cos(a))
            y2 = cy + int(radius * math.sin(a))
            color = CYAN if i % 5 == 0 else CYAN_DIM
            pygame.draw.line(surface, color, (x1, y1), (x2, y2), 1)


class Orb:
    """Floating metric orb."""

    def __init__(self, x, y, label, value=""):
        self.x = float(x)
        self.y = float(y)
        self.target_x = self.x
        self.target_y = self.y
        self.label = label
        self.value = value
        self.grabbed = False

    def update(self, dt):
        self.x += (self.target_x - self.x) * 8 * dt
        self.y += (self.target_y - self.y) * 8 * dt

    def draw(self, surface):
        cx, cy = int(self.x), int(self.y)
        r = 32 if not self.grabbed else 36
        color = GREEN if self.grabbed else CYAN

        # % do valor (CPU/RAM) → anel de progresso; >=85% vira alerta
        pct = None
        val = self.value.strip()
        if val.endswith("%"):
            try:
                pct = max(0.0, min(100.0, float(val[:-1])))
            except ValueError:
                pct = None
        if pct is not None and pct >= 85.0:
            color = RED

        # Vidro: disco translúcido + anel brilhante
        glass = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glass, (*PANEL_FILL, 178), (r, r), r)
        pygame.draw.circle(glass, (*color, 225), (r, r), r, 2)
        pygame.draw.circle(glass, (*color, 75), (r, r), r - 6, 1)
        if pct is not None:
            arc = pygame.Rect(0, 0, r * 2 - 9, r * 2 - 9)
            arc.center = (r, r)
            start = -math.pi / 2
            end = start + (pct / 100.0) * math.pi * 2
            pygame.draw.arc(glass, (*color, 255), arc, start, end, 3)
        surface.blit(glass, (cx - r, cy - r))

        # Value + label (fonte pixel do HUD)
        font = _font("vt323", 17)
        font_sm = _font("vt323", 12)
        val_txt = font.render(self.value, True, WHITE)
        surface.blit(val_txt, val_txt.get_rect(center=(cx, cy - 1)))
        lbl_txt = font_sm.render(self.label, True, color)
        surface.blit(lbl_txt, lbl_txt.get_rect(center=(cx, cy + r + 11)))

    def contains(self, px, py):
        return math.hypot(px - self.x, py - self.y) < 40


class ScanLine:
    """Horizontal scan line that sweeps across the screen."""

    def __init__(self):
        self.y = 0
        self.speed = 150

    def update(self, dt):
        self.y += self.speed * dt
        if self.y > HEIGHT:
            self.y = -10

    def draw(self, surface):
        # Banda de varredura suave (núcleo + rastros)
        y = int(self.y)
        for dy, alpha in ((-2, 18), (0, 60), (1, 26)):
            band = pygame.Surface((WIDTH, 1), pygame.SRCALPHA)
            band.fill((*CYAN, alpha))
            surface.blit(band, (0, y + dy))


class CornerHUD:
    """Painéis dos cantos (fundos translúcidos + tipografia pixel)."""

    def __init__(self):
        self.time_offset = 0

    @staticmethod
    def _panel(surface, x, y, w, h, title):
        """Painel com header de acento; devolve a y de início do conteúdo."""
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (*PANEL_FILL, 200), (0, 0, w, h),
                         border_radius=8)
        pygame.draw.rect(panel, (*CYAN_DIM, 170), (0, 0, w, h), 1,
                         border_radius=8)
        pygame.draw.rect(panel, (*CYAN, 235), (0, 0, 3, h),
                         border_top_left_radius=8, border_bottom_left_radius=8)
        font_t = _font("vt323", 14)
        pygame.draw.rect(panel, (*CYAN_DIM, 90), (3, 0, w - 3, 20))
        panel.blit(font_t.render(title, True, CYAN), (10, 2))
        surface.blit(panel, (x, y))
        return y + 24

    def draw(self, surface, metrics, fps: int = 60, right_edge: int = WIDTH - 16,
             cam: bool = False):
        font = _font("vt323", 15)
        font_sm = _font("vt323", 13)

        # Top-left: sistema
        cy0 = self._panel(surface, 16, 44, 168, 96, "SISTEMA")
        for i, (text, color) in enumerate([
            (f"CPU  {metrics['cpu']}", WHITE),
            (f"RAM  {metrics['ram']}", WHITE),
            (f"UP   {metrics['uptime']}", WHITE),
        ]):
            surface.blit(font.render(text, True, color), (28, cy0 + i * 20))

        # Top-right: relógio + estado (recuado para não sumir sob o chat)
        ts = time.strftime("%H:%M:%S")
        date_str = time.strftime("%d/%m/%Y")
        rx = max(720, right_edge - 182)
        cy0 = self._panel(surface, rx, 88, 170, 116, "SISTEMA // NO")
        clock_txt = _font("vt323", 30).render(ts, True, CYAN)
        surface.blit(clock_txt, (rx + 12, cy0 - 4))
        for i, (text, color) in enumerate([
            (date_str, GRAY),
            (f"MODO  {metrics['mode']}", GREEN),
            (f"STAT  {metrics['status'][:11]}", WHITE),
        ]):
            surface.blit(font_sm.render(text, True, color), (rx + 12,
                                                              cy0 + 30 + i * 17))

        # Bottom-left: info técnica acima da barra de debug de mãos
        by = HEIGHT - 148
        cy0 = self._panel(surface, 16, by, 168, 92, "TELEMETRIA")
        for i, (text, color) in enumerate([(f"RES   {WIDTH}x{HEIGHT}", WHITE),
                                           (f"FPS   {fps}", WHITE),
                                           ("GATE  :8765  :8790", WHITE),
                                           ("CAM   " + ("LIVE" if cam else "OFF"),
                                            GREEN if cam else RED)]):
            surface.blit(font_sm.render(text, True, color), (28, cy0 + i * 16))


class ChatPanel:
    """Scrollable chat panel receiving messages via SSE from ARIS Event Bus."""

    def __init__(self):
        self.messages = []  # list of (sender, text, timestamp, color)
        self.scroll_offset = 0
        self.max_messages = 100
        self.lock = threading.Lock()
        self.running = False
        self.sse_thread = None
        self.sse_url = "http://127.0.0.1:8790/api/hud/events"

        # Drag state for moving the panel
        self.dragging = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        # Panel position
        self.x = CHAT_X
        self.y = CHAT_Y
        self.width = CHAT_WIDTH
        self.height = CHAT_HEIGHT

        # Input field state
        self.input_active = False
        self.input_text = ""
        self.cursor_blink = 0

        # Último estado de voz (indicador visual — fora do histórico)
        self.last_status = "idle"

        # Hook local (HUD registra): comandos resolvidos sem HTTP
        self.on_local_command = None

    def start(self):
        """Start SSE connection thread."""
        self.running = True
        self.sse_thread = threading.Thread(target=self._sse_loop, daemon=True)
        self.sse_thread.start()

    def stop(self):
        self.running = False

    def _sse_loop(self):
        """Connect to SSE endpoint and process events."""
        while self.running:
            try:
                req = urllib.request.Request(self.sse_url)
                req.add_header('Accept', 'text/event-stream')
                req.add_header('Cache-Control', 'no-cache')
                response = urllib.request.urlopen(req, timeout=30)

                buffer = b""
                for chunk in iter(lambda: response.read(1024), b""):
                    if not self.running:
                        break
                    buffer += chunk
                    lines = buffer.split(b"\n")
                    buffer = lines[-1]  # Keep incomplete line
                    for line in lines[:-1]:
                        self._process_sse_line(line.decode('utf-8', errors='ignore'))

            except Exception:
                # Connection failed, wait and retry
                time.sleep(5)

    def _process_sse_line(self, line):
        """Process a single SSE line."""
        line = line.strip()
        if not line or line.startswith(":"):
            return
        if line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
                self._handle_event(data)
            except json.JSONDecodeError:
                pass

    def _handle_event(self, data):
        """Handle incoming event from ARIS Event Bus."""
        event_type = data.get("type", "")
        payload = data.get("payload", {})

        # Map event types to chat messages
        if event_type == "aris_speak":
            text = payload.get("text", "")
            if text:
                self.add_message("ARIS", text, CYAN)
        elif event_type == "user_command":
            text = payload.get("command", "")
            if text:
                self.add_message("VOCÊ", text, GREEN)
        elif event_type == "aris_status":
            # Status vai só ao indicador visual — nunca ao histórico do chat
            state = payload.get("state", "")
            if state:
                self.last_status = state
        elif event_type == "chat_message":
            # Generic chat message
            sender = payload.get("sender", "ARIS")
            text = payload.get("text", "")
            color = payload.get("color", CYAN)
            if text:
                self.add_message(sender, text, color)

    def add_message(self, sender, text, color):
        """Add a message to the chat history."""
        timestamp = time.strftime("%H:%M:%S")
        with self.lock:
            self.messages.append((sender, text, timestamp, color))
            if len(self.messages) > self.max_messages:
                self.messages.pop(0)
            # Auto-scroll to bottom
            self.scroll_offset = 0

    def update(self, dt):
        """Update animation state."""
        self.cursor_blink += dt

    def handle_event(self, event):
        """Handle pygame events for chat panel interaction."""
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                mx, my = event.pos
                # Check if clicking on panel header
                if (self.x <= mx <= self.x + self.width and
                        self.y <= my <= self.y + 30):
                    self.dragging = True
                    self.drag_offset_x = mx - self.x
                    self.drag_offset_y = my - self.y
                    return True
                # Check if clicking on input field
                input_y = self.y + self.height - 35
                if (self.x + 5 <= mx <= self.x + self.width - 5 and
                        input_y <= my <= input_y + 30):
                    self.input_active = True
                    return True
                else:
                    self.input_active = False
            elif event.button == 4:  # Scroll up
                mx, my = event.pos
                if self.x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height:
                    with self.lock:
                        self.scroll_offset = min(self.scroll_offset + 20, 0)
                    return True
            elif event.button == 5:  # Scroll down
                mx, my = event.pos
                if self.x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height:
                    with self.lock:
                        self.scroll_offset -= 20
                    return True

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.dragging = False

        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                mx, my = event.pos
                self.x = mx - self.drag_offset_x
                self.y = my - self.drag_offset_y
                # Keep panel on screen
                self.x = max(0, min(self.x, WIDTH - self.width))
                self.y = max(0, min(self.y, HEIGHT - self.height))
                return True

        elif event.type == pygame.KEYDOWN and self.input_active:
            if event.key == pygame.K_RETURN:
                if self.input_text.strip():
                    # Send command to ARIS
                    self._send_command(self.input_text.strip())
                    self.input_text = ""
                self.input_active = False
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.input_text = self.input_text[:-1]
                return True
            elif event.key == pygame.K_ESCAPE:
                self.input_active = False
                return True
            else:
                self.input_text += event.unicode
                return True

        return False

    def _send_command(self, text):
        """Send command to ARIS via HTTP API (ou hook local)."""
        try:
            if self.on_local_command and self.on_local_command(text):
                return
        except Exception:
            pass
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8790/api/hud/command",
                data=json.dumps({"command": text}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass

    def draw(self, surface):
        """Draw the chat panel."""
        # Panel background
        panel_surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        pygame.draw.rect(panel_surf, (*PANEL_FILL, 226),
                         (0, 0, self.width, self.height), border_radius=10)
        pygame.draw.rect(panel_surf, (*CYAN_DIM, 190),
                         (0, 0, self.width, self.height), 1, border_radius=10)

        # Header (30px — geometria do hit-test de drag)
        pygame.draw.rect(panel_surf, (*CYAN_DIM, 110),
                         (0, 0, self.width, 30),
                         border_top_left_radius=10, border_top_right_radius=10)
        pygame.draw.rect(panel_surf, (*AMBER, 235), (0, 26, self.width, 3))
        font_title = _font("vt323", 16)
        title_txt = font_title.render("CHAT // ARIS", True, CYAN)
        panel_surf.blit(title_txt, (10, 3))

        # Message area
        msg_area_y = 35
        msg_area_h = self.height - 75
        clip_rect = pygame.Rect(5, msg_area_y, self.width - 10, msg_area_h)
        panel_surf.set_clip(clip_rect)

        with self.lock:
            messages = list(self.messages)

        # Draw messages from bottom up as bubbles (VOCÊ→direita/verde, ARIS→esquerda/ciano)
        y = msg_area_y + msg_area_h - 20 + self.scroll_offset
        for sender, text, timestamp, color in reversed(messages):
            font = _font("Consolas", 10)
            font_hd = _font("vt323", 13)
            mine = sender == "VOCÊ"
            bubble = GREEN if mine else CYAN

            # Wrap text into lines
            max_w = self.width - 70
            lines, line = [], ""
            for word in text.split(" "):
                test_line = line + word + " "
                if font.size(test_line)[0] > max_w and line:
                    lines.append(line)
                    line = word + " "
                else:
                    line = test_line
            if line:
                lines.append(line)
            if not lines:
                lines = [""]

            block_h = len(lines) * 16 + 24
            y -= block_h
            bx = self.width - 15 - max_w - 20 if mine else 10
            pygame.draw.rect(panel_surf, (*PANEL_FILL, 208),
                             (bx, y, max_w + 20, block_h), border_radius=9)
            pygame.draw.rect(panel_surf, (*bubble, 165),
                             (bx, y, max_w + 20, block_h), 1, border_radius=9)
            # acento lateral + avatar do sender
            pygame.draw.rect(panel_surf, (*bubble, 235),
                             (bx if not mine else bx + max_w + 16, y + 6, 3,
                              block_h - 12))
            pygame.draw.circle(panel_surf, (*bubble, 235),
                               (bx + 14, y + 12), 4)

            snd_txt = font_hd.render(sender.upper(), True, bubble)
            panel_surf.blit(snd_txt, (bx + 24, y + 4))
            ts_txt = _font("Consolas", 8).render(timestamp, True, DARK_GRAY)
            ts_rect = ts_txt.get_rect(topright=(bx + max_w + 12, y + 7))
            panel_surf.blit(ts_txt, ts_rect)
            for i, ln in enumerate(lines):
                txt_surf = font.render(ln, True, WHITE)
                panel_surf.blit(txt_surf, (bx + 8, y + 22 + i * 16))

            y -= 8

        panel_surf.set_clip(None)

        # Input field (30px em height-35 — geometria do hit-test)
        input_y = self.height - 35
        fill = (4, 9, 17, 235)
        edge = (*CYAN, 235) if self.input_active else (*DARK_GRAY, 175)
        pygame.draw.rect(panel_surf, fill, (5, input_y, self.width - 10, 30),
                         border_radius=6)
        pygame.draw.rect(panel_surf, edge, (5, input_y, self.width - 10, 30),
                         1 if not self.input_active else 2, border_radius=6)
        if self.input_active:
            pygame.draw.rect(panel_surf, (*CYAN_GLOW, 60),
                             (6, input_y + 1, self.width - 12, 28),
                             border_radius=5)
            if int(self.cursor_blink * 2) % 2 == 0:
                cursor_text = self.input_text + "|"
            else:
                cursor_text = self.input_text
        else:
            cursor_text = self.input_text if self.input_text else "pergunte à A.R.I.S..."

        font = _font("Consolas", 10)
        inp_txt = font.render(cursor_text, True,
                              WHITE if self.input_active else GRAY)
        panel_surf.blit(inp_txt, (12, input_y + 7))

        surface.blit(panel_surf, (self.x, self.y))

    def contains(self, px, py):
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height


class MetricsFetcher:
    """Fetch system metrics from HUD server in background."""

    def __init__(self):
        self.cpu = "--"
        self.ram = "--"
        self.uptime = "--:--"
        self.mode = "EDGE"
        self.status = "ONLINE"
        self.lock = threading.Lock()
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        import json
        import urllib.request
        while self.running:
            try:
                r = urllib.request.urlopen(METRICS_URL, timeout=3)
                data = json.loads(r.read())
                with self.lock:
                    self.cpu = f"{data.get('cpu', 0):.0f}%"
                    self.ram = f"{data.get('ram', 0):.0f}%"
                    self.uptime = self._fmt_uptime(data.get('uptime', 0))
            except Exception:
                pass
            try:
                r = urllib.request.urlopen(STATUS_URL, timeout=3)
                data = json.loads(r.read())
                with self.lock:
                    self.mode = data.get("mode", {}).get("current", "EDGE") if isinstance(data.get("mode"), dict) else "EDGE"
                    self.status = data.get("status", "unknown")
            except Exception:
                pass
            time.sleep(2)

    def _fmt_uptime(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def get(self):
        with self.lock:
            return {
                "cpu": self.cpu,
                "ram": self.ram,
                "uptime": self.uptime,
                "mode": self.mode,
                "status": self.status,
            }

    def stop(self):
        self.running = False


class HUD:
    """Main Pygame HUD."""

    def __init__(self):
        pygame.init()
        pygame.display.set_caption("A.R.I.S. HUD")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.NOFRAME)
        self.clock = pygame.time.Clock()
        self.running = True

        # Components
        self.tracker = HandTracker()
        self.hologram = Hologram(WIDTH // 2, HEIGHT // 2)
        self.metrics = MetricsFetcher()
        self.scan_line = ScanLine()
        self.corner_hud = CornerHUD()
        self.chat_panel = ChatPanel()

        # Particles
        self.particles = [Particle(WIDTH // 2, HEIGHT // 2) for _ in range(30)]

        # Data streams
        self.data_streams = DataStream(WIDTH // 2, HEIGHT // 2)

        # Orbs — coluna esquerda empilhada (não colidem com painéis/chat)
        orb_x = 88
        self.orbs = [
            Orb(orb_x, 292, "CPU", "--"),
            Orb(orb_x, 362, "RAM", "--"),
            Orb(orb_x, 432, "UPTIME", "--:--"),
            Orb(orb_x, 502, "MODO", "EDGE"),
            Orb(orb_x, 572, "STATUS", "ONLINE"),
        ]

        # Vignette da câmera (bordas escurecidas + tinte ciano fraco)
        self._vignette = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._vignette.fill((0, 26, 38, 20))
        for i in range(0, 72, 6):
            a = int(74 * (1 - i / 72))
            pygame.draw.rect(self._vignette, (2, 5, 10, a), (0, i, WIDTH, 6))
            pygame.draw.rect(self._vignette, (2, 5, 10, a),
                             (0, HEIGHT - i - 6, WIDTH, 6))
            pygame.draw.rect(self._vignette, (2, 5, 10, a), (i, 0, 6, HEIGHT))
            pygame.draw.rect(self._vignette, (2, 5, 10, a),
                             (WIDTH - i - 6, 0, 6, HEIGHT))

        # Moldura inset dupla da tela (uma vez, blit por frame)
        self._frame_edge = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        pygame.draw.rect(self._frame_edge, (*CYAN_DIM, 110),
                         (5, 5, WIDTH - 10, HEIGHT - 10), 1)
        pygame.draw.rect(self._frame_edge, (*CYAN, 45),
                         (9, 9, WIDTH - 18, HEIGHT - 18), 1)

        # Hand interaction state
        self.prev_hand_x = 0
        self.prev_hand_y = 0
        self.hand_vel_x = 0
        self.hand_vel_y = 0
        self.prev_two_hand_dist = 0
        self.dragging = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        # Throw: soltura rápida = flick (px/s no histórico pré-release)
        self.throw_threshold = 800.0

        # Telemetria de gesto (validação: tap/drag/zoom/flick/place/reset)
        self.gesture_stats = {"tap": 0, "drag": 0, "zoom": 0, "flick": 0,
                              "place": 0, "reset": 0}

        # Drag limits
        self.min_scale = 0.3
        self.max_scale = 3.0

        # Câmera: retry automático + botões (settings/chat)
        self._cam_retry_at = 0.0
        self.chat_visible = True
        self.settings_open = False
        self._settings_rects = {}

        # Workspace ARQUIVOS (pasta jail + itens gestuais)
        from core.vision.hud.workspace import WorkspaceManager, match_folder_command
        self.workspace = WorkspaceManager(DATA_DIR / "workspace")
        self._match_folder_command = match_folder_command
        self.chat_panel.on_local_command = self._local_command
        # 2 mãos: uma máquina de pinça por mão + ângulo anterior
        # (speed_aware = razão gap/tamanho-mão + release bar por velocidade)
        from core.vision.hud.workspace import HandPinch
        self._pinch = [HandPinch(speed_aware=True), HandPinch(speed_aware=True)]
        self._prev_two_dist = 0.0
        self._prev_two_ang = 0.0
        self._ws_grab = None
        self._ws_grab_dx = 0.0
        self._ws_grab_dy = 0.0
        # 2 mãos: janela de pausa + EMA (zoom/giro não disparam no ruído)
        self._two_hand_since = 0.0
        self._two_dist_ema = 0.0
        self._two_rot_ema = 0.0
        # Reset por 2 punhos segurados
        self._fist_since = 0.0
        self._reset_cooldown_until = 0.0
        # Manipulação com 2 mãos no meio da pinça anula o tap na soltura
        self._two_used = False

        # Itens da pasta aberta vivem sobre a câmera (sem abas)
        self._ws_surf_cache = {}

        # Aba de documento (texto em 3D / modelo 3D) + caches de render
        from core.vision.hud.viewer import DocViewer
        self.viewer = DocViewer()
        self._viewer_cache = {}
        self._mesh_cache = {}
        self._viewer_drag = None     # [x, y, modo] = 1 mão arrastando a aba
        self._viewer_mouse = None    # [x0, y0, lx, ly] = mouse na aba
        self._viewer_last_tap = 0.0   # gesto: 2 taps em ≤0.6s fecham a aba
        self._viewer_last_click = 0.0 # mouse: 2 cliques em ≤0.45s fecham
        self._ws_mouse = None         # [x0, y0, t0, card, offx, offy] = mouse no card

    def start(self):
        self.metrics.start()
        self.chat_panel.start()
        cam_ok = self.tracker.start()
        if cam_ok:
            print("Camera + Hand Tracking ativo")
            for _ in range(30):
                if self.tracker.get_frame() is not None:
                    print("Primeiro frame da camera recebido")
                    break
                time.sleep(0.1)
        else:
            print("Camera indisponivel — usando sem tracking")

    def run(self):
        self.start()
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self._handle_events()
            self._update(dt)
            self._draw()
            pygame.display.flip()
        self.tracker.stop()
        self.metrics.stop()
        self.chat_panel.stop()
        pygame.quit()

    def _card_at(self, mx: float, my: float):
        """Card do workspace sob o ponto (inclusive o VOLTAR, que não arrasta)."""
        from core.vision.hud.workspace import card_hit
        for it in reversed(self.workspace.items):
            if card_hit(it, mx, my):
                return it
        return None

    def _handle_events(self):
        for event in pygame.event.get():
            # Let chat panel handle its events first (só se visível)
            if self.chat_visible and self.chat_panel.handle_event(event):
                continue
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_f:
                    self.tracker.mirror = not self.tracker.mirror
                    print("Espelho: " + ("ON" if self.tracker.mirror else "OFF"))
                elif event.key == pygame.K_c:
                    self.tracker.cycle_camera()
                elif event.key == pygame.K_v:
                    self.tracker.rotation = (self.tracker.rotation + 90) % 360
                    print(f"Rotação: {self.tracker.rotation}°")
            elif event.type == pygame.MOUSEWHEEL:
                # Roda do mouse rola a página de texto com a aba aberta
                if self.viewer.visible and self.viewer.kind == "text":
                    self.viewer.scroll_by_lines(-event.y * 3.0)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    mx, my = event.pos
                    if self.viewer.visible and self.viewer.hit(mx, my):
                        self._viewer_mouse = [mx, my, mx, my]
                        continue
                    if self._handle_chrome_click(mx, my):
                        continue
                    card = self._card_at(mx, my)
                    if card is not None:
                        # Clique/arrasto em card (inclusive o VOLTAR)
                        self._ws_mouse = [mx, my, time.monotonic(), card,
                                          mx - card.x, my - card.y]
                        continue
                    for i, orb in enumerate(self.orbs):
                        if orb.contains(mx, my):
                            self.dragging = f"orb_{i}"
                            self.drag_offset_x = mx - orb.x
                            self.drag_offset_y = my - orb.y
                            orb.grabbed = True
                            break
                    if self.dragging is None:
                        hx, hy = self.hologram.x, self.hologram.y
                        if math.hypot(mx - hx, my - hy) < 120:
                            self.dragging = "hologram"
                            self.drag_offset_x = mx - hx
                            self.drag_offset_y = my - hy
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    if self._viewer_mouse is not None:
                        x0, y0, lx, ly = self._viewer_mouse
                        self._viewer_mouse = None
                        # Clique curto na aba; o 2º clique em ≤0.45s fecha
                        if abs(lx - x0) + abs(ly - y0) < 8:
                            now = time.monotonic()
                            if now - self._viewer_last_click <= 0.45:
                                self.viewer.close()
                                self._viewer_last_click = 0.0
                            else:
                                self._viewer_last_click = now
                        continue
                    if self._ws_mouse is not None:
                        x0, y0, t0 = self._ws_mouse[:3]
                        self._ws_mouse = None
                        mx, my = event.pos
                        now = time.monotonic()
                        if abs(mx - x0) + abs(my - y0) < 8 and now - t0 < 0.5:
                            # Clique curto = tap (abre pasta/arquivo, VOLTAR volta)
                            hit = self.workspace.tap(mx, my, now)
                            if hit is not None:
                                self.open_in_viewer(hit)
                        continue
                    if self.dragging and self.dragging.startswith("orb_"):
                        idx = int(self.dragging.split("_")[1])
                        self.orbs[idx].grabbed = False
                    self.dragging = None
            elif event.type == pygame.MOUSEMOTION:
                if self._viewer_mouse is not None:
                    mx, my = event.pos
                    lx, ly = self._viewer_mouse[2], self._viewer_mouse[3]
                    self.viewer.move_by(mx - lx, my - ly, WIDTH, HEIGHT)
                    self._viewer_mouse[2], self._viewer_mouse[3] = mx, my
                elif self._ws_mouse is not None:
                    mx, my = event.pos
                    card = self._ws_mouse[3]
                    if card.kind != "back":
                        card.x = mx - self._ws_mouse[4]
                        card.y = my - self._ws_mouse[5]
                        card.vx = card.vy = 0.0
                elif self.dragging == "hologram":
                    mx, my = event.pos
                    self.hologram.target_x = mx - self.drag_offset_x
                    self.hologram.target_y = my - self.drag_offset_y
                elif self.dragging and self.dragging.startswith("orb_"):
                    mx, my = event.pos
                    idx = int(self.dragging.split("_")[1])
                    self.orbs[idx].target_x = mx - self.drag_offset_x
                    self.orbs[idx].target_y = my - self.drag_offset_y

    def _update(self, dt):
        self.hologram.update(dt)
        self.scan_line.update(dt)
        self.data_streams.update(dt)
        self.chat_panel.update(dt)

        m = self.metrics.get()
        self.orbs[0].value = m["cpu"]
        self.orbs[1].value = m["ram"]
        self.orbs[2].value = m["uptime"]
        self.orbs[3].value = m["mode"]
        self.orbs[4].value = m["status"][:8]
        for orb in self.orbs:
            orb.update(dt)

        for p in self.particles:
            p.update(dt, self.hologram.x, self.hologram.y)

        hands = self.tracker.get_hands()
        self._process_hands(hands)
        # Arremesso: card voa, some só ao sair inteiro da tela
        self.workspace.step(dt, WIDTH, HEIGHT, self._ws_grab)
        self._maybe_restart_camera()

    def _camera_on(self) -> bool:
        cap = self.tracker.cap
        try:
            return bool(cap is not None and cap.isOpened())
        except Exception:
            return False

    def _maybe_restart_camera(self) -> None:
        """Retry automático da câmera a cada 10s até abrir."""
        if self._camera_on():
            return
        now = time.monotonic()
        if now < self._cam_retry_at:
            return
        self._cam_retry_at = now + 10.0
        try:
            if self.tracker.start():
                print("Camera reaberta pelo retry automático")
        except Exception:
            pass

    def toggle_camera(self) -> None:
        if self._camera_on():
            try:
                self.tracker.stop()
            except Exception:
                pass
            print("Camera desligada pelo usuário")
        else:
            self._cam_retry_at = 0.0
            self._maybe_restart_camera()

    def _local_command(self, text: str) -> bool:
        """Comandos resolvidos no próprio HUD: 'abre (pasta) X (na camera)'.

        Só consome se a pasta existir; senão devolve False e a ARIS trata.
        """
        name = self._match_folder_command(text)
        if not name:
            return False
        items = self.workspace.open_folder(name)
        if not items:
            return False
        self.chat_panel.add_message("VOCÊ", text, GREEN)
        label = self.workspace.current or name
        reply = f"Pasta {label} aberta na câmera com {len(items)} itens. Use pinça para mover, tap para abrir, 2 mãos para zoom e girar."
        self.chat_panel.add_message("ARIS", reply, CYAN)
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8790/api/hud/speak",
                data=json.dumps({"text": reply}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass
        return True

    def _hand_screen(self, hand):
        from core.vision.hud.workspace import hand_aspect, map_landmark, pinch_ratio
        ratio = pinch_ratio(hand)
        aspect = hand_aspect(hand)
        ix, iy = hand[8]
        sx, sy = map_landmark(ix, iy, self.tracker.mirror, WIDTH, HEIGHT)
        return ratio, sx, sy, aspect

    def _process_hands(self, hands):
        from core.vision.hud.viewer import LINE_H
        from core.vision.hud.workspace import fist_curl, holo_hit, pinch_angle_delta, zoom_factor
        now = time.monotonic()
        if not hands:
            self._prev_two_dist = 0.0
            self._fist_since = 0.0
            # Mão sumiu no quadro do clique: soltura na última posição
            # conhecida (quadro perdido não pode jogar o tap em (0,0))
            self._release_hand(now, self.prev_hand_x, self.prev_hand_y)
            for p in self._pinch:
                p.reset()
            return

        states = []
        for i, hand in enumerate(hands[:2]):
            ratio, sx, sy, aspect = self._hand_screen(hand)
            states.append((self._pinch[i].update(ratio, sx, sy, now, aspect), sx, sy))

        # 2 punhos fechados = reset (o punho lê como pinça e dispararia
        # zoom/giro sozinhos — o gesto de reset corta esse caminho)
        if len(states) == 2 and all(fist_curl(h) >= FIST_CURL for h in hands[:2]):
            self._prev_two_dist = 0.0
            self._hold_fist_reset(now)
            return
        self._fist_since = 0.0

        # 2 mãos pinçadas: pan pelo ponto médio + zoom + rotação
        if len(states) == 2 and states[0][0] and states[1][0]:
            if self.dragging == "hand":
                self.dragging = None
            self._viewer_drag = None
            (_, x1, y1), (_, x2, y2) = states
            mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
            dist = math.hypot(x2 - x1, y2 - y1)
            ang = math.atan2(y2 - y1, x2 - x1)
            first = self._prev_two_dist <= 0
            if first:
                self._two_hand_since = now
                self._two_dist_ema = dist
                self._two_rot_ema = 0.0
            else:
                # Soltura depois de zoom/giro com 2 mãos não vira tap
                self._two_used = True
                # EMA da distância: jitter de ±1px se cancela entre quadros,
                # movimento sustentado passa com o passo cheio
                prev_ema = self._two_dist_ema
                self._two_dist_ema += (dist - self._two_dist_ema) * TWO_HAND_EMA
                rel = zoom_factor(prev_ema, self._two_dist_ema) - 1.0
                self._two_rot_ema += (pinch_angle_delta(self._prev_two_ang, ang)
                                      - self._two_rot_ema) * TWO_HAND_EMA
                ready = (now - self._two_hand_since) >= TWO_HAND_GRACE
                # Aba aberta = foco: giro/zoom/pan valem pra ela
                view = self.viewer
                is_view = view.visible
                tgt = view if is_view else (self._ws_grab or self.hologram)
                is_holo = (not is_view) and tgt is self.hologram
                if ready:
                    if abs(rel) > ZOOM_DEADBAND:
                        z = max(-ZOOM_MAX_STEP, min(ZOOM_MAX_STEP, rel))
                        self.gesture_stats["zoom"] += 1
                        if is_view:
                            tgt.zoom(1.0 + z)
                        elif is_holo:
                            tgt.target_scale = max(
                                self.min_scale,
                                min(self.max_scale, tgt.target_scale * (1.0 + z)))
                        else:
                            tgt.scale = max(0.4, min(2.5, tgt.scale * (1.0 + z)))
                    if abs(self._two_rot_ema) > ROT_DEADBAND and not is_holo:
                        if is_view:
                            tgt.rotate(self._two_rot_ema)
                        else:
                            tgt.rotation += max(-ROT_MAX_STEP,
                                                min(ROT_MAX_STEP, self._two_rot_ema))
                # Pan suave pelo ponto médio
                if is_view:
                    tgt.move_by((mid_x - tgt.x) * 0.35, (mid_y - tgt.y) * 0.35,
                                WIDTH, HEIGHT)
                elif is_holo:
                    tgt.target_x += (mid_x - tgt.target_x) * 0.35
                    tgt.target_y += (mid_y - tgt.target_y) * 0.35
                else:
                    tgt.x += (mid_x - tgt.x) * 0.35
                    tgt.y += (mid_y - tgt.y) * 0.35
            self._prev_two_dist = dist
            self._prev_two_ang = ang
            return

        self._prev_two_dist = 0.0

        # 1 mão: arrasta item do workspace (prioridade) ou holograma
        pinched, sx, sy = states[0]
        self.hand_vel_x = sx - self.prev_hand_x
        self.hand_vel_y = sy - self.prev_hand_y
        if pinched:
            if (self.dragging is None and self._ws_grab is None
                    and self._viewer_drag is None):
                if self.viewer.visible and self.viewer.hit(sx, sy):
                    # Texto: arrastar rola a página; modelo: arrasta a aba
                    mode = "scroll" if self.viewer.kind == "text" else "move"
                    self._viewer_drag = [sx, sy, mode]
                else:
                    grab = self.workspace.grab_at(sx, sy)
                    if grab is not None:
                        self._ws_grab = grab
                        self._ws_grab.vx = self._ws_grab.vy = 0.0
                        self._ws_grab_dx = sx - grab.x
                        self._ws_grab_dy = sy - grab.y
                    elif holo_hit(sx, sy, self.hologram.x, self.hologram.y,
                                  self.hologram.scale):
                        self.dragging = "hand"
                    # Fora do central: pinça no vazio não puxa o holograma
            if self._viewer_drag is not None:
                lx, ly, mode = self._viewer_drag[:3]
                if mode == "scroll":
                    # Dedo pra baixo = página desce com o dedo (conteúdo acima)
                    self.viewer.scroll_by_lines((ly - sy) / LINE_H)
                else:
                    self.viewer.move_by(sx - lx, sy - ly, WIDTH, HEIGHT)
                self._viewer_drag[0], self._viewer_drag[1] = sx, sy
            elif self._ws_grab is not None:
                self._ws_grab.x += (sx - self._ws_grab_dx - self._ws_grab.x) * 0.5
                self._ws_grab.y += (sy - self._ws_grab_dy - self._ws_grab.y) * 0.5
            elif self.dragging == "hand":
                self.hologram.target_x += (sx - self.hologram.target_x) * 0.5
                self.hologram.target_y += (sy - self.hologram.target_y) * 0.5
            moved = abs(sx - self.prev_hand_x) + abs(sy - self.prev_hand_y)
            holding = (self._ws_grab is not None or self.dragging == "hand"
                       or self._viewer_drag is not None)
            if moved > 2.0 and holding and (self.prev_hand_x or self.prev_hand_y):
                self.gesture_stats["drag"] += 1
        else:
            self._release_hand(now, sx, sy)
        self.prev_hand_x = sx
        self.prev_hand_y = sy

    def open_folder_gesture(self) -> None:
        """Gesto/mouse no botão pasta: abre a atual ou a padrão."""
        if self.workspace.current:
            items = self.workspace.open_folder(self.workspace.current)
        else:
            items = self.workspace.open_default()
        name = self.workspace.current or ""
        if items:
            reply = f"Pasta {name} aberta na câmera com {len(items)} itens."
        else:
            reply = "Nenhuma pasta na área de trabalho. Crie em data/workspace/."
        self.chat_panel.add_message("ARIS", reply, CYAN)

    def open_in_viewer(self, item) -> bool:
        """Tap em arquivo: cada categoria tem sua ação (aba ou programa padrão)."""
        from core.vision.hud.workspace import file_category
        path = self.workspace.path_of(item)
        if path is None:
            return False
        cat = item.cat or file_category(path)
        # Aba centrada na área livre (deslocada se o chat estiver aberto)
        cx = (WIDTH - CHAT_WIDTH - 20) / 2 if self.chat_visible else WIDTH / 2
        center = (cx, HEIGHT / 2)
        try:
            if item.kind == "model3d" or cat == "model":
                mesh = self._mesh_cache.get(str(path))
                if mesh is None:
                    from core.vision.hud.model3d import load_mesh
                    mesh = load_mesh(path)
                    if len(self._mesh_cache) > 8:
                        self._mesh_cache.clear()
                    self._mesh_cache[str(path)] = mesh
                self.viewer.open_model(path, mesh, center)
            elif cat == "image":
                self.viewer.open_image(path, center)
            elif cat == "archive":
                from core.vision.hud.viewer import read_archive_lines
                lines = read_archive_lines(path)
                self.viewer.open_text(path, center)  # aba de leitura...
                self.viewer.lines = lines            # ...com o índice do archive
                self.viewer.rev += 1
            elif cat == "text":
                self.viewer.open_text(path, center)
            else:
                # media/doc/exe/arquivo desconhecido: programa padrão do OS
                return self._open_in_system(path, cat)
        except Exception as exc:
            self.chat_panel.add_message("ARIS", f"Não abri {path.name}: {exc}", RED)
            return False
        hints = {
            "model": "2 mãos giram e dão zoom, 2 taps fecham.",
            "image": "2 mãos inclinam a imagem, 2 taps fecham.",
            "text": "2 mãos giram em 3D, arrastar rola, 2 taps fecham.",
        }
        self.chat_panel.add_message(
            "ARIS", f"Aba {self.viewer.name} aberta. {hints.get(cat, '')}",
            CYAN)
        return True

    def _open_in_system(self, path, cat: str) -> bool:
        """Abre no programa padrão do Windows (mídia, doc, exe, zip sem leitor)."""
        import os as _os
        labels = {"media": "mídia", "doc": "documento", "exe": "aplicativo",
                  "archive": "compactado", "file": "arquivo"}
        try:
            _os.startfile(str(path))  # noqa: S606 - ação pedida pelo usuário
        except OSError as exc:
            self.chat_panel.add_message(
                "ARIS", f"Não abri {path.name}: {exc}", RED)
            return False
        self.chat_panel.add_message(
            "ARIS", f"Abrindo {labels.get(cat, 'arquivo')} {path.name} "
                    f"no programa padrão.", CYAN)
        return True

    def _release_hand(self, now, sx=0.0, sy=0.0):
        """Soltura classificada: flick (rápido) > tap (curto) > place (lento).

        A velocidade vem do histórico pré-release (px/s) da HandPinch — a do
        quadro atual nunca serve para decidir; hand_vel_* só empurra o lançamento.
        Tap vale pela posição da soltura OU do início da pinça (mão derivou /
        quadro perdido não joga em 0,0) e vale mesmo segurando: mão parada perto
        do início é tap, não place. Uma ação por pinça (armed), sem re-fire.
        """
        from core.vision.hud.workspace import TAP_MAX_MOVE, holo_hit
        pinch = self._pinch[0]
        if not pinch.armed:
            return  # mão aberta sem pinça nova: a ação já foi despachada
        view_drag = self._viewer_drag is not None
        had_target = (self._ws_grab is not None or self.dragging == "hand"
                      or view_drag)
        two_used = self._two_used
        pinch.armed = False
        self._viewer_drag = None
        self._two_used = False
        is_flick = pinch.last_speed > self.throw_threshold
        quick = pinch.is_tap(now)
        near = pinch.moved(sx, sy) <= TAP_MAX_MOVE
        is_tap = (quick or near) and not is_flick and not two_used
        # Fechar a aba exige tap "de verdade": rápido E parado no lugar
        # (rolar o texto com a mão e soltar não pode fechar o documento)
        strict_tap = quick and near and not is_flick and not two_used
        starts = ((sx, sy), (pinch.down_x, pinch.down_y))
        hz = self.hologram
        on_holo = any(holo_hit(px, py, hz.x, hz.y, hz.scale) for px, py in starts)
        if is_tap:
            # 1) Botão chrome = ação (pasta/câmera/chat/config)
            for name, rect in self._chrome_buttons().items():
                if any(rect.collidepoint(px, py) for px, py in starts):
                    if name == "folder":
                        self.open_folder_gesture()
                    elif name == "camera":
                        self.toggle_camera()
                    elif name == "chat":
                        self.chat_visible = not self.chat_visible
                    elif name == "settings":
                        self.settings_open = not self.settings_open
                    self.gesture_stats["tap"] += 1
                    self._ws_grab = None
                    self.dragging = None
                    return
            # 2) Aba de documento: 2 taps em ≤0.6s fecham (1 tap só avisa)
            if (strict_tap and self.viewer.visible
                    and any(self.viewer.hit(px, py) for px, py in starts)):
                if now - self._viewer_last_tap <= 0.6:
                    self._viewer_last_tap = 0.0
                    self.viewer.close()
                else:
                    self._viewer_last_tap = now
                self.gesture_stats["tap"] += 1
                return
        if self._ws_grab is not None:
            if is_flick:
                # Arremesso com física: voa e some SÓ ao sair da tela
                self._ws_grab.vx, self._ws_grab.vy = self._throw_velocity(pinch)
                self.gesture_stats["flick"] += 1
            elif is_tap:
                hit = self.workspace.tap(sx, sy, now)
                if hit is None:
                    hit = self.workspace.tap(pinch.down_x, pinch.down_y, now)
                if hit is not None:
                    self.gesture_stats["tap"] += 1
                    self.open_in_viewer(hit)
            else:
                self.gesture_stats["place"] += 1
            self._ws_grab = None
        if self.dragging == "hand":
            if is_flick:
                self.hologram.vx, self.hologram.vy = self._throw_velocity(pinch)
                self.gesture_stats["flick"] += 1
            elif is_tap:
                if on_holo:
                    # Tap no central = navegador ARQUIVOS (carrega os cards)
                    self.open_folder_gesture()
                else:
                    hit = self.workspace.tap(sx, sy, now)
                    if hit is None:
                        hit = self.workspace.tap(pinch.down_x, pinch.down_y, now)
                    if hit is not None:
                        self.open_in_viewer(hit)
                self.gesture_stats["tap"] += 1
            else:
                self.gesture_stats["place"] += 1
            self.dragging = None
        # 3) Pinça começou no vazio: soltar em cima de algo ainda conta tap
        if is_tap and not had_target:
            hit = self.workspace.tap(sx, sy, now)
            if hit is None:
                hit = self.workspace.tap(pinch.down_x, pinch.down_y, now)
            if hit is not None:
                self.gesture_stats["tap"] += 1
                self.open_in_viewer(hit)
            elif on_holo:
                self.open_folder_gesture()
                self.gesture_stats["tap"] += 1

    def _throw_velocity(self, pinch) -> tuple[float, float]:
        """Vetor do arremesso (px/s): direção da mão + pico pré-release."""
        speed = min(max(pinch.last_speed, 400.0), 3000.0) * THROW_POWER
        norm = math.hypot(self.hand_vel_x, self.hand_vel_y)
        if norm < 1e-3:
            return 0.0, 0.0
        return (self.hand_vel_x / norm * speed, self.hand_vel_y / norm * speed)

    def _hold_fist_reset(self, now: float) -> None:
        """2 punhos: segura FIST_HOLD_S -> reset (cooldown anti re-disparo)."""
        if now < self._reset_cooldown_until:
            self._fist_since = 0.0
            return
        if self._fist_since <= 0.0:
            self._fist_since = now
            return
        if now - self._fist_since >= FIST_HOLD_S:
            self._reset_hud(now)

    def _reset_hud(self, now: float) -> None:
        """Fecha cards e configurações, centraliza o holograma (chat fica)."""
        self.workspace.clear()
        self.settings_open = False
        self.viewer.close()
        self._viewer_drag = None
        self._viewer_mouse = None
        hz = self.hologram
        hz.x = hz.target_x = WIDTH / 2
        hz.y = hz.target_y = HEIGHT / 2
        hz.scale = hz.target_scale = 1.0
        hz.vx = hz.vy = 0.0
        self._ws_grab = None
        self.dragging = None
        self._prev_two_dist = 0.0
        self._prev_two_ang = 0.0
        self._fist_since = 0.0
        self._reset_cooldown_until = now + RESET_COOLDOWN_S
        self.gesture_stats["reset"] += 1
        self.chat_panel.add_message(
            "ARIS", "HUD reiniciado: cards fechados, central no centro.", CYAN)

    def _draw(self):
        self.screen.fill(BG_COLOR)

        # Webcam background — direto, sem efeito
        frame = self.tracker.get_frame()
        if frame is not None:
            self.screen.blit(frame, (0, 0))
            self.screen.blit(self._vignette, (0, 0))

        # Scan line
        self.scan_line.draw(self.screen)

        # Particles
        for p in self.particles:
            p.draw(self.screen)

        # Data streams
        self.data_streams.draw(self.screen)

        # Hologram
        self.hologram.draw(self.screen)

        # Orbs
        for orb in self.orbs:
            orb.draw(self.screen)

        # Workspace: itens da pasta aberta direto sobre a câmera
        for it in self.workspace.items:
            self._draw_ws_item(it)

        # Aba de documento: página de texto em 3D ou visualizador de modelo
        if self.viewer.visible:
            self._draw_viewer()

        # Hand cursors + esqueleto completo (mesmo espelho do display)
        from core.vision.hud.workspace import map_landmark
        hands = self.tracker.get_hands()
        for hand in hands:
            pts = [map_landmark(ix, iy, self.tracker.mirror, WIDTH, HEIGHT)
                   for ix, iy in hand]
            for a, b in HAND_CONNECTIONS:
                if a < len(pts) and b < len(pts):
                    pygame.draw.line(
                        self.screen, CYAN_DIM,
                        (int(pts[a][0]), int(pts[a][1])),
                        (int(pts[b][0]), int(pts[b][1])), 2,
                    )
            for i, (px, py) in enumerate(pts):
                if i in HAND_KEY_POINTS:
                    pygame.draw.circle(self.screen, GREEN, (int(px), int(py)), 5)
                else:
                    pygame.draw.circle(self.screen, CYAN, (int(px), int(py)), 3)
            if len(pts) > 8:
                sx, sy = int(pts[8][0]), int(pts[8][1])
                pygame.draw.circle(self.screen, CYAN, (sx, sy), 8, 2)
                if len(pts) > 4:
                    pygame.draw.line(self.screen, CYAN_DIM,
                                     (int(pts[4][0]), int(pts[4][1])), (sx, sy), 1)
                if len(hands) >= 2:
                    pygame.draw.circle(self.screen, GREEN, (sx, sy), 12, 1)

        # Debug de rastreamento (mãos + confiança da inferência)
        self._draw_hand_debug(len(hands))

        # Chat panel (ocultável — modo só-microfone)
        if self.chat_visible:
            self.chat_panel.draw(self.screen)

        # Corner HUD panels
        m = self.metrics.get()
        right_edge = CHAT_X - 6 if self.chat_visible else WIDTH - 16
        self.corner_hud.draw(self.screen, m, fps=max(1, int(self.clock.get_fps())),
                             right_edge=right_edge, cam=frame is not None)

        # Status pill (estado de voz) + moldura da tela
        self._draw_status_pill()
        self._draw_frame_chrome(has_camera=frame is not None)
        self._draw_chrome_buttons()
        if self.settings_open:
            self._draw_settings()

    def _draw_ws_icon(self, surf, cat: str, color, x: int, y: int) -> None:
        """Ícone do card por categoria (primitivas — não depende de fonte)."""
        if cat == "image":
            pygame.draw.rect(surf, (*color, 235), (x, y + 2, 24, 19), 2,
                             border_radius=3)
            pygame.draw.polygon(surf, (*color, 235),
                                [(x + 4, y + 19), (x + 11, y + 9), (x + 16, y + 19)])
            pygame.draw.circle(surf, (*color, 235), (x + 18, y + 7), 3)
        elif cat == "archive":
            pygame.draw.rect(surf, (*color, 235), (x + 4, y, 16, 23), 2,
                             border_radius=3)
            for i in range(4):  # zíper
                pygame.draw.line(surf, (*color, 255), (x + 12, y + 3 + i * 5),
                                 (x + 12, y + 6 + i * 5), 2)
        elif cat == "media":
            pygame.draw.circle(surf, (*color, 235), (x + 12, y + 11), 11, 2)
            pygame.draw.polygon(surf, (*color, 255),
                                [(x + 9, y + 6), (x + 17, y + 11), (x + 9, y + 16)])
        elif cat == "doc":
            pygame.draw.rect(surf, (*color, 235), (x + 3, y, 17, 23), 2,
                             border_radius=3)
            for i in range(3):
                pygame.draw.line(surf, (*color, 235), (x + 7, y + 7 + i * 5),
                                 (x + 16, y + 7 + i * 5), 2)
        elif cat == "exe":
            pygame.draw.circle(surf, (*color, 235), (x + 12, y + 11), 9, 2)
            pygame.draw.line(surf, (*color, 255), (x + 12, y + 1), (x + 12, y + 21), 2)
            pygame.draw.line(surf, (*color, 255), (x + 2, y + 11), (x + 22, y + 11), 2)
        else:  # text/file: folha com linhas
            pygame.draw.rect(surf, (*color, 235), (x + 3, y, 17, 23), 2,
                             border_radius=3)
            pygame.draw.line(surf, (*color, 235), (x + 7, y + 8), (x + 16, y + 8), 2)
            pygame.draw.line(surf, (*color, 235), (x + 7, y + 13), (x + 16, y + 13), 2)
            pygame.draw.line(surf, (*color, 235), (x + 7, y + 18), (x + 12, y + 18), 2)

    def _image_preview(self, it, w: int, h: int):
        """Miniatura da imagem no card (PIL thumbnail, cacheada pelo card)."""
        from PIL import Image as PILImage
        try:
            path = self.workspace.path_of(it)
            if path is None:
                return None
            with PILImage.open(path) as im:
                im = im.convert("RGBA")
                im.thumbnail((w, h), PILImage.Resampling.LANCZOS)
                thumb = pygame.image.frombytes(im.tobytes(), im.size, "RGBA")
            box = pygame.Surface((w, h), pygame.SRCALPHA)
            box.fill((2, 6, 13, 160))
            box.blit(thumb, thumb.get_rect(center=(w // 2, h // 2)))
            return box
        except Exception:
            return None

    def _draw_ws_item(self, it):
        import math as _m
        card_w, card_h = 210, 130
        # open/children entram na chave: expandir/recolher não pode servir
        # uma surface obsoleta que já estava em cache
        key = (it.id, round(it.scale, 1), round(it.rotation / 0.26),
               it.open, len(it.children))
        surf = self._ws_surf_cache.get(key)
        if surf is None:
            extra = 20 * len(it.children) if it.open else 0
            surf = pygame.Surface((card_w, card_h + extra), pygame.SRCALPHA)
            if it.kind == "folder":
                color = GREEN
            elif it.kind == "model3d":
                color = AMBER
            else:
                color = WS_CAT_COLORS.get(it.cat, CYAN)
            pygame.draw.rect(surf, (*PANEL_FILL, 228), (0, 0, card_w, surf.get_height()), border_radius=10)
            pygame.draw.rect(surf, (*color, 220), (0, 0, card_w, surf.get_height()), 2, border_radius=10)
            # acento lateral colorido (linguagem de painel do HUD)
            pygame.draw.rect(surf, (*color, 240), (3, 9, 4, surf.get_height() - 18))
            if it.kind == "back":
                font = _font("Consolas", 22, bold=True)
                surf.blit(font.render("◀", True, color), (16, 9))
            elif it.kind == "folder":
                font = _font("Consolas", 22, bold=True)
                surf.blit(font.render("▤", True, color), (16, 9))
            elif it.kind == "model3d":
                font = _font("Consolas", 22, bold=True)
                surf.blit(font.render("⬢", True, color), (16, 9))
            else:
                self._draw_ws_icon(surf, it.cat, color, 17, 11)
            font_n = _font("vt323", 16)
            surf.blit(font_n.render(it.name[:24], True, WHITE), (48, 11))
            # tag de tipo no canto
            tag = WS_CAT_TAGS.get(it.cat) or {"folder": "PASTA",
                                               "model3d": "3D",
                                               "back": "VOLTAR"}.get(it.kind, "ARQ")
            font_t = _font("vt323", 12)
            tag_s = font_t.render(tag, True, color)
            surf.blit(tag_s, (card_w - tag_s.get_width() - 10, 13))
            if it.kind == "model3d":
                # Preview real do mesh (capacete/armadura/etc) no card
                prev = self._model_preview(it, card_w - 36, card_h - 62)
                if prev is not None:
                    surf.blit(prev, (18, 36))
            elif it.cat == "image":
                prev = self._image_preview(it, card_w - 36, card_h - 62)
                if prev is not None:
                    surf.blit(prev, (18, 36))
            if it.open and it.children:
                font_c = _font("Consolas", 10)
                for i, kid in enumerate(it.children[:8]):
                    surf.blit(font_c.render("▸ " + kid[:26], True, GRAY), (14, 52 + i * 18))
            if len(self._ws_surf_cache) > 64:
                self._ws_surf_cache.clear()
            self._ws_surf_cache[key] = surf
        if abs(it.rotation) > 0.02:
            shown = pygame.transform.rotozoom(surf, -_m.degrees(it.rotation), it.scale)
        elif abs(it.scale - 1.0) > 0.02:
            shown = pygame.transform.scale(surf, (int(surf.get_width() * it.scale), int(surf.get_height() * it.scale)))
        else:
            shown = surf
        self.screen.blit(shown, shown.get_rect(center=(int(it.x), int(it.y))))

    def _model_preview(self, it, w: int, h: int):
        """Miniatura do modelo 3D no card (mesh real, cacheada por arquivo)."""
        from core.vision.hud.model3d import FALLBACK_COLOR, load_mesh, render_mesh
        try:
            path = self.workspace.path_of(it)
            if path is None:
                return None
            mesh = self._mesh_cache.get(str(path))
            if mesh is None:
                mesh = load_mesh(path)
                if len(self._mesh_cache) > 8:
                    self._mesh_cache.clear()
                self._mesh_cache[str(path)] = mesh
            return render_mesh(mesh, w, h, yaw=0.7, pitch=0.35,
                               color=FALLBACK_COLOR)
        except Exception:
            return None

    def _model_page(self, mesh_surf, v):
        """Painel do visualizador 3D: moldura + grid técnico + rodapé de dados."""
        from core.vision.hud.viewer import VIEW_H, VIEW_W
        surf = pygame.Surface((VIEW_W, VIEW_H), pygame.SRCALPHA)
        pygame.draw.rect(surf, (6, 12, 22, 238), (0, 0, VIEW_W, VIEW_H),
                         border_radius=10)
        # grid técnico de fundo + eixos centrais
        for gx in range(42, VIEW_W, 42):
            pygame.draw.line(surf, (26, 64, 90, 70), (gx, 0), (gx, VIEW_H))
        for gy in range(42, VIEW_H, 42):
            pygame.draw.line(surf, (26, 64, 90, 70), (0, gy), (VIEW_W, gy))
        pygame.draw.line(surf, (0, 96, 130, 130), (VIEW_W // 2, 0),
                         (VIEW_W // 2, VIEW_H))
        pygame.draw.line(surf, (0, 96, 130, 130), (0, VIEW_H // 2),
                         (VIEW_W, VIEW_H // 2))
        surf.blit(mesh_surf, (0, 0))
        # rodapé de dados (fecha a linguagem do painel)
        if v.mesh is not None:
            bar = pygame.Surface((VIEW_W, 24), pygame.SRCALPHA)
            bar.fill((4, 8, 16, 215))
            surf.blit(bar, (0, VIEW_H - 24))
            font_f = _font("Consolas", 11, bold=True)
            info = (f"MESH // {v.mesh.face_count} FACES  ·  YAW {v.yaw:+.2f}"
                    f"  ·  PITCH {v.pitch:+.2f}")
            surf.blit(font_f.render(info, True, AMBER), (12, VIEW_H - 18))
        return surf

    def _draw_viewer(self):
        """Aba de documento: só o corpo (sem moldura — fechar é com 2 taps)."""
        v = self.viewer
        body = self._viewer_body(v)
        self.screen.blit(body, body.get_rect(center=(int(v.x), int(v.y))))

    def _viewer_body(self, v):
        """Corpo da aba (cacheado): texto = warp em 3D; modelo = render direto."""
        from core.vision.hud.viewer import VIEW_H, VIEW_W, warp_pitch, warp_yaw
        key = (v.rev, v.kind, round(v.yaw, 2), round(v.pitch, 2), round(v.scale, 2))
        cached = self._viewer_cache.get(key)
        if cached is not None:
            return cached
        if v.kind == "model" and v.mesh is not None:
            from core.vision.hud.model3d import FALLBACK_COLOR, render_mesh
            mesh = render_mesh(v.mesh, VIEW_W, VIEW_H, yaw=v.yaw, pitch=v.pitch,
                               color=FALLBACK_COLOR)
            body = self._model_page(mesh, v)
        elif v.kind == "image" and v.image is not None:
            base = self._viewer_cache.get((v.rev, "image"))
            if base is None:
                base = pygame.Surface((VIEW_W, VIEW_H), pygame.SRCALPHA)
                base.fill((6, 12, 22, 200))
                img = v.image
                base.blit(img, img.get_rect(center=(VIEW_W // 2, VIEW_H // 2)))
                self._viewer_cache[(v.rev, "image")] = base
            body = warp_pitch(warp_yaw(base, v.yaw), v.pitch)
        else:
            base = self._viewer_cache.get((v.rev, "text"))
            if base is None:
                base = self._render_text_page(v)
                self._viewer_cache[(v.rev, "text")] = base
            body = warp_pitch(warp_yaw(base, v.yaw), v.pitch)
        if abs(v.scale - 1.0) > 0.02:
            body = pygame.transform.scale(
                body, (max(1, int(body.get_width() * v.scale)),
                       max(1, int(body.get_height() * v.scale))))
        if len(self._viewer_cache) > 48:
            self._viewer_cache.clear()
        self._viewer_cache[key] = body
        return body

    def _render_text_page(self, v):
        """Página de texto da aba: gutter de linhas + scroll + hint."""
        from core.vision.hud.viewer import LINE_H, VIEW_H, VIEW_W
        surf = pygame.Surface((VIEW_W, VIEW_H), pygame.SRCALPHA)
        pygame.draw.rect(surf, (*PANEL_FILL, 240), (0, 0, VIEW_W, VIEW_H),
                         border_radius=10)
        # gutter de números de linha (estilo editor)
        pygame.draw.rect(surf, (2, 6, 13, 215), (3, 3, 36, VIEW_H - 6),
                         border_top_left_radius=9, border_bottom_left_radius=9)
        pygame.draw.line(surf, (*CYAN_DIM, 150), (41, 5), (41, VIEW_H - 5))
        font = _font("Consolas", 14)
        font_n = _font("Consolas", 9)
        rows = VIEW_H // LINE_H + 2
        y = 12 + int(v.line_offset_px())
        for i in range(v.first_line, min(len(v.lines), v.first_line + rows)):
            if y > VIEW_H:
                break
            line = v.lines[i][:76]
            if y + LINE_H > 0:
                if line:
                    surf.blit(font.render(line, True, WHITE), (50, y))
                num = font_n.render(str(i + 1), True, DARK_GRAY)
                surf.blit(num, (34 - num.get_width(), y + 5))
            y += LINE_H
        max_s = v.max_scroll()
        if max_s > 0:
            track = VIEW_H - 12
            visible = max(1, VIEW_H // LINE_H - 2)
            thumb = max(24, int(track * visible / max(1, len(v.lines))))
            ty = 6 + int((track - thumb) * (v.scroll / max_s))
            pygame.draw.rect(surf, (0, 60, 88, 150), (VIEW_W - 10, ty, 7, thumb),
                             border_radius=4)
            pygame.draw.rect(surf, (*CYAN, 220), (VIEW_W - 9, ty + 2, 5, thumb - 4),
                             border_radius=3)
        # hint pill centralizado no rodapé
        font_h = _font("vt323", 15)
        hint = font_h.render("2 mãos = girar/zoom · arrastar = rolar · 2 taps = fechar",
                             True, GRAY)
        hb = pygame.Surface((hint.get_width() + 22, 24), pygame.SRCALPHA)
        pygame.draw.rect(hb, (*PANEL_FILL, 225), (0, 0, hb.get_width(), 24),
                         border_radius=12)
        pygame.draw.rect(hb, (*CYAN_DIM, 170), (0, 0, hb.get_width(), 24), 1,
                         border_radius=12)
        hb.blit(hint, (11, 2))
        surf.blit(hb, (VIEW_W // 2 - hb.get_width() // 2, VIEW_H - 30))
        return surf

    def _draw_status_pill(self):
        states = {
            "listening": (CYAN, "OUVINDO"),
            "thinking": (AMBER, "PENSANDO"),
            "speaking": (GREEN, "FALANDO"),
            "idle": (GRAY, "OCIOSA"),
        }
        color, label = states.get(self.chat_panel.last_status, (GRAY, "OCIOSA"))
        font = _font("vt323", 17)
        txt = font.render(label, True, color)
        w = txt.get_width() + 52
        h = 30
        # halo (glow) + corpo do pill
        halo = pygame.Surface((w + 12, h + 12), pygame.SRCALPHA)
        pygame.draw.rect(halo, (*color, 42), (0, 0, w + 12, h + 12),
                         border_radius=(h + 12) // 2)
        self.screen.blit(halo, (WIDTH // 2 - w // 2 - 6, 6))
        pill = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(pill, (*PANEL_FILL, 215), (0, 0, w, h), border_radius=h // 2)
        pygame.draw.rect(pill, (*color, 220), (0, 0, w, h), 1, border_radius=h // 2)
        pygame.draw.circle(pill, (*color, 255), (18, h // 2), 5)
        pygame.draw.circle(pill, (*color, 70), (18, h // 2), 8)
        pill.blit(txt, (32, 4))
        self.screen.blit(pill, (WIDTH // 2 - w // 2, 12))

    def _draw_hand_debug(self, hand_n: int) -> None:
        """Overlay de rastreamento: mãos, confiança, razão de pinça e velocidade."""
        try:
            count, conf = self.tracker.get_debug_stats()
        except Exception:
            count, conf = hand_n, 0.0
        count = max(count, hand_n)
        ratio = 0.0
        try:
            hands = self.tracker.get_hands()
            if hands:
                from core.vision.hud.workspace import pinch_ratio
                ratio = pinch_ratio(hands[0])
        except Exception:
            pass
        speed = self._pinch[0].last_speed
        color = GREEN if count else RED
        label = (f"MÃOS: {count}  CONF: {conf * 100:.0f}%  "
                 f"LIM: {HAND_DETECTION_CONFIDENCE:.2f}/{HAND_TRACKING_CONFIDENCE:.2f}  "
                 f"RATIO: {ratio:.2f}  V: {speed:.0f}px/s")
        font = _font("vt323", 15)
        txt = font.render(label, True, color)
        w, h = txt.get_width() + 22, 26
        bar = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(bar, (*PANEL_FILL, 200), (0, 0, w, h), border_radius=8)
        pygame.draw.rect(bar, (*color, 210), (0, 0, w, h), 1, border_radius=8)
        pygame.draw.rect(bar, (*color, 235), (0, 6, 3, h - 12))
        bar.blit(txt, (11, 4))
        self.screen.blit(bar, (10, HEIGHT - h - 10))

    def _chrome_buttons(self) -> dict:
        # engrenagem, chat on/off, câmera on/off, pasta (tap abre)
        # com chat aberto recuam para a esquerda do painel (sem colisão)
        base_x = (CHAT_X - 44) if self.chat_visible else (WIDTH - 44)
        y = 44
        return {
            "settings": pygame.Rect(base_x, y, 32, 32),
            "chat": pygame.Rect(base_x - 40, y, 32, 32),
            "camera": pygame.Rect(base_x - 80, y, 32, 32),
            "folder": pygame.Rect(base_x - 120, y, 32, 32),
        }

    def _handle_chrome_click(self, mx: int, my: int) -> bool:
        for name, rect in self._chrome_buttons().items():
            if rect.collidepoint(mx, my):
                if name == "settings":
                    self.settings_open = not self.settings_open
                elif name == "chat":
                    self.chat_visible = not self.chat_visible
                    print("Chat " + ("visível" if self.chat_visible else "oculto (modo mic)"))
                elif name == "camera":
                    self.toggle_camera()
                elif name == "folder":
                    self.open_folder_gesture()
                return True
        if self.settings_open:
            row = self._settings_row_at(mx, my)
            if row:
                self._settings_activate(row)
                return True
            # Clique fora do painel fecha
            px, py, pw, ph = self._settings_geom()
            if not (px <= mx <= px + pw and py <= my <= py + ph):
                self.settings_open = False
                return True
        # Tag CAM clicável = retry/toggle
        if 8 <= mx <= 140 and HEIGHT - 38 <= my <= HEIGHT - 8:
            self.toggle_camera()
            return True
        return False

    def _settings_geom(self):
        w, h = 320, 282
        return (WIDTH - w - 16, 84, w, h)

    def _settings_rows(self):
        import os as _os
        speak = _os.getenv("ARIS_HUD_SPEAK", "1") == "1"
        voice = _os.getenv("ARIS_TTS_VOICE", "pt-BR-FranciscaNeural")
        return [
            ("voz", f"Voz HUD: {'ON' if speak else 'OFF'}"),
            ("voz_tts", f"Voz TTS: {voice.split('-')[-1]}"),
            ("camera", f"Câmera: {'ON' if self._camera_on() else 'OFF'} (cam {self.tracker.camera_index})"),
            ("espelho", f"Espelho: {'ON' if self.tracker.mirror else 'OFF'} (F)"),
            ("rotacao", f"Rotação: {self.tracker.rotation}° (V)"),
            ("trocar_cam", "Trocar câmera frontal/traseira (C)"),
            ("chat", f"Chat: {'ON' if self.chat_visible else 'OFF (mic)'}"),
        ]

    def _settings_row_at(self, mx: int, my: int):
        px, py, pw, ph = self._settings_geom()
        rows = self._settings_rows()
        for i, (key, _label) in enumerate(rows):
            ry = py + 44 + i * 32
            if px + 12 <= mx <= px + pw - 12 and ry <= my <= ry + 26:
                return key
        return None

    def _settings_activate(self, key: str) -> None:
        import os as _os
        if key == "voz":
            cur = _os.getenv("ARIS_HUD_SPEAK", "1") == "1"
            _os.environ["ARIS_HUD_SPEAK"] = "0" if cur else "1"
        elif key == "voz_tts":
            order = ["pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural", "pt-BR-AntonioNeural"]
            cur = _os.getenv("ARIS_TTS_VOICE", order[0])
            nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
            _os.environ["ARIS_TTS_VOICE"] = nxt
        elif key == "camera":
            self.toggle_camera()
        elif key == "espelho":
            self.tracker.mirror = not self.tracker.mirror
        elif key == "rotacao":
            self.tracker.rotation = (self.tracker.rotation + 90) % 360
        elif key == "trocar_cam":
            self.tracker.cycle_camera()
        elif key == "chat":
            self.chat_visible = not self.chat_visible

    def _draw_chrome_buttons(self):
        font = _font("Consolas", 16, bold=True)
        cam_on = self._camera_on()
        has_folder = bool(self.workspace.items)
        items = [
            ("camera", "C" if cam_on else "c", GREEN if cam_on else RED, cam_on),
            ("chat", "▭" if self.chat_visible else "—",
             CYAN if self.chat_visible else GRAY, self.chat_visible),
            ("folder", "▤", GREEN if has_folder else CYAN, has_folder),
            ("settings", "⚙", CYAN if self.settings_open else GRAY,
             self.settings_open),
        ]
        for name, glyph, color, active in items:
            rect = self._chrome_buttons()[name]
            bg = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            pygame.draw.rect(bg, (*PANEL_FILL, 212), (0, 0, rect.w, rect.h),
                             border_radius=9)
            pygame.draw.rect(bg, (*color, 235 if active else 130),
                             (0, 0, rect.w, rect.h), 2 if active else 1,
                             border_radius=9)
            if active:
                pygame.draw.rect(bg, (*color, 55), (3, 3, rect.w - 6, rect.h - 6),
                                 border_radius=7)
            self.screen.blit(bg, rect.topleft)
            txt = font.render(glyph, True, color)
            self.screen.blit(txt, txt.get_rect(center=rect.center))

    def _draw_settings(self):
        px, py, pw, ph = self._settings_geom()
        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(panel, (*PANEL_FILL, 242), (0, 0, pw, ph),
                         border_radius=10)
        pygame.draw.rect(panel, (*CYAN_DIM, 225), (0, 0, pw, ph), 1,
                         border_radius=10)
        font_t = _font("vt323", 17)
        panel.blit(font_t.render("CONFIG // ARIS", True, CYAN), (14, 8))
        pygame.draw.rect(panel, (*AMBER, 230), (14, 34, pw - 28, 2))
        font = _font("vt323", 15)
        for i, (_key, label) in enumerate(self._settings_rows()):
            ry = 44 + i * 32
            pygame.draw.rect(panel, (0, 120, 165, 32), (12, ry, pw - 24, 26),
                             border_radius=6)
            pygame.draw.rect(panel, (*CYAN_DIM, 95), (12, ry, pw - 24, 26), 1,
                             border_radius=6)
            panel.blit(font.render(label, True, WHITE), (20, ry + 4))
        self.screen.blit(panel, (px, py))

    def _draw_frame_chrome(self, has_camera: bool):
        # Moldura inset dupla
        self.screen.blit(self._frame_edge, (0, 0))
        # Cantos da tela (L maior, ciano vivo)
        corner = 34
        for x, y, dx, dy in [(6, 6, 1, 1), (WIDTH - 6, 6, -1, 1),
                             (6, HEIGHT - 6, 1, -1), (WIDTH - 6, HEIGHT - 6, -1, -1)]:
            pygame.draw.line(self.screen, CYAN, (x, y), (x + corner * dx, y), 2)
            pygame.draw.line(self.screen, CYAN, (x, y), (x, y + corner * dy), 2)


def main():
    hud = HUD()
    hud.run()


if __name__ == "__main__":
    main()

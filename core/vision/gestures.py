"""Hand Gesture Detection using MediaPipe Hands.

Leve (CPU-friendly) para detecção de landmarks de mão em tempo real.
4-5 gestos básicos: mão aberta, pinça, punho fechado, dois braços, corte.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

try:  # pragma: no cover - dependência opcional
    import cv2
    import mediapipe as mp
    import numpy as np
    HAS_MEDIAPIPE = True
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    mp = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    HAS_MEDIAPIPE = False

try:  # pragma: no cover
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

from core.vision.sources.camera_source import CameraSource


class GestureType(Enum):
    """Tipos de gestos suportados."""
    OPEN_HAND = "open_hand"        # Mão aberta = selecionar/focar
    PINCH = "pinch"                # Pinça = zoom in/out
    CLOSED_FIST = "closed_fist"    # Punho fechado = arrastar/mover
    TWO_HANDS_OPEN = "two_hands_open"  # Duas mãos abertas = maximizar
    CUT = "cut"                    # Gesto de corte = fechar/cortar
    UNKNOWN = "unknown"


@dataclass
class HandLandmarks:
    """Landmarks normalizados de uma mão (0-1)."""
    wrist: tuple[float, float]
    thumb_tip: tuple[float, float]
    index_tip: tuple[float, float]
    middle_tip: tuple[float, float]
    ring_tip: tuple[float, float]
    pinky_tip: tuple[float, float]
    thumb_ip: tuple[float, float]
    index_pip: tuple[float, float]
    middle_pip: tuple[float, float]
    ring_pip: tuple[float, float]
    pinky_pip: tuple[float, float]

    @property
    def finger_tips(self) -> list[tuple[float, float]]:
        return [self.thumb_tip, self.index_tip, self.middle_tip, self.ring_tip, self.pinky_tip]

    @property
    def finger_pips(self) -> list[tuple[float, float]]:
        return [self.thumb_ip, self.index_pip, self.middle_pip, self.ring_pip, self.pinky_pip]


@dataclass
class DetectedGesture:
    """Gesto detectado com metadados."""
    gesture: GestureType
    confidence: float
    hand_landmarks: Optional[HandLandmarks]
    hand_side: str  # "left" ou "right"
    timestamp: float = field(default_factory=time.time)



    field = lambda default_factory: None


class HandGestureRecognizer:
    """
    Detector de gestos de mão via MediaPipe Hands.

    Pipeline:
    1. Captura frame da câmera
    2. Processa com MediaPipe Hands (CPU - modelo leve)
    3. Extrai landmarks normalizados
    4. Classifica gesto baseado em geometria
    5. Dispara callback com gesto detectado

    Gestos:
    - Mão aberta: todos os dedos estendidos
    - Pinça: polegar e indicador próximos (< threshold)
    - Punho fechado: todos os dedos flexionados
    - Duas mãos: duas mãos abertas simultâneas
    - Corte: mão fechada movendo horizontalmente rápido
    """

    def __init__(
        self,
        camera: CameraSource,
        logger: Any = None,
        on_gesture: Optional[Callable[[DetectedGesture], None]] = None,
        min_detection_confidence: float = 0.7,
        min_tracking_confidence: float = 0.5,
        max_num_hands: int = 2,
    ) -> None:
        self._camera = camera
        self._logger = logger
        self._on_gesture = on_gesture
        self._max_num_hands = max_num_hands

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._hands = None
        self._mp_hands = None
        self._mp_drawing = None
        self._mp_drawing_styles = None

        self._last_gesture: Optional[DetectedGesture] = None
        self._last_cut_position: Optional[float] = None
        self._last_cut_time: float = 0.0

        # Thresholds para classificação
        self._pinch_threshold = 0.05  # distância normalizada polegar-indicador
        self._finger_extended_threshold = 0.02  # y_tip < y_pip para dedo estendido
        self._cut_speed_threshold = 0.3  # pixels normalizados por frame
        self._cut_cooldown = 0.5  # segundos entre gestos de corte

    @property
    def available(self) -> bool:
        return HAS_MEDIAPIPE and self._camera.is_available

    def start(self) -> bool:
        """Inicia detecção de gestos contínua."""
        if not self.available:
            self._log("warning", "MediaPipe não disponível ou câmera indisponível")
            return False
        if self._running:
            return True

        if not self._camera.is_capturing:
            if not self._camera.start_continuous_capture():
                self._log("warning", "Não foi possível iniciar captura contínua")
                return False

        self._init_mediapipe()
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._detection_loop, name="hand-gestures", daemon=True)
        self._thread.start()
        self._log("info", "Detecção de gestos de mão iniciada")
        return True

    def stop(self) -> None:
        """Para detecção de gestos."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._hands:
            self._hands.close()
            self._hands = None
        self._log("info", "Detecção de gestos parada")

    def _log(self, level: str, message: str) -> None:
        if self._logger:
            getattr(self._logger, level, print)(f"[VISION/GESTURES] {message}")

    def _init_mediapipe(self) -> None:
        """Inicializa MediaPipe Hands."""
        if mp is None:
            return

        self._mp_hands = mp.solutions.hands
        self._mp_drawing = mp.solutions.drawing_utils
        self._mp_drawing_styles = mp.solutions.drawing_styles

        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=self._max_num_hands,
            min_detection_confidence=self._min_detection_confidence,
            min_tracking_confidence=self._min_tracking_confidence,
            model_complexity=0,  # 0 = mais leve (CPU)
        )

    def _detection_loop(self) -> None:
        """Loop de detecção de gestos."""
        while self._running:
            try:
                frame = self._camera.get_latest_frame()
                if frame is None:
                    time.sleep(0.03)  # ~30 fps
                    continue

                # Converter para RGB (MediaPipe espera RGB)
                if np is not None:
                    frame_rgb = np.array(frame)
                else:
                    time.sleep(0.03)
                    continue

                # Processar
                results = self._hands.process(frame_rgb)

                if results.multi_hand_landmarks:
                    for hand_landmarks, handedness in zip(
                        results.multi_hand_landmarks,
                        results.multi_handedness,
                    ):
                        # Extrair lado da mão
                        hand_side = handedness.classification[0].label.lower()  # "left" ou "right"

                        # Normalizar landmarks
                        landmarks = self._normalize_landmarks(hand_landmarks)

                        # Classificar gesto
                        gesture = self._classify_gesture(landmarks, hand_side)

                        if gesture and gesture.gesture != GestureType.UNKNOWN:
                            # Evitar repetição do mesmo gesto muito rápido
                            if self._should_emit_gesture(gesture):
                                self._last_gesture = gesture
                                if self._on_gesture:
                                    try:
                                        self._on_gesture(gesture)
                                    except Exception as exc:
                                        self._log("warning", f"Erro no callback de gesto: {exc}")

                time.sleep(0.03)  # ~30 fps

            except Exception as exc:
                self._log("warning", f"Erro no loop de gestos: {exc}")
                time.sleep(0.1)

    def _normalize_landmarks(self, hand_landmarks) -> HandLandmarks:
        """Extrai landmarks chave normalizados (0-1)."""
        lm = hand_landmarks.landmark

        # MediaPipe usa coordenadas normalizadas (0-1) relativas à imagem
        def pt(idx: int) -> tuple[float, float]:
            p = lm[idx]
            return (p.x, p.y)

        return HandLandmarks(
            wrist=pt(0),
            thumb_tip=pt(4), thumb_ip=pt(3),
            index_tip=pt(8), index_pip=pt(6),
            middle_tip=pt(12), middle_pip=pt(10),
            ring_tip=pt(16), ring_pip=pt(14),
            pinky_tip=pt(20), pinky_pip=pt(18),
        )

    def _classify_gesture(self, landmarks: HandLandmarks, hand_side: str) -> Optional[DetectedGesture]:
        """Classifica gesto baseado em geometria dos landmarks."""
        # Verificar dedos estendidos
        fingers_extended = self._get_extended_fingers(landmarks)
        num_extended = sum(fingers_extended)

        # Distância polegar-indicador (pinça)
        pinch_dist = self._distance(landmarks.thumb_tip, landmarks.index_tip)

        # Posição horizontal do punho (para gesto de corte)
        wrist_x = landmarks.wrist[0]
        current_time = time.time()

        # Classificação
        if num_extended >= 4:
            # Mão aberta (4+ dedos estendidos)
            gesture_type = GestureType.OPEN_HAND
            confidence = 0.9

        elif pinch_dist < self._pinch_threshold and num_extended <= 1:
            # Pinça: polegar e indicador próximos, outros dedos fechados
            gesture_type = GestureType.PINCH
            confidence = 0.85

        elif num_extended == 0:
            # Punho fechado
            gesture_type = GestureType.CLOSED_FIST
            confidence = 0.8

        else:
            return None

        # Verificar duas mãos (requer lógica externa para contar mãos)
        # Aqui retornamos gesto de mão única

        # Verificar gesto de corte (movimento horizontal rápido do punho)
        if self._last_cut_position is not None:
            dx = abs(wrist_x - self._last_cut_position)
            dt = current_time - self._last_cut_time
            if dt > 0 and dx / dt > self._cut_speed_threshold and dt > self._cut_cooldown:
                self._last_cut_time = current_time
                self._last_cut_position = wrist_x
                return DetectedGesture(
                    gesture=GestureType.CUT,
                    confidence=0.7,
                    hand_landmarks=landmarks,
                    hand_side=hand_side,
                )

        self._last_cut_position = wrist_x

        return DetectedGesture(
            gesture=gesture_type,
            confidence=confidence,
            hand_landmarks=landmarks,
            hand_side=hand_side,
        )

    def _get_extended_fingers(self, landmarks: HandLandmarks) -> list[bool]:
        """Retorna lista de quais dedos estão estendidos."""
        extended = []

        # Polegar: comparar x do tip com x do IP (depende da mão)
        # Para simplificar: usar y do tip vs IP para todos
        extended.append(landmarks.thumb_tip[1] < landmarks.thumb_ip[1])
        extended.append(landmarks.index_tip[1] < landmarks.index_pip[1])
        extended.append(landmarks.middle_tip[1] < landmarks.middle_pip[1])
        extended.append(landmarks.ring_tip[1] < landmarks.ring_pip[1])
        extended.append(landmarks.pinky_tip[1] < landmarks.pinky_pip[1])

        return extended

    def _distance(self, p1: tuple[float, float], p2: tuple[float, float]) -> float:
        """Distância euclidiana normalizada."""
        if np is None:
            return 1.0
        return float(np.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2))

    def _should_emit_gesture(self, gesture: DetectedGesture) -> bool:
        """Evita emitir o mesmo gesto repetidamente em intervalo curto."""
        if self._last_gesture is None:
            return True
        if gesture.gesture != self._last_gesture.gesture:
            return True
        # Mesmo gesto: só emite se mudou de mão ou passou tempo suficiente
        if gesture.hand_side != self._last_gesture.hand_side:
            return True
        return (gesture.timestamp - self._last_gesture.timestamp) > 1.0
"""Face Recognition module for A.R.I.S.

Leve (HOG + dlib) para CPU, integração com Knowledge Graph,
consentimento explícito para rostos desconhecidos.
"""

from __future__ import annotations

import base64
import threading
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

try:  # pragma: no cover - dependência opcional
    import face_recognition
    import numpy as np
    HAS_FACE_RECOGNITION = True
except Exception:  # pragma: no cover
    face_recognition = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    HAS_FACE_RECOGNITION = False

try:  # pragma: no cover
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

from core.vision.sources.camera_source import CameraSource

try:
    from core.neural.events import Event, PRIORITY_HIGH, EVENT_VISION_FACE_DETECTED, EVENT_VISION_FACE_RECOGNIZED
except Exception:
    Event = None  # type: ignore[assignment]
    PRIORITY_HIGH = 50  # type: ignore[assignment]
    EVENT_VISION_FACE_DETECTED = "vision.face_detected"
    EVENT_VISION_FACE_RECOGNIZED = "vision.face_recognized"


@dataclass
class FaceIdentity:
    """Identidade de uma face reconhecida."""
    entity_id: str
    name: str
    confidence: float
    encoding: list[float] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    known: bool = True


class FaceRecognizer:
    """
    Reconhecimento facial leve (HOG) com integração ao Knowledge Graph.

    Fluxo:
    1. Captura frame da câmera
    2. Detecta rostos (HOG - rápido em CPU)
    3. Gera embeddings (128-dim)
    4. Compara com rostos conhecidos no KG
    5. Se desconhecido: dispara consentimento via callback
    6. Se conhecido: atualiza entidade no KG
    """

    TOLERANCE = 0.5  # Menor = mais estrito
    MIN_FACE_SIZE = 50  # pixels
    EMBEDDING_DIM = 128

    def __init__(
        self,
        camera: CameraSource,
        kg_client: Any = None,
        logger: Any = None,
        event_bus: Any = None,
        on_unknown_face: Optional[Callable[[Image.Image, list[float]], str | None]] = None,
        known_faces_path: str = "data/known_faces",
    ) -> None:
        self._camera = camera
        self._kg = kg_client
        self._logger = logger
        self._bus = event_bus
        self._on_unknown_face = on_unknown_face
        self._known_faces_path = Path(known_faces_path)
        self._known_faces_path.mkdir(parents=True, exist_ok=True)

        self._known_encodings: list[list[float]] = []
        self._known_names: list[str] = []
        self._known_entity_ids: list[str] = []

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Cache de identidades atuais no frame
        self._current_identities: list[FaceIdentity] = []

    @property
    def available(self) -> bool:
        return HAS_FACE_RECOGNITION and self._camera.is_available

    def start(self) -> bool:
        """Inicia reconhecimento contínuo (requer câmera já capturando)."""
        if not self.available:
            self._log("warning", "face_recognition indisponível ou câmera não disponível")
            return False
        if self._running:
            return True

        if not self._camera.is_capturing:
            if not self._camera.start_continuous_capture():
                self._log("warning", "Não foi possível iniciar captura contínua da câmera")
                return False

        self._load_known_faces()
        self._running = True
        self._thread = threading.Thread(target=self._recognition_loop, name="face-recognition", daemon=True)
        self._thread.start()
        self._log("info", "Reconhecimento facial iniciado")
        return True

    def stop(self) -> None:
        """Para o reconhecimento."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._log("info", "Reconhecimento facial parado")

    def _log(self, level: str, message: str) -> None:
        if self._logger:
            getattr(self._logger, level, print)(f"[VISION/FACE] {message}")

    def _load_known_faces(self) -> None:
        """Carrega rostos conhecidos do Knowledge Graph e cache local."""
        if self._kg is None:
            self._log("info", "KG não disponível - carregando apenas cache local")
            self._load_local_cache()
            return

        try:
            # Buscar entidades do tipo 'person' no KG
            results = self._kg.search("type:person", limit=100)
            for entity in results:
                entity_id = entity.get("id", "")
                name = entity.get("title", entity.get("name", ""))
                if not name or not entity_id:
                    continue

                # Tentar carregar encoding do cache local
                encoding_path = self._known_faces_path / f"{entity_id}.npy"
                if encoding_path.exists() and np is not None:
                    try:
                        encoding = np.load(encoding_path).tolist()
                        self._known_encodings.append(encoding)
                        self._known_names.append(name)
                        self._known_entity_ids.append(entity_id)
                    except Exception:
                        pass

            self._log("info", f"Rostos conhecidos carregados: {len(self._known_names)}")
        except Exception as exc:
            self._log("warning", f"Falha ao carregar rostos do KG: {exc}")
            self._load_local_cache()

    def _load_local_cache(self) -> None:
        """Fallback: carrega apenas arquivos .npy locais."""
        if np is None:
            return
        for npy_file in self._known_faces_path.glob("*.npy"):
            try:
                encoding = np.load(npy_file).tolist()
                name = npy_file.stem
                self._known_encodings.append(encoding)
                self._known_names.append(name)
                self._known_entity_ids.append(name)
            except Exception:
                pass
        self._log("info", f"Cache local: {len(self._known_names)} rostos")

    def _save_face_encoding(self, entity_id: str, encoding: list[float]) -> bool:
        """Salva encoding no cache local."""
        if np is None:
            return False
        try:
            path = self._known_faces_path / f"{entity_id}.npy"
            np.save(path, np.array(encoding))
            return True
        except Exception:
            return False

    def _recognition_loop(self) -> None:
        """Loop de reconhecimento facial contínuo."""
        while self._running:
            try:
                frame = self._camera.get_latest_frame()
                if frame is None:
                    time.sleep(0.1)
                    continue

                identities = self._process_frame(frame)
                
                # Publica evento de rostos detectados se houver
                if identities and self._bus:
                    try:
                        from core.neural.events import Event, PRIORITY_LOW
                        for ident in identities:
                            self._bus.publish(Event(
                                event_type=EVENT_VISION_FACE_DETECTED,
                                source="vision",
                                priority=PRIORITY_LOW,
                                confidence=ident.confidence,
                                payload={
                                    "name": ident.name,
                                    "entity_id": ident.entity_id,
                                    "confidence": ident.confidence,
                                    "known": ident.known,
                                },
                            ))
                    except Exception:
                        pass

                with self._lock:
                    self._current_identities = identities

            except Exception as exc:
                self._log("warning", f"Erro no loop de reconhecimento: {exc}")

            time.sleep(0.5)  # 2 fps para reconhecimento (mais leve que captura)

    def _process_frame(self, image: Image.Image) -> list[FaceIdentity]:
        """Processa um frame e retorna identidades reconhecidas."""
        if not HAS_FACE_RECOGNITION or np is None:
            return []

        # Converter PIL para numpy (RGB)
        try:
            frame_rgb = np.array(image)
        except Exception:
            return []

        # Detectar localizações de rosto (modelo HOG - rápido CPU)
        try:
            face_locations = face_recognition.face_locations(
                frame_rgb,
                model="hog",  # HOG é ~10x mais rápido que CNN em CPU
                number_of_times_to_upsample=1,
            )
        except Exception:
            return []

        if not face_locations:
            return []

        # Gerar encodings para cada rosto
        try:
            face_encodings = face_recognition.face_encodings(
                frame_rgb,
                known_face_locations=face_locations,
                num_jitters=1,  # 1 = mais rápido, menos preciso
            )
        except Exception:
            return []

        identities = []
        for (top, right, bottom, left), encoding in zip(face_locations, face_encodings):
            # Filtrar rostos muito pequenos
            face_width = right - left
            face_height = bottom - top
            if face_width < self.MIN_FACE_SIZE or face_height < self.MIN_FACE_SIZE:
                continue

            identity = self._match_or_register_face(encoding, frame_rgb, (top, right, bottom, left))
            if identity:
                identities.append(identity)

        return identities

    def _match_or_register_face(
        self,
        encoding: list[float],
        frame_rgb: "np.ndarray",
        location: tuple[int, int, int, int],
    ) -> Optional[FaceIdentity]:
        """Compara com rostos conhecidos ou registra novo com consentimento."""
        if not self._known_encodings:
            # Nenhum rosto conhecido - sempre pede consentimento
            return self._handle_unknown_face(encoding, frame_rgb, location)

        # Comparar com conhecidos
        distances = face_recognition.face_distance(self._known_encodings, encoding)
        best_idx = int(np.argmin(distances))
        best_distance = float(distances[best_idx])

        if best_distance <= self.TOLERANCE:
            # Rosto conhecido
            name = self._known_names[best_idx]
            entity_id = self._known_entity_ids[best_idx]

            # Atualizar KG com último avistamento
            if self._kg:
                try:
                    self._kg.store(
                        content=f"Pessoa {name} vista em {time.strftime('%Y-%m-%d %H:%M:%S')}",
                        node_type="observation",
                        tags=["face_recognition", "person", name.lower()],
                    )
                except Exception:
                    pass

            # Publica evento de rosto reconhecido
            if self._bus:
                try:
                    from core.neural.events import Event, PRIORITY_LOW
                    self._bus.publish(Event(
                        event_type=EVENT_VISION_FACE_RECOGNIZED,
                        source="vision",
                        priority=PRIORITY_LOW,
                        confidence=1.0 - best_distance,
                        payload={
                            "name": name,
                            "entity_id": entity_id,
                            "confidence": 1.0 - best_distance,
                        },
                    ))
                except Exception:
                    pass

            return FaceIdentity(
                entity_id=entity_id,
                name=name,
                confidence=1.0 - best_distance,
                encoding=encoding,
                known=True,
            )

        # Rosto desconhecido - pedir consentimento
        return self._handle_unknown_face(encoding, frame_rgb, location)

    def _handle_unknown_face(
        self,
        encoding: list[float],
        frame_rgb: "np.ndarray",
        location: tuple[int, int, int, int],
    ) -> Optional[FaceIdentity]:
        """Lida com rosto desconhecido: dispara callback de consentimento."""
        if self._on_unknown_face is None:
            self._log("info", "Rosto desconhecido detectado - sem callback de consentimento")
            return FaceIdentity(
                entity_id="unknown",
                name="Desconhecido",
                confidence=0.0,
                encoding=encoding,
                known=False,
            )

        try:
            # Callback deve retornar o nome se consentiu, None se não
            name = self._on_unknown_face(
                Image.fromarray(frame_rgb) if Image else None,
                encoding,
            )
        except Exception as exc:
            self._log("warning", f"Erro no callback de consentimento: {exc}")
            name = None

        if name:
            # Consentimento dado - salvar como conhecido
            entity_id = f"person_{name.lower().replace(' ', '_')}"
            self._known_encodings.append(encoding)
            self._known_names.append(name)
            self._known_entity_ids.append(entity_id)

            # Salvar no cache local
            self._save_face_encoding(entity_id, encoding)

            # Registrar no KG
            if self._kg:
                try:
                    self._kg.store(
                        content=f"Nova pessoa conhecida: {name}",
                        node_type="person",
                        tags=["face_recognition", "known_person", name.lower()],
                    )
                except Exception:
                    pass

            self._log("info", f"Novo rosto registrado com consentimento: {name}")
            return FaceIdentity(
                entity_id=entity_id,
                name=name,
                confidence=0.8,
                encoding=encoding,
                known=True,
            )

        return FaceIdentity(
            entity_id="unknown",
            name="Desconhecido",
            confidence=0.0,
            encoding=encoding,
            known=False,
        )

    def get_current_identities(self) -> list[FaceIdentity]:
        """Retorna identidades do frame mais recente (thread-safe)."""
        with self._lock:
            return list(self._current_identities)

    def get_known_people(self) -> list[dict[str, Any]]:
        """Lista pessoas conhecidas."""
        return [
            {"entity_id": eid, "name": name}
            for eid, name in zip(self._known_entity_ids, self._known_names)
        ]
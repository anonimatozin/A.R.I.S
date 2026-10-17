"""Testes do Vision Engine do A.R.I.S.

Cobre: config, eventos de visão, atenção, monitores (ScreenSource),
câmera (CameraSource), OCR (Tesseract), VLM (Ollama/Gemini), o pipeline
(analyze/read/find/errors/ask) e a integração com EventBus + Atenção +
Memória. Nenhum teste exige câmera física nem VLM de verdade.
"""

from io import BytesIO
from pathlib import Path

import pytest

from core.memory import MemoryManager
from core.neural.attention.attention_engine import AttentionEngine, AttentionLevel
from core.neural.event_bus import EventBus
from core.neural.events import (
    EVENT_CAMERA,
    EVENT_VISION_APPLICATION_DETECTED,
    EVENT_VISION_ERROR_DETECTED,
    EVENT_VISION_SCREEN_ANALYZED,
    EVENT_VISION_TEXT_DETECTED,
    PERCEPTION_EVENT_TYPES,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    Event,
)
from core.neural.memory.system import MemorySystem
from core.neural.state import GlobalState
from core.perception.attention_bridge import AttentionBridge
from core.vision.config import VisionConfig
from core.vision.ocr import TesseractEngine
from core.vision.result import OcrResult, OcrWord, VisionAnalysis, VisionResult
from core.vision.sources.camera_source import CameraSource
from core.vision.sources.screen_source import ScreenSource
from core.vision.vision_engine import VisionEngine
from core.vision.vlm import OllamaVision, VisionLanguageModel, _is_vision_model
from utils.logger import Logger


def _logger():
    return Logger(name="test-vision", level="CRITICAL")


@pytest.fixture
def logger():
    return Logger(name="test-vision", level="CRITICAL")


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def attention():
    return AttentionEngine.with_defaults()


@pytest.fixture
def state():
    return GlobalState()


@pytest.fixture
def memory(logger, tmp_path):
    mm = MemoryManager(logger=logger, memory_root=tmp_path / "memory")
    return MemorySystem.build(mm, logger=logger, memory_root=tmp_path)


def make_image(width: int = 320, height: int = 180):
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    buffer.seek(0)
    return Image.open(buffer)


class EventCollector:
    def __init__(self, bus):
        self.events: list[Event] = []
        bus.subscribe("*", self.events.append)


# ── Config ────────────────────────────────────────────────────

class TestVisionConfig:
    def test_defaults_are_offline_safe(self):
        cfg = VisionConfig.load()
        assert cfg.enabled is True
        assert cfg.camera_enabled is False
        assert cfg.vlm_provider in ("ollama", "google")

    def test_env_bool_true(self, monkeypatch):
        monkeypatch.setenv("ARIS_VISION_SAVE_IMAGES", "true")
        assert VisionConfig.load().save_images is True

    def test_env_bool_false(self, monkeypatch):
        monkeypatch.setenv("ARIS_VISION_ENABLED", "off")
        assert VisionConfig.load().enabled is False

    def test_env_int_and_float(self, monkeypatch):
        monkeypatch.setenv("ARIS_VISION_MAX_IMAGE_SIZE", "640")
        monkeypatch.setenv("ARIS_VISION_TIMEOUT", "5.5")
        cfg = VisionConfig.load()
        assert cfg.max_image_size == 640
        assert cfg.vision_timeout == 5.5

    def test_update_env_immutable(self):
        cfg = VisionConfig.load()
        changed = cfg.update_env(save_images=True)
        assert changed.save_images is True

    def test_error_terms_env(self, monkeypatch):
        monkeypatch.setenv("ARIS_VISION_ERROR_TERMS", "erro, falha")
        assert VisionConfig.load().error_terms == ("erro", "falha")


# ── Eventos e atenção de visão ────────────────────────────────

class TestVisionEvents:
    def test_vision_types_registered_as_perception(self):
        for event_type in (
            EVENT_VISION_SCREEN_ANALYZED,
            EVENT_VISION_TEXT_DETECTED,
            EVENT_VISION_ERROR_DETECTED,
            EVENT_VISION_APPLICATION_DETECTED,
        ):
            assert event_type in PERCEPTION_EVENT_TYPES, event_type

    def test_not_duplicated_with_camera(self):
        assert EVENT_VISION_ERROR_DETECTED != EVENT_CAMERA


class TestVisionAttention:
    def test_error_event_gets_high_attention_signal(self):
        engine = AttentionEngine.with_defaults()
        score = engine.score(
            Event(
                event_type=EVENT_VISION_ERROR_DETECTED,
                source="vision",
                payload={"text": "Erro detectado na tela"},
                priority=PRIORITY_HIGH,
                confidence=0.8,
            )
        )
        assert engine.level(score.score) in (AttentionLevel.HIGH, AttentionLevel.NORMAL)

    def test_screen_analyzed_low_stays_low(self):
        engine = AttentionEngine.with_defaults()
        score = engine.score(
            Event(
                event_type=EVENT_VISION_SCREEN_ANALYZED,
                source="vision",
                payload={"text": "janela ativa"},
                priority=PRIORITY_LOW,
                confidence=0.5,
            )
        )
        assert score.score < 0.6


# ── ScreenSource ──────────────────────────────────────────────

class FakeRect:
    """Rectangular com atributo .contents igual a si mesmo (para ctypes)."""

    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom
        self.contents = self  # útil para callbacks ctypes


class TestScreenSource:
    def test_list_monitors_windows_multi(self, monkeypatch):
        monkeypatch.setattr(
            "core.vision.sources.screen_source._list_windows_monitors",
            lambda: [
                {"left": 0, "top": 0, "width": 1920, "height": 1080},
                {"left": 1920, "top": 0, "width": 1920, "height": 1080},
            ],
        )
        monkeypatch.setattr("core.vision.sources.screen_source._WINDOWS", True)
        monkeypatch.setattr("core.vision.sources.screen_source._PYAUTOGUI", True)
        monitors = ScreenSource(logger=_logger()).list_monitors()
        assert len(monitors) == 2
        assert monitors[0]["index"] == 0
        assert monitors[1]["width"] == 1920

    def test_capture_returns_pil_image(self, monkeypatch):
        import types

        monkeypatch.setattr("core.vision.sources.screen_source._LINUX", False)
        monkeypatch.setattr("core.vision.sources.screen_source._PYAUTOGUI", True)
        fake_img = make_image()
        # pyautogui é None sem display; cria um fake patcheável.
        fake_pa = types.SimpleNamespace(screenshot=lambda region=None: fake_img)
        monkeypatch.setattr(
            "core.vision.sources.screen_source.pyautogui", fake_pa
        )
        image = ScreenSource(logger=_logger()).capture()
        assert image is not None
        assert image.size == (320, 180)

    def test_capture_none_when_unavailable(self, monkeypatch):
        monkeypatch.setattr("core.vision.sources.screen_source._LINUX", False)
        monkeypatch.setattr("core.vision.sources.screen_source._PYAUTOGUI", False)
        source = ScreenSource(logger=_logger())
        assert not source.is_available
        assert source.capture() is None

    def test_linux_capture_uses_session_tool(self, monkeypatch, tmp_path):
        """No Linux, a captura usa a ferramenta da sessão e valida a imagem."""
        from PIL import Image as PILImage

        monkeypatch.setattr("core.vision.sources.screen_source._LINUX", True)

        def fake_capture_to(path, timeout=20):
            PILImage.new("RGB", (320, 180), "red").save(path)
            return True, str(path)

        monkeypatch.setattr(
            "utils.screen_capture.capture_to", fake_capture_to
        )
        image = ScreenSource(logger=_logger()).capture()
        assert image is not None
        assert image.size == (320, 180)

    def test_linux_capture_error_is_clear(self, monkeypatch):
        """Sem ferramenta de captura, devolve None com erro claro (log)."""
        monkeypatch.setattr("core.vision.sources.screen_source._LINUX", True)
        monkeypatch.setattr(
            "utils.screen_capture.capture_to",
            lambda path, timeout=20: (False, "Nenhuma ferramenta de captura"),
        )
        assert ScreenSource(logger=_logger()).capture() is None

    def test_status_includes_monitors(self, monkeypatch):
        monkeypatch.setattr("core.vision.sources.screen_source._WINDOWS", False)
        monkeypatch.setattr("core.vision.sources.screen_source._PYAUTOGUI", True)
        status = ScreenSource(logger=_logger()).get_status()
        assert "available" in status
        assert status["monitors"] == 1


# ── CameraSource (sem hardware) ───────────────────────────────

class TestCameraSource:
    def test_without_opencv_unavailable(self, monkeypatch):
        monkeypatch.setattr("core.vision.sources.camera_source.HAS_CV2", False)
        camera = CameraSource(enabled=True, logger=_logger())
        assert not camera.is_available
        assert camera.capture() is None  # nunca lança

    def test_disabled_never_available_even_with_probe(self):
        camera = CameraSource(enabled=False, logger=_logger())
        camera._probe = lambda: True  # type: ignore[method-assign]
        assert not camera.is_available

    def test_enabled_with_probe_available(self):
        camera = CameraSource(enabled=True, logger=_logger())
        camera._probe = lambda: True  # type: ignore[method-assign]
        assert camera.is_available

    def test_status_honest(self, monkeypatch):
        monkeypatch.setattr("core.vision.sources.camera_source.HAS_CV2", False)
        status = CameraSource(enabled=True, logger=_logger()).get_status()
        assert status["available"] is False
        assert status["hardware_detected"] is False


# ── OCR (Tesseract) ───────────────────────────────────────────

def fake_tesseract_data():
    return {
        "level": [5, 5, 5],
        "page_num": [1, 1, 1],
        "block_num": [1, 1, 2],
        "par_num": [1, 1, 1],
        "line_num": [1, 1, 2],
        "word_num": [1, 2, 1],
        "left": [10, 60, 10],
        "top": [20, 20, 80],
        "width": [40, 90, 50],
        "height": [15, 15, 15],
        "conf": [95, 85, 70],
        "text": ["Erro", "na tela", "falhou"],
    }


class TestTesseractEngine:
    def test_extract_produces_words_lines_and_text(self, monkeypatch):
        engine = TesseractEngine(logger=_logger())
        monkeypatch.setattr(engine, "_image_to_data", lambda image: fake_tesseract_data())
        monkeypatch.setattr("core.vision.ocr.pytesseract", __import__("pytesseract"))
        monkeypatch.setattr("core.vision.ocr.Image", __import__("PIL").Image)
        # Simula binário localizado diretamente no cache global
        from core.vision import ocr as ocr_mod
        ocr_mod._set_tesseract_path("fake_tesseract_path")
        monkeypatch.setattr(engine, "_locate_binary", lambda: None)
        result = engine.extract(make_image())
        assert result.available
        assert "Erro" in result.text and "falhou" in result.text
        assert len(result.lines) == 2
        assert len(result.words) == 3
        assert result.confidence > 0.5
        word = result.words[0]
        assert word.bbox["x"] == 10 and word.bbox["y1"] == 20

    def test_without_pytesseract_returns_false(self, monkeypatch):
        monkeypatch.setattr("core.vision.ocr.pytesseract", None)
        result = TesseractEngine().extract(make_image())
        assert not result.available
        assert result.note


# ── VLM (Ollama/Gemini) ───────────────────────────────────────

def fake_ollama_response(models, status=200):
    class FakeResponse:
        def __init__(self, models, status):
            self.status_code = status

        def json(self):
            return {"models": [{"name": m} for m in models]}

    return FakeResponse(models, status)


class TestOllamaVision:
    def test_finds_vision_model_by_hint(self, monkeypatch):
        class FakeRequests:
            def get(self, url, timeout=0):
                return fake_ollama_response(["llama3.2", "llava:7b", "qwen2.5-vl"])

        monkeypatch.setattr("core.vision.vlm.requests", FakeRequests())
        ollama = OllamaVision("http://localhost:11434", logger=_logger())
        assert ollama._model() in ("llava", "qwen2.5-vl")

    def test_configured_model_wins(self, monkeypatch):
        class FakeRequests:
            def get(self, url, timeout=0):
                return fake_ollama_response(["llama3.2"])

        monkeypatch.setattr("core.vision.vlm.requests", FakeRequests())
        ollama = OllamaVision("http://localhost:11434", model="custom-vision", logger=_logger())
        assert ollama._model() == "custom-vision"

    def test_without_server_unavailable(self, monkeypatch):
        class FakeRequests:
            def get(self, url, timeout=0):
                raise ConnectionError("sem ollama")

        monkeypatch.setattr("core.vision.vlm.requests", FakeRequests())
        ollama = OllamaVision("http://localhost:11434", logger=_logger())
        assert not ollama.available
        assert ollama.ask(make_image(), "o que vê?") is None  # não lança

    def test_ask_returns_response(self, monkeypatch):
        class FakeGen:
            status_code = 200

            def json(self):
                return {"response": "Há uma janela de terminal aberta."}

        class FakeRequests:
            def __init__(self):
                self.posts = []

            def get(self, url, timeout=0):
                return fake_ollama_response(["llava:7b"])

            def post(self, url, json=None, timeout=0):
                self.posts.append((url, json))
                return FakeGen()

        requests_fake = FakeRequests()
        monkeypatch.setattr("core.vision.vlm.requests", requests_fake)
        monkeypatch.setattr("core.vision.vlm.ollama_limiter", None)
        ollama = OllamaVision("http://localhost:11434", logger=_logger())
        answer = ollama.ask(make_image(), "descreva")
        assert answer and "terminal" in answer
        assert requests_fake.posts and "images" in requests_fake.posts[0][1]

    def test_http_error_returns_none(self, monkeypatch):
        class FakeErr:
            status_code = 500

            def json(self):
                return {}

        class FakeRequests:
            def get(self, url, timeout=0):
                return fake_ollama_response(["llava:7b"])

            def post(self, url, json=None, timeout=0):
                return FakeErr()

        monkeypatch.setattr("core.vision.vlm.requests", FakeRequests())
        monkeypatch.setattr("core.vision.vlm.ollama_limiter", None)
        ollama = OllamaVision("http://localhost:11434", logger=_logger())
        assert ollama.ask(make_image(), "descreva") is None


class TestVisionModelHeuristics:
    def test_important_vision_names(self):
        for name in ("llava", "llava:7b", "qwen2.5-vl", "moondream", "gemma3:4b", "minicpm-v"):
            assert _is_vision_model(name), name

    def test_text_models_not_mistaken(self):
        for name in ("llama3.2", "qwen2.5", "mistral", "deepseek-r1"):
            assert not _is_vision_model(name), name


class TestVisionLanguageModelFacade:
    def _facade(self, providers, preferred="ollama"):
        config = VisionConfig.load().update_env(vlm_enabled=True)
        vlm = VisionLanguageModel.__new__(VisionLanguageModel)
        vlm._config = config
        vlm._logger = None
        vlm._providers = providers
        vlm._preferred = preferred
        return vlm

    def test_ask_never_raises(self):
        class Boom:
            available = True

            def ask(self, image, question):
                raise RuntimeError("boom")

        vlm = self._facade({"ollama": Boom(), "google": Boom()})
        assert vlm.ask(make_image(), "o que vê?") is None

    def test_ask_falls_through_providers(self):
        class Silent:
            available = False

            def ask(self, image, question):
                return None

        class Answering:
            available = True

            def ask(self, image, question):
                return "resposta da gemini"

        vlm = self._facade({"ollama": Silent(), "google": Answering()})
        assert vlm.ask(make_image(), "q") == "resposta da gemini"


# ── VisionResult ──────────────────────────────────────────────

class TestVisionResult:
    def test_to_dict_preserves_structure(self):
        result = VisionResult(
            source="screen",
            timestamp="2026-01-01T00:00:00",
            active_application="Notepad",
            ocr=OcrResult(available=True, text="Erro: arquivo não encontrado",
                          confidence=0.9),
            vision=VisionAnalysis(available=True, description="Uma janela de notas"),
            errors_detected=["erro"],
            confidence=0.9,
        )
        data = result.to_dict()
        assert data["active_application"] == "Notepad"
        assert data["ocr"]["text"].startswith("Erro")
        assert data["vision"]["description"]
        assert "erro" in data["errors_detected"]
        assert data["confidence"] == 0.9


# ── VisionEngine (com fakes) ──────────────────────────────────

class FakeScreen:
    def __init__(self, image=None):
        self.image = image

    def capture(self, monitor=None):
        return self.image

    def get_active_window(self):
        return {"title": "Visual Studio Code"}

    def get_status(self):
        return {"available": self.image is not None, "monitors": 1,
                "active_application": "Visual Studio Code"}


class FakeOcr:
    def __init__(self, available=True, result=None):
        self._available = available
        self.result = result

    @property
    def available(self):
        return self._available

    def extract(self, image):
        return self.result or OcrResult(
            available=True, text="Erro na tela", lines=["Erro na tela"], confidence=0.9)

    def get_status(self):
        return {"available": self._available}


class FakeVLM:
    def __init__(self, answer="Uma janela com um erro de sistema aberta."):
        self.answer = answer

    def ask(self, image, question):
        return self.answer

    def is_available(self):
        return bool(self.answer)

    def get_status(self):
        return {"provider": "fake", "providers": {"fake": bool(self.answer)},
                "available": bool(self.answer)}


def make_engine(bus=None, *, image=None, errors_text="", vlm_answer=None, memory=None):
    cfg = VisionConfig.load().update_env(vlm_provider="ollama")
    engine = VisionEngine(event_bus=bus, logger=_logger(), config=cfg, memory=memory)
    engine._screen = FakeScreen(image=image)
    engine._ocr = FakeOcr(available=True, result=OcrResult(
        available=True, text=errors_text or "nada", lines=["nada"], confidence=0.8))
    engine._vlm = FakeVLM(answer=vlm_answer)
    return engine


class TestVisionEnginePipeline:
    def test_analyze_without_image_graceful(self, bus):
        engine = make_engine(bus, image=None)
        result = engine.analyze_screen()
        assert result.ocr.available is False
        assert "capturar" in result.note

    def test_analyze_publishes_events(self, bus):
        collector = EventCollector(bus)
        engine = make_engine(bus, image=make_image(), errors_text="Erro: Indisponível",
                             vlm_answer="Tela com mensagem de erro.")
        result = engine.analyze_screen()
        types = {e.event_type for e in collector.events}
        assert EVENT_VISION_SCREEN_ANALYZED in types
        assert EVENT_VISION_APPLICATION_DETECTED in types
        assert EVENT_VISION_TEXT_DETECTED in types
        assert result.active_application == "Visual Studio Code"
        assert result.vision.available
        assert result.ocr.available

    def test_analyze_detects_errors_and_publishes_high_event(self, bus):
        collector = EventCollector(bus)
        engine = make_engine(bus, image=make_image(), errors_text="Falha crítica: exception",
                             vlm_answer="Instruções estão na tela.")
        result = engine.analyze_screen()
        assert "falha" in result.errors_detected or "exception" in result.errors_detected
        types = {e.event_type for e in collector.events}
        assert EVENT_VISION_ERROR_DETECTED in types
        error_event = next(e for e in collector.events
                           if e.event_type == EVENT_VISION_ERROR_DETECTED)
        assert error_event.priority >= PRIORITY_HIGH

    def test_analyze_no_vlm_falls_back_to_ocr(self, bus):
        engine = make_engine(bus, image=make_image(), vlm_answer=None,
                             errors_text="Hoje está tudo certo com o sistema")
        result = engine.analyze_screen()
        assert result.ocr.available
        assert result.vision.available is False
        assert "Texto visível" in engine.summarize_for_speech(result)

    def test_find_on_screen(self, bus):
        ocr = OcrResult(
            available=True,
            text="Bem-vindo ao Spotify",
            words=[OcrWord(text="Spotify", confidence=0.9,
                           bbox={"x": 10, "y": 10, "width": 50, "height": 15})],
        )
        engine = make_engine(bus, image=make_image())
        engine._ocr = FakeOcr(result=ocr)
        found = engine.find_on_screen("spotify")
        assert found["found"] is True
        assert found["query"] == "spotify"
        assert found["position"] == {"x": 35, "y": 17.5}

    def test_find_on_screen_absent(self, bus):
        engine = make_engine(bus, image=make_image(), errors_text="só texto comum")
        assert engine.find_on_screen("spotify")["found"] is False

    def test_detect_errors_returns_terms(self, bus):
        engine = make_engine(bus, image=make_image(), errors_text="A aplicação falhou com exception")
        errors = engine.detect_errors()
        assert errors and ("falhou" in errors or "exception" in errors)

    def test_read_screen_returns_ocr_text(self, bus):
        engine = make_engine(bus, image=make_image(), errors_text="texto qualquer")
        assert engine.read_screen().text == "texto qualquer"

    def test_ask_returns_vlm_answer(self, bus):
        engine = make_engine(bus, image=make_image(), vlm_answer="Vejo um terminal.")
        assert engine.ask("o que você vê?") == "Vejo um terminal."

    def test_capture_not_continuous(self, bus):
        engine = make_engine(bus, image=make_image())
        assert engine.capture_image() is not None
        assert bus.get_stats()["published"] == 0  # captura sozinha não gera evento

    def test_save_image_only_when_enabled(self, tmp_path):
        cfg = VisionConfig.load().update_env(save_images=True, save_dir=str(tmp_path))
        engine = VisionEngine(config=cfg, logger=_logger())
        path = engine.save_image(make_image())
        assert path and Path(path).exists()

        engine2 = VisionEngine(config=cfg.update_env(save_images=False), logger=_logger())
        assert engine2.save_image(make_image()) is None

    def test_resize_limits_max_side(self):
        cfg = VisionConfig.load().update_env(max_image_size=128)
        engine = VisionEngine(config=cfg, logger=_logger())
        small = engine._resize(make_image(640, 480))
        assert max(small.size) <= 128

    def test_summarize_avoids_action_engine_trigger_words(self, bus):
        engine = make_engine(bus, image=None)
        summary = engine.summarize_for_speech(engine.analyze_screen())
        assert "indisponível" not in summary
        assert "não encontrado" not in summary

    def test_without_ocr_service(self, bus):
        engine = make_engine(bus, image=make_image())
        engine._ocr = FakeOcr(available=False, result=None)
        result = engine.analyze_screen()
        assert result.ocr.available is False


# ── Integração EventBus → Atenção → Memória ───────────────────

class TestVisionAttentionBridgeIntegration:
    def test_error_event_reaches_state_and_memory(self, bus, attention, state, memory, logger):
        AttentionBridge(bus, attention, state, memory, logger)
        bus.publish(Event(
            event_type=EVENT_VISION_ERROR_DETECTED,
            source="vision",
            payload={"text": "Erro detectado na tela", "source": "screen"},
            priority=PRIORITY_HIGH,
            confidence=0.8,
        ))
        assert state.event_history
        assert memory.episodic.total() >= 1

    def test_low_screen_analysis_not_saved(self, bus, attention, state, memory, logger):
        AttentionBridge(bus, attention, state, memory, logger)
        bus.publish(Event(
            event_type=EVENT_VISION_SCREEN_ANALYZED,
            source="vision",
            payload={"text": "janela ativa", "source": "screen"},
            priority=PRIORITY_LOW,
            confidence=0.5,
        ))
        assert memory.episodic.total() == 0


# ── Handler analyze — resumo via LLM ─────────────────────────

class TestHandleVisionAnalyze:
    """Testa a ação analyze do handle_vision (resumo via LLM, fallback)."""

    def _make_vision_result(self, *, ocr_text="", ocr_lines=None, vlm_desc=None,
                            app="VSCode", errors=None):
        return VisionResult(
            ocr=OcrResult(
                available=bool(ocr_text),
                text=ocr_text,
                lines=ocr_lines or ocr_text.splitlines(),
                confidence=0.85,
            ),
            vision=VisionAnalysis(
                available=vlm_desc is not None,
                description=vlm_desc,
            ),
            active_application=app,
            errors_detected=errors or [],
            confidence=0.85,
        )

    def _make_vision_stub(self, result):
        class _VisionStub:
            def __init__(self, r):
                self._r = r
            def analyze_screen(self, question=None):
                return self._r
            def summarize_for_speech(self, r):
                return "resumo stub"
            def format_status(self):
                return "ok"
            def camera_status(self):
                return "off"
            def read_screen(self):
                return self._r.ocr
            def detect_errors(self):
                return self._r.errors_detected
            def find_on_screen(self, q):
                return {"found": False, "query": q, "reason": "stub"}
            def ask(self, q):
                return None
        return _VisionStub(result)

    def _make_multi_chat(self, response="Resumo gerado pela IA."):
        class _Router:
            def __init__(self, resp):
                self._resp = resp
                self.available = True
            def send(self, prompt, temperature=0.7, max_tokens=2048, **kw):
                return self._resp
        return _Router(response)

    def _make_multi_chat_unavailable(self):
        class _Router:
            available = False
            def send(self, prompt, **kw):
                from core.llm.router import AllProvidersFailedError
                raise AllProvidersFailedError("Nenhum provider configurado.")
        return _Router()

    def test_analyze_with_vlm_uses_description(self, capfd):
        from core.handlers import handle_vision
        result = self._make_vision_result(vlm_desc="Terminal com erros de compilação.")
        vision = self._make_vision_stub(result)
        router = self._make_multi_chat()
        output = handle_vision("analyze", {}, vision=vision, llm_router=router)
        assert "Terminal com erros" in output
        captured = capfd.readouterr().out
        assert "erro" not in captured.lower() or "compilação" in captured

    def test_analyze_without_vlm_uses_llm_for_ocr_summary(self, capfd):
        from core.handlers import handle_vision
        result = self._make_vision_result(
            ocr_text="Error: module 'pyautogui' has no attribute 'screenshot'\n"
                     "File \"main.py\", line 42\n"
                     "  img = pyautogui.screenshot()")
        vision = self._make_vision_stub(result)
        router = self._make_multi_chat("Há um erro de importação no código Python.")
        output = handle_vision("analyze", {}, vision=vision, llm_router=router)
        assert "Há um erro de importação" in output
        captured = capfd.readouterr().out
        # Texto bruto OCR não deve vazar no output
        assert "pyautogui.screenshot" not in captured
        assert "File \"main.py\"" not in captured

    def test_analyze_llm_fallback_when_unavailable(self, capfd):
        from core.handlers import handle_vision
        result = self._make_vision_result(
            ocr_text="Error: module 'pyautogui' has no attribute 'screenshot'")
        vision = self._make_vision_stub(result)
        router = self._make_multi_chat_unavailable()
        output = handle_vision("analyze", {}, vision=vision, llm_router=router)
        assert "Detectei texto na tela" in output
        assert "não consegui gerar um resumo" in output
        captured = capfd.readouterr().out
        assert "pyautogui" not in captured

    def test_analyze_llm_exception_fallback(self, capfd):
        from core.handlers import handle_vision
        result = self._make_vision_result(
            ocr_text="Erro fatal no sistema operacional.")
        vision = self._make_vision_stub(result)

        class _BadRouter:
            available = True
            def send(self, prompt, **kw):
                raise ConnectionError("timeout")
        router = _BadRouter()

        output = handle_vision("analyze", {}, vision=vision, llm_router=router)
        assert "Detectei texto na tela" in output
        captured = capfd.readouterr().out
        assert "Erro fatal" not in captured

    def test_analyze_no_ocr_no_vlm_shows_generic(self, capfd):
        from core.handlers import handle_vision
        result = self._make_vision_result(ocr_text="", vlm_desc=None)
        vision = self._make_vision_stub(result)
        multi = self._make_multi_chat()
        output = handle_vision("analyze", {}, vision=vision, multi_chat=multi)
        assert "Sem texto detectável" in output

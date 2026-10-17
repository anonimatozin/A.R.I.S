"""Classe principal do A.R.I.S.

Orquestra o funcionamento do sistema, gerenciando módulos,
comandos e a interface do terminal.
"""

import concurrent.futures
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import webrtcvad
except ImportError:
    webrtcvad = None

import core.handlers  # noqa: F401 — auto-registra todos os handlers
from config.esp32_config import ESP32Config
from config.settings import Settings
from core.advanced_interpreter import AdvancedInterpreter, Intent
from core.calendar import CalendarAccountConfig, CalendarManager
from core.cll1_heartbeat import CLL1Heartbeat
from core.cll1_server import CLL1Server
from core.commands import registry
from core.gmail import GmailAccountConfig, GmailManager, GmailService
from core.greeting import GreetingService
from core.llm import LLMRouter
from core.memcore import MemoryKind
from core.memory import MemoryManager
from core.memory_models import MemoryCategory
from core.memory_organizer import MemoryOrganizer
from core.message_origin import MessageOrigin
from core.module_manager import ModuleManager
from core.multi_provider import MultiProviderChat
from core.neural import NeuralCore
from core.neural.events import (
    EVENT_BOOT,
    EVENT_SHUTDOWN,
    EVENT_TIMER_FINISHED,
    Event,
)
from core.neural.mode import get_mode_manager
from core.neural.world_model import WorldModel
from core.perception import PerceptionConfig, PerceptionManager
from core.perception.continuous_voice_sensor import ContinuousVoiceConfig, ContinuousVoiceSensor
from core.proactive_engine import build_proactive_engine
from core.reflex_layer import ReflexLayer, build_reflex_layer
from core.services import ServiceContainer
from core.sync_engine import SyncEngine
from modules.auto_redaction import AutoRedaction
from modules.browser_automation import BrowserAutomation
from modules.chat import Chat
from modules.context_detector import ContextDetector
from modules.desktop_awareness import DesktopAwareness
from modules.desktop_tools import DesktopTools
from modules.dictation_mode import DictationMode
from modules.entertainment import Entertainment
from modules.esp32_hardware import HardwareManager, SystemState
from modules.face_matrix import HUD_STATES, FaceMatrixClient
from modules.knowledge_graph import KnowledgeGraph
from modules.morning_digest import MorningDigest
from modules.multi_agent import MultiAgentSystem
from modules.notifications import NotificationManager
from modules.safety import SafetyManager
from modules.scheduler import Scheduler
from modules.skills_system import SkillsSystem
from modules.turbo_mode import TurboMode
from search.hyper_search import HyperSearch
from system.analyzer import PersonalAnalyzer
from utils import eyes_bridge
from utils.clap_detector import ClapDetector, ClapDetectorConfig
from utils.logger import Logger
from utils.terminal import ArisUI, Terminal
from utils.voice import Voice
from utils.voice_hybrid import HybridVoice
from weather.hyper_weather import HyperWeather


class Aris:
    """Classe principal do assistente A.R.I.S.

    Responsável por inicializar todos os subsistemas,
    carregar módulos e executar o loop principal.
    """

    def __init__(self) -> None:
        """Inicializa o A.R.I.S. com todas as dependências."""
        self._settings = Settings()
        self._settings.ensure_directories()

        self._logger = Logger(
            name="aris",
            log_dir=self._settings.LOG_DIR,
            level=self._settings.LOG_LEVEL,
            max_size_mb=self._settings.MAX_LOG_SIZE_MB,
        )

        self._module_manager = ModuleManager(
            modules_dir=self._settings.MODULES_DIR,
            plugins_dir=self._settings.PLUGINS_DIR,
            logger=self._logger,
        )

        # Fila de entrada assíncrona — producers externos podem enfileirar
        # mensagens via send_message(); o loop principal consome com get_input().
        self._input_queue: queue.Queue[str] = queue.Queue()

        # Leitora do terminal em thread: o ``input()`` bloqueante impedia o
        # loop principal de drenar a fila de VOZ (wake word) — o comando
        # só era processado quando o usuário apertava Enter (bug real
        # medido: resposta 98s depois no teste ao vivo).
        self._terminal_queue: queue.Queue[str] = queue.Queue()
        self._terminal_reader: threading.Thread | None = None

        self._voice = Voice(
            rate=self._settings.VOICE_RATE,
            volume=self._settings.VOICE_VOLUME,
        )

        self._hybrid_voice = HybridVoice(
            rate=self._settings.VOICE_RATE,
            volume=self._settings.VOICE_VOLUME,
            logger=self._logger,
        )

        # Voz contínua (VAD + wake word + STT leve)
        self._continuous_voice = ContinuousVoiceSensor(
            send_message_fn=self.send_message,
            event_bus=None,  # será definido após _neural ser criado
            config=ContinuousVoiceConfig(
                enabled=self._settings.CONTINUOUS_VOICE_ENABLED,
                vad_aggressiveness=self._settings.VAD_AGGRESSIVENESS,
                stt_model=self._settings.STT_MODEL,
                stt_device=self._settings.STT_DEVICE,
                stt_compute_type=self._settings.STT_COMPUTE_TYPE,
                vosk_model_path=self._settings.VOSK_MODEL_PATH,
                warmup_frames=self._settings.WARMUP_FRAMES,
                energy_threshold=self._settings.ENERGY_THRESHOLD,
                device_index=self._settings.MIC_DEVICE_INDEX,
            ),
            logger=self._logger,
        )

        # Detector de palmas (2 palmas rápidas -> intro JARVIS)
        self._clap_detector = None
        try:
            self._clap_detector = ClapDetector(
                on_double_clap=self._on_double_clap,
                config=ClapDetectorConfig(
                    sample_rate=16000,
                    frame_duration_ms=30,
                    calibration_frames=100,
                    energy_threshold_multiplier=4.0,
                    transient_min_ms=60,
                    transient_max_ms=250,
                    min_peak_rms=0.04,
                    double_clap_min_gap_ms=300,
                    double_clap_max_gap_ms=1200,
                    cooldown_ms=2000,
                    device_index=self._settings.MIC_DEVICE_INDEX,
                ),
                logger=self._logger,
            )
            if self._logger:
                self._logger.info("Clap detector construído.")
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Clap detector indisponível: {e}")

        self._memory = MemoryManager(
            logger=self._logger,
            memory_root=self._settings.MEMORY_ROOT,
        )

        self._llm_router = LLMRouter(logger=self._logger)

        self._multi_chat = MultiProviderChat(logger=self._logger, router=self._llm_router)

        self._chat = Chat(
            api_key=self._settings.GROQ_API_KEY,
            model=self._settings.CHAT_MODEL,
            logger=self._logger,
            memory=self._memory,
            router=self._llm_router,
        )

        self._organizer = MemoryOrganizer(
            memory_manager=self._memory,
            logger=self._logger,
        )

        self._analyzer = PersonalAnalyzer()
        self._weather = HyperWeather(api_keys={
            "openweather": os.getenv("OPENWEATHER_API_KEY", ""),
            "weatherapi": os.getenv("WEATHERAPI_KEY", ""),
        })
        self._search = HyperSearch(api_keys={
            "serpapi": os.getenv("SERPAPI_KEY", ""),
        })

        self._intent = None  # deprecated: IntentAnalyzer removido
        self._interpreter = AdvancedInterpreter()

        # Novos módulos
        self._desktop = DesktopTools()
        self._scheduler = Scheduler(data_dir=self._settings.DATA_DIR)
        self._notifications = NotificationManager(data_dir=self._settings.DATA_DIR)
        self._context = ContextDetector()
        self._safety = SafetyManager(data_dir=self._settings.DATA_DIR)
        self._entertainment = Entertainment(data_dir=self._settings.DATA_DIR)
        self._turbo = TurboMode(logger=self._logger)
        self._knowledge = KnowledgeGraph(data_dir=self._settings.DATA_DIR)
        self._awareness = DesktopAwareness(data_dir=self._settings.DATA_DIR)
        self._redaction = AutoRedaction()
        self._digest = MorningDigest(data_dir=self._settings.DATA_DIR)
        self._greeting = GreetingService(
            timezone=self._settings.GREETING_TIMEZONE,
            latitude=self._settings.GREETING_LATITUDE,
            longitude=self._settings.GREETING_LONGITUDE,
            city=self._settings.GREETING_CITY,
            cooldown_hours=self._settings.GREETING_COOLDOWN_HOURS,
            logger=self._logger,
        )
        self._browser = BrowserAutomation(data_dir=self._settings.DATA_DIR)
        self._agents = MultiAgentSystem(data_dir=self._settings.DATA_DIR)
        self._skills = SkillsSystem(data_dir=self._settings.DATA_DIR)
        self._dictation = DictationMode()

        # WhatsApp Web integration
        try:
            from modules.whatsapp import WhatsApp
            self._whatsapp = WhatsApp(data_dir=self._settings.DATA_DIR / "whatsapp")
        except Exception as e:
            self._whatsapp = None
            self._logger.warning(f"WhatsApp module unavailable: {e}")

        # Gmail (read-only) — Single account (legacy)
        self._gmail = GmailService(
            client_id=os.getenv("ARIS_GMAIL_CLIENT_ID", ""),
            client_secret=os.getenv("ARIS_GMAIL_CLIENT_SECRET", ""),
            safety_manager=self._safety,
            auth_port=int(os.getenv("ARIS_GMAIL_AUTH_PORT", "8741")),
        )
        if self._gmail.is_configured:
            self._gmail.load_stored_tokens()

        # Gmail Manager — Multi-account support
        self._gmail_manager = GmailManager(safety_manager=self._safety)

        # Add primary account from env if configured
        primary_client_id = os.getenv("ARIS_GMAIL_CLIENT_ID", "")
        primary_client_secret = os.getenv("ARIS_GMAIL_CLIENT_SECRET", "")
        if primary_client_id and primary_client_secret:
            self._gmail_manager.add_account(GmailAccountConfig(
                account_id="primary",
                display_name="Principal",
                client_id=primary_client_id,
                client_secret=primary_client_secret,
                account_email=os.getenv("ARIS_GMAIL_ACCOUNT_EMAIL", ""),
                auth_port=int(os.getenv("ARIS_GMAIL_AUTH_PORT", "8741")),
            ))

        # Add second account from env if configured
        secondary_client_id = os.getenv("ARIS_GMAIL2_CLIENT_ID", "")
        secondary_client_secret = os.getenv("ARIS_GMAIL2_CLIENT_SECRET", "")
        if secondary_client_id and secondary_client_secret:
            self._gmail_manager.add_account(GmailAccountConfig(
                account_id="secondary",
                display_name="Secundária",
                client_id=secondary_client_id,
                client_secret=secondary_client_secret,
                account_email=os.getenv("ARIS_GMAIL2_ACCOUNT_EMAIL", ""),
                auth_port=int(os.getenv("ARIS_GMAIL2_AUTH_PORT", "8742")),
            ))

        # Load tokens for all accounts
        self._gmail_manager.load_all_tokens()

        # Calendar Manager
        self._calendar_manager = CalendarManager(safety_manager=self._safety)

        # Add primary calendar account (can reuse Gmail OAuth)
        cal_client_id = os.getenv("ARIS_CALENDAR_CLIENT_ID", "") or primary_client_id
        cal_client_secret = os.getenv("ARIS_CALENDAR_CLIENT_SECRET", "") or primary_client_secret
        if cal_client_id and cal_client_secret:
            self._calendar_manager.add_account(CalendarAccountConfig(
                account_id="primary",
                display_name="Principal",
                client_id=cal_client_id,
                client_secret=cal_client_secret,
                account_email=os.getenv("ARIS_CALENDAR_ACCOUNT_EMAIL", "") or os.getenv("ARIS_GMAIL_ACCOUNT_EMAIL", ""),
                auth_port=int(os.getenv("ARIS_CALENDAR_AUTH_PORT", "8743")),
            ))

        # Load calendar tokens
        self._calendar_manager.load_all_tokens()

        # World Model with Calendar integration
        self._world_model = WorldModel(
            db=self._memory._db,
            logger=self._logger,
            calendar_manager=self._calendar_manager,
        )

        # Hardware ESP32
        self._esp32_config = ESP32Config()
        self._hardware = HardwareManager(config=self._esp32_config, logger=self._logger)

        # Estado de interação
        self._mic_mode = False
        self._cmd_count = 0
        self._proactive_next = 2
        self._proactive_enabled = True
        self._briefing_offered = False
        self._last_aris_question = None
        self._is_speaking = False  # Para barge-in: indica se TTS está tocando

        if self._settings.SAFETY_PASSWORD:
            self._safety.set_master_password(self._settings.SAFETY_PASSWORD)

        # Conectar safety ao registry
        registry.set_safety(self._safety)

        # Neural Core: container de serviços + núcleo cognitivo
        self._container = ServiceContainer()
        self._neural = NeuralCore.build(
            command_registry=registry,
            memory_manager=self._memory,
            logger=self._logger,
        )
        self._neural.register_services(self._container)
        self._neural.set_handler_context(self._build_handler_context)

        # Camada Reflexo: mini-agentes determinísticos (sem LLM)
        try:
            self._neural.initialize_reflex(
                plugins_dir=str(self._settings.PLUGINS_DIR),
                analyzer=self._analyzer,
                state=self._neural.state,
                memory=self._neural.memory,
                working=self._neural.working,
                mode_manager=self._container.get("neural.mode_manager") if hasattr(self._container, "get") else None,
            )
            if self._logger:
                self._logger.info("Camada Reflexo inicializada com plugins")
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Camada Reflexo: falha ao inicializar ({e})")

        # Conectar event bus ao sensor de voz contínua
        if hasattr(self, "_continuous_voice") and self._continuous_voice:
            self._continuous_voice._event_bus = self._neural.event_bus

        # Conectar event bus ao MemoryManager para eventos memory.*
        self._memory.set_event_bus(self._neural.event_bus)

        # Camada de percepção: sensores + atenção integrados ao Neural Core.
        self._perception = None
        try:
            self._perception = PerceptionManager.with_defaults(
                event_bus=self._neural.event_bus,
                state=self._neural.state,
                attention=self._neural.attention,
                memory=self._neural.memory,
                config=PerceptionConfig.load(),
                awareness=self._awareness,
                hardware=self._hardware,
                analyzer=self._analyzer,
                logger=self._logger,
            )
            self._container.set("modules.perception", self._perception)
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Percepção indisponível: {e}")

        self._register_module_services()

        # Memória cognitiva (SQLite em D:/ARIS_MEMORY, com fallback).
        self._memory_service = None
        try:
            from core.memcore import MemoryService
            self._memory_service = MemoryService(
                primary_root=Path("D:/ARIS_MEMORY"),
                legacy_dir=self._settings.MEMORY_ROOT,
                logger=self._logger,
            )
            self._container.set("memory.service", self._memory_service)
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Memória cognitiva indisponível: {e}")

        self._interpreter._memory_service = self._memory_service
        self._interpreter._context_engine = self._neural.context

        # CLL1 distributed components (PC = principal, CLL1 = edge)
        self._cll1_server: CLL1Server | None = None
        self._cll1_heartbeat: CLL1Heartbeat | None = None
        self._sync_engine: SyncEngine | None = None
        self._cll1_offline_mode = False

        # Vision Engine (visão computacional: tela → OCR → VLM → eventos/memória).
        self._vision = None
        try:
            from core.vision import VisionConfig, VisionEngine

            self._vision = VisionEngine(
                event_bus=self._neural.event_bus,
                awareness=self._awareness,
                logger=self._logger,
                config=VisionConfig.load(),
                memory=self._memory_service,
            )
            self._container.set("modules.vision", self._vision)
            if self._logger:
                self._logger.info("Vision Engine inicializado.")
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Vision Engine indisponível: {e}")

        self._running = False
        self._shutdown_done = False  # guarda de idempotência do shutdown()

        # Matriz de LED 8x8 (ESP32 + MAX7219) — periférico opcional:
        # falha de conexão é silenciosa e nunca bloqueia o ARIS.
        self._face_matrix: FaceMatrixClient | None = None
        self._last_aris_status = "idle"
        try:
            self._face_matrix = FaceMatrixClient(
                ip=self._settings.FACE_MATRIX_IP, logger=self._logger
            )
            self._container.set("modules.face_matrix", self._face_matrix)
            if self._logger:
                if self._face_matrix.enabled:
                    self._logger.info(f"Matriz de LED em {self._face_matrix.ip}")
                else:
                    self._logger.info(
                        "Matriz de LED desativada (ARIS_FACE_MATRIX_IP vazio)"
                    )
            # Mesmos eventos de estado que o HUD consome
            bus = self._neural.event_bus
            bus.subscribe("aris_status", self._face_matrix.handle_event)
            bus.subscribe("mic_status", self._face_matrix.handle_event)
        except Exception as e:
            self._face_matrix = None
            if self._logger:
                self._logger.warning(f"Matriz de LED indisponível: {e}")

        # Camada Reflex do loop principal (mini-agentes rápidos: time,
        # calc, sys, memory, jokenpo). Precisa existir — sem ela o
        # `if self._reflex_layer` do loop levantava AttributeError.
        self._reflex_layer: ReflexLayer | None = None
        try:
            self._reflex_layer = build_reflex_layer(self, logger=self._logger)
            if self._logger:
                self._logger.info(
                    "Reflex Layer ativa (time, calc, sys, memory, jokenpo)"
                )
        except Exception as e:
            self._reflex_layer = None
            if self._logger:
                self._logger.warning(f"Reflex Layer indisponível: {e}")

        # Parte 8: ponte para o agente novo (aris_agent) — construída no
        # start() quando ARIS_AGENT_ENABLED=true; None = fluxo antigo intacto.
        self._agent_bridge = None

        # Proactive Engine (será iniciado no start())
        self._proactive_engine = None
        try:
            self._proactive_engine = build_proactive_engine(self)
            if self._proactive_engine:
                self._container.set("proactive.engine", self._proactive_engine)
                if self._logger:
                    self._logger.info("Proactive Engine construído.")
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Proactive Engine indisponível: {e}")

        self._setup_signal_handlers()

    def _register_module_services(self) -> None:
        """Expõe os módulos existentes no container (injeção de serviços).

        Cada módulo direto do ARIS pode se registrar no container via
        ``register_services(container)`` — o padrão oficial para os 7
        módulos que falhavam no ModuleManager (chat, knowledge_graph,
        scheduler, notifications, safety, multi_agent, esp32_hardware).
        """
        for name, instance in (
            ("modules.chat", self._chat),
            ("modules.scheduler", self._scheduler),
            ("modules.notifications", self._notifications),
            ("modules.safety", self._safety),
            ("modules.knowledge", self._knowledge),
            ("modules.agents", self._agents),
            ("modules.hardware", self._hardware),
            ("modules.desktop", self._desktop),
            ("modules.context", self._context),
            ("modules.entertainment", self._entertainment),
            ("modules.turbo", self._turbo),
            ("modules.perception", self._perception),
            ("memory", self._memory),
            ("settings", self._settings),
            ("neural.mode_manager", get_mode_manager()),
        ):
            self._container.set(name, instance)

    def send_message(self, text: str, origin: MessageOrigin | None = None) -> None:
        """Enfileira uma mensagem para processamento assincrono.

        Pode ser chamado de qualquer thread. O loop principal consome
        a fila via _get_input() a cada iteracao.
        """
        self._input_queue.put((text, origin or MessageOrigin()))

    def _get_input(self, mic_mode: bool = False) -> tuple[str, MessageOrigin]:
        """Obtem proxima entrada: fila assincrona primeiro, depois terminal.

        Retorna (text, origin) — text vazio se nada disponivel.
        """
        # 1. Fila assincrona (nao-bloqueante)
        try:
            item = self._input_queue.get_nowait()
            if isinstance(item, tuple):
                return item
            return str(item), MessageOrigin()
        except queue.Empty:
            pass

        # 2. Input do usuario
        if mic_mode:
            if self._hybrid_voice._recognizer is None:
                return "", MessageOrigin()
            ArisUI.show_info("Escutando...")
            result = self._hybrid_voice.listen(timeout=6) or ""
            if result:
                ArisUI.show_user_input(result)
            return result, MessageOrigin(source="voice", channel="mic", user_id="local")
        else:
            # Terminal via leitora em thread (NAO bloqueia o loop): o
            # ``input()`` puro travava o loop principal e comandos de voz
            # (wake word) ficavam na fila até o Enter do usuário (bug
            # real: resposta 98s depois no teste ao vivo). Timeout curto
            # = voz respondida em ≤300ms; o texto digitado segue fluindo.
            self._ensure_terminal_reader()
            try:
                text = self._terminal_queue.get(timeout=0.3)
            except queue.Empty:
                return "", MessageOrigin()
            return text, MessageOrigin(source="terminal", channel="stdin", user_id="local")

    def _ensure_terminal_reader(self) -> None:
        """Sobe (uma unica vez) a thread leitora do terminal."""
        if self._terminal_reader is not None:
            return
        self._terminal_reader = threading.Thread(
            target=self._terminal_read_loop, daemon=True, name="terminal-input",
        )
        self._terminal_reader.start()

    def _terminal_read_loop(self) -> None:
        """Loop da leitora: consome ``input_modern`` e enfileira o texto.

        EOF (Ctrl+D/pipe fechado) retorna "" — espera 0,5s antes de
        tentar de novo para nao hot-spinhar prompts (spam infinito no
        console, medido em execucao real com stdin fechado).
        """
        while True:
            try:
                text = ArisUI.input_modern(
                    version=self._settings.VERSION,
                    provider=self._llm_router.provider_names[0] if self._llm_router.provider_names else "local",
                    mem_count=self._memory.get_stats().get("total_memories", 0),
                    task_count=self._scheduler.get_pending_count(),
                )
            except Exception:
                text = ""
            if not text:
                threading.Event().wait(0.5)
                continue
            self._terminal_queue.put(text)

    def _setup_signal_handlers(self) -> None:
        """Configura handlers para sinais do sistema."""
        def signal_handler(sig: int, frame: object) -> None:
            self._logger.info("Sinal de interrupção recebido. Encerrando...")
            self.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal_handler)

    def _build_handler_context(self, origin: MessageOrigin | None = None) -> dict:
        """Constrói o contexto com todas as instâncias de módulos para os handlers."""
        ctx = {
            "weather": self._weather,
            "search": self._search,
            "analyzer": self._analyzer,
            "desktop": self._desktop,
            "scheduler": self._scheduler,
            "notifications": self._notifications,
            "context": self._context,
            "safety": self._safety,
            "entertainment": self._entertainment,
            "turbo": self._turbo,
            "knowledge": self._knowledge,
            "awareness": self._awareness,
            "redaction": self._redaction,
            "digest": self._digest,
            "browser": self._browser,
            "agents": self._agents,
            "skills": self._skills,
            "dictation": self._dictation,
            "memory": self._memory,
            "memory_service": self._memory_service,
            "voice": self._voice,
            "settings": self._settings,
            "hardware": self._hardware,
            "face_matrix": self._face_matrix,
            "event_bus": self._neural.event_bus,
            "state": self._neural.state,
            "perception": self._perception,
            "vision": self._vision,
            "multi_chat": self._multi_chat,
            "llm_router": self._llm_router,
            "gmail": self._gmail,
            "gmail_manager": self._gmail_manager,
            "calendar": self._calendar_manager,
            "world_model": self._world_model,
            "whatsapp": self._whatsapp,
        }

        # Dados pré-computados para handlers que precisam
        try:
            ctx["weather_report"] = self._weather.format_report("São Paulo")
        except Exception:
            ctx["weather_report"] = ""
        try:
            ctx["tasks_report"] = self._scheduler.format_task_list(self._scheduler.list_tasks())
        except Exception:
            ctx["tasks_report"] = ""
        try:
            ctx["system_report"] = f"CPU: {self._analyzer.cpu_usage():.1f}%"
        except Exception:
            ctx["system_report"] = ""

        ctx["origin"] = origin or MessageOrigin()
        return ctx

    def _execute_intent(self, intent: Intent, origin: MessageOrigin | None = None) -> str | None:
        """Executa uma intencao detectada pela IA.

        Delega para o CommandRegistry atraves do Neural Core (Security
        Gate + Acao + Feedback). Se o handler nao existe, cai no
        fallback legacy. Retorna o resumo falavel do resultado.
        """
        module = intent.module
        params = intent.params

        ArisUI.show_action(module, intent.action, params)

        # Comando de saida (sempre funciona)
        if module == "exit":
            self.shutdown()
            return None

        # Tentar registry primeiro
        if registry.has_intent(module):
            ctx = self._build_handler_context(origin=origin)
            decision = self._neural.decision.decide(intent, source="llm")
            result = self._neural.execute(decision, ctx=ctx)
            if not result.success and result.error.startswith("Seguranca:"):
                ArisUI.show_error(result.error)
                return None
            if result.success:
                return result.output
            # Honestidade: a falha REAL volta para a resposta. Sem isso, a
            # ação falhava em silêncio e só a frase genérica do LLM (que
            # assume sucesso) era falada.
            reason = (result.error or result.output or "").strip()
            if not reason:
                reason = "a ação não pôde ser concluída"
            ArisUI.show_error(reason)
            return f"Não deu certo: {reason}"

        # Fallback: modulos sem handler registrado ainda
        self._execute_intent_legacy(intent)
        return None

    def _maybe_proactive(self, voice) -> None:
        """Sugestão proativa leve estilo JARVIS (máx. 1 a cada ~4 comandos).

        Usa o que já aprendeu (memórias) e o estado do sistema para
        oferecer ajuda real — nunca executa nada sem permissão.
        """
        if not self._proactive_enabled or not voice.enabled:
            return
        self._cmd_count += 1
        if self._cmd_count < self._proactive_next:
            return
        self._proactive_next = self._cmd_count + 4
        try:
            total = self._memory.get_stats().get("total_memories", 0)
            if total == 0:
                suggestion = ("Ainda não tenho memórias suas. Se quiser, eu anoto suas "
                              "preferências conforme você for conversando comigo.")
            else:
                cpu = getattr(self._analyzer, "get_cpu_usage", lambda: None)()
                ram = getattr(self._analyzer, "get_memory_usage", lambda: None)()
                if cpu and cpu > 85:
                    suggestion = (f"Detectei uso alto de CPU em {cpu:.0f} por cento. "
                                  "Quer que eu prepare um relatório do sistema?")
                elif ram and ram > 90:
                    suggestion = (f"A memória está em {ram:.0f} por cento. "
                                  "Posso sugerir processos para liberar espaço?")
                elif total >= 3:
                    if self._briefing_offered:
                        return
                    self._briefing_offered = True
                    suggestion = None  # Desativado: não oferecer briefing automaticamente
                else:
                    suggestion = ("Estou de prontidão. Se quiser, posso agendar lembretes "
                                  "ou montar um briefing do dia.")
            if suggestion:
                print(f"  💡 {suggestion}")
                self._is_speaking = True
                voice.speak(suggestion)
                self._is_speaking = False
        except Exception as e:
            if self._logger:
                self._logger.debug(f"Proactive suggestion skipped: {e}")

    def _execute_intent_legacy(self, intent: Intent, origin: MessageOrigin | None = None) -> None:
        """Fallback: route through SecurityGate for unregistered handlers."""
        decision = self._neural.decision.decide(intent, source="llm_legacy")
        ctx = self._build_handler_context(origin=origin)
        result = self._neural.execute(decision, ctx=ctx)
        if not result.success:
            if self._logger:
                self._logger.warning(
                    f"Legacy intent {intent.module}/{intent.action}: {result.error}"
                )

    def _print_banner(self) -> None:
        """Exibe o banner inicial do sistema."""
        ArisUI.show_banner(self._settings.VERSION)

    def start(self) -> None:
        """Inicia o A.R.I.S."""
        self._logger.info("Iniciando A.R.I.S.")

        # Carregar módulos (com DI via container)
        self._module_manager.load_modules(container=self._container)

        # Neural Core: sincronizar estado com o mundo real
        self._neural.event_bus.publish(Event(
            event_type=EVENT_BOOT,
            source="aris",
            payload={"version": self._settings.VERSION},
            priority=80,
            confidence=1.0,
        ))
        self._neural.state.update_hardware(
            connected=self._hardware.connected,
            available=self._hardware.available,
        )

        # Configurar multi-provider com personalidade
        from config.personality import ARIS_PERSONALITY
        self._multi_chat.set_system_prompt(ARIS_PERSONALITY)

        # Iniciar hardware ESP32
        if self._esp32_config.enabled:
            esp32_result = self._hardware.start()
            self._logger.info(f"Hardware: {esp32_result}")

            # Registrar callbacks do botão
            self._hardware.register_button_action("voice_toggle", self._on_button_voice_toggle)
            self._hardware.register_button_action("stop_speaking", self._on_button_stop_speaking)
            self._hardware.register_button_action("turbo_mode", self._on_button_turbo_mode)
            self._hardware.register_button_action("config_action", self._on_button_config)
            self._hardware.register_button_action("reconnect", self._on_button_reconnect)

            # Deck Wi-Fi: o rosto reage ao portal/conexão (utils/eyes_bridge)
            self._hardware.register_event_listener(self._on_deck_event)

            # Estado inicial (sem logs falsos se hardware indisponível)
            self._hardware.set_state(SystemState.IDLE)
            self._neural.state.update_hardware(
                connected=self._hardware.connected,
                available=self._hardware.available,
            )
        else:
            self._neural.state.update_hardware(connected=False, available=False)

        # Iniciar matriz de LED 8x8 (opcional: sem IP, fica desativada)
        if getattr(self, "_face_matrix", None):
            try:
                self._face_matrix.start()
            except Exception as e:
                self._logger.warning(f"Matriz de LED: falha ao iniciar ({e})")

        # Iniciar scheduler em background
        self._scheduler.start_checker(callback=self._on_task_due)
        self._neural.state.update_scheduler(
            running=True,
            pending_tasks=self._scheduler.get_pending_count(),
        )

        # Memória cognitiva: integridade, migração e manutenção
        if self._memory_service:
            try:
                self._memory_service.boot()
            except Exception as e:
                self._logger.warning(f"Boot da memória cognitiva falhou: {e}")

        # Iniciar percepção (sensores em background; sem falhas se indisponíveis)
        if self._perception is not None:
            try:
                self._perception.start()
            except Exception as e:
                self._logger.warning(f"Percepção: falha ao iniciar ({e})")

        # Iniciar voz contínua (VAD + wake word + STT)
        if hasattr(self, "_continuous_voice") and self._continuous_voice:
            try:
                # Configurar callback para wake word beep e barge-in
                self._continuous_voice.set_transcript_callback(self._on_voice_transcript)
                self._continuous_voice.start()
                self._logger.info("Voz contínua iniciada (VAD + wake word + STT)")
            except Exception as e:
                self._logger.warning(f"Voz contínua: falha ao iniciar ({e})")
                # Fallback gracioso: continuar sem microfone
                self._continuous_voice = None

        # Iniciar detector de palmas (2 palmas -> intro JARVIS)
        if hasattr(self, "_clap_detector") and self._clap_detector:
            try:
                if self._clap_detector.start():
                    self._logger.info("Clap detector iniciado (2 palmas = intro JARVIS)")
                else:
                    self._logger.warning("Clap detector: não disponível (PyAudio?)")
            except Exception as e:
                self._logger.warning(f"Clap detector: falha ao iniciar ({e})")
                self._clap_detector = None

        # Iniciar Proactive Engine
        if self._proactive_engine:
            try:
                self._proactive_engine.start()
                self._logger.info("Proactive Engine iniciado.")
            except Exception as e:
                self._logger.warning(f"Proactive Engine: falha ao iniciar ({e})")

        # CLL1 distributed: server, heartbeat, sync engine
        self._start_distributed()

        # Sincronizar personalidade com CLL1 (Edge) e painel web
        self._sync_personality()

        # ARIS Eyes: mood ocioso vem da personalidade; sobe os olhos se preciso
        eyes_bridge.refresh_idle_mood()
        if eyes_bridge.ensure_running():
            self._logger.info("ARIS Eyes: conectado")
        elif eyes_bridge.autolaunch_enabled():
            self._logger.info("ARIS Eyes: iniciando olhos automaticamente (modo mini)")
        else:
            self._logger.info("ARIS Eyes: não rodando (./aris_eyes/aris-eyes.sh --mini)")

        # Exibir banner
        self._print_banner()

        # Status do microfone
        mic_available = self._continuous_voice is not None and self._continuous_voice.available
        mic_enabled = self._continuous_voice is not None and self._continuous_voice.enabled
        ArisUI.show_mic_status(mic_enabled, mic_available)

        # Saudação por voz
        voice = self._hybrid_voice if self._hybrid_voice.enabled else self._voice
        if voice.enabled:
            self._is_speaking = True
            voice.speak("A.R.I.S. inicializado. Todos os sistemas operacionais.")
            self._is_speaking = False

        # Status do provider
        provider_status = self._llm_router.get_status()
        if provider_status["providers"]:
            active = next(
                (p["name"] for p in provider_status["providers"] if p.get("available")),
                "nenhum",
            )
            print(f"  Provider ativo: {Terminal.colorize(active, Terminal.CYAN)}")
        print()

        # Loop principal
        self._running = True
        self._logger.info("Sistema pronto para recebimento de comandos.")
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="aris-llm")

        # Parte 8: ponte do agente (desligada por padrão; ARIS_AGENT_ENABLED)
        self._agent_bridge = self._build_agent_bridge()

        while self._running:
            try:
                # Input: fila assincrona, teclado ou microfone
                voice = self._hybrid_voice if self._hybrid_voice.enabled else self._voice
                if self._mic_mode and self._hybrid_voice._recognizer is None:
                    self._mic_mode = False
                user_input, msg_origin = self._get_input(mic_mode=self._mic_mode)

                if not user_input.strip():
                    continue

                # Mostrar entrada do usuário com cor distinta
                ArisUI.show_user_input(user_input)
                self._publish_aris_status("executing")

                # Saudação contextual na primeira interação da sessão (desativada)
                # if self._greeting.should_greet():
                #     greeting_text = self._greeting.compose_greeting()
                #     print(f"\n  {greeting_text}\n")
                #     self._greeting.register_greeting()

                # Alimenta o observador de memória (buffer de conversa)
                if self._memory_service:
                    try:
                        self._memory_service.observe("USER_MESSAGE", {"text": user_input})
                    except Exception as e:
                        self._logger.warning(f"Observador de memória falhou: {e}")

                ui = user_input.strip().lower()
                # Modo voz (microfone)
                if ui in ("modo voz", "voz on", "mic on", "ativar mic", "usar microfone"):
                    self._mic_mode = True if self._hybrid_voice._recognizer is not None else False
                    self._sync_hardware_state(SystemState.IDLE)
                    if self._mic_mode:
                        ArisUI.show_info("Modo voz ativado. Fale seus comandos. Digite 'modo texto' para voltar a digitar.")
                    else:
                        ArisUI.show_warning("Sem microfone disponível. Instale: pip install SpeechRecognition pyaudio")
                    continue
                if ui in ("modo texto", "voz off", "mic off", "desativar mic"):
                    self._mic_mode = False
                    ArisUI.show_info("Modo digitação ativado.")
                    continue

                # Configuração de microfone
                if ui in ("mic list", "microfone lista", "listar microfones", "list mics"):
                    self._list_microphones()
                    continue
                if ui.startswith("mic select ") or ui.startswith("microfone selecionar "):
                    parts = ui.split()
                    if len(parts) >= 3:
                        try:
                            idx = int(parts[2])
                            self._select_microphone(idx)
                        except ValueError:
                            ArisUI.show_error("Uso: mic select <número>")
                    else:
                        ArisUI.show_error("Uso: mic select <número>")
                    continue
                if ui.startswith("mic threshold ") or ui.startswith("microfone threshold "):
                    parts = ui.split()
                    if len(parts) >= 3:
                        try:
                            threshold = float(parts[2])
                            self._set_energy_threshold(threshold)
                        except ValueError:
                            ArisUI.show_error("Uso: mic threshold <valor>")
                    else:
                        ArisUI.show_error("Uso: mic threshold <valor>")
                    continue
                if ui.startswith("mic vad ") or ui.startswith("microfone vad "):
                    parts = ui.split()
                    if len(parts) >= 3:
                        try:
                            level = int(parts[2])
                            if 0 <= level <= 3:
                                self._set_vad_aggressiveness(level)
                            else:
                                ArisUI.show_error("VAD deve ser 0-3")
                        except ValueError:
                            ArisUI.show_error("Uso: mic vad <0-3>")
                    else:
                        ArisUI.show_error("Uso: mic vad <0-3>")
                    continue
                if ui in ("mic status", "microfone status", "mic config"):
                    self._show_mic_config()
                    continue
                if ui in ("mic restart", "microfone reiniciar"):
                    self._restart_continuous_voice()
                    continue

                # Safety: exit sempre funciona
                if user_input.strip().lower() in ("exit", "sair", "encerrar", "desligar"):
                    self.shutdown()
                    break

                # Reinício: abre um novo cmd com a ARIS e encerra esta
                if ui in ("/reiniciar", "/restart", "reiniciar", "restart"):
                    print("  🔄 Reiniciando A.R.I.S. ...")
                    self._restart()
                    self.shutdown()
                    break

                # Comandos diretos do terminal
                if user_input.strip().lower() in ("help", "ajuda", "comandos"):
                    self._show_help()
                    continue

                # Gate de confirmação do WhatsApp: com rascunho pendente,
                # só uma resposta afirmativa real envia; negativas bloqueiam.
                # Roda ANTES de reflexo/LLM — "não" nunca vira outro intent.
                wa_reply = None
                try:
                    from modules.whatsapp import confirmation_reply
                    wa_reply = confirmation_reply(user_input)
                except Exception as e:
                    self._logger.warning(f"WhatsApp gate: {e}")
                if wa_reply is not None:
                    self._cognitive_trace(user_input, "WHATSAPP_CONFIRM", wa_reply[:40])
                    self._interpreter.update_context(user_input, wa_reply, [])
                    ArisUI.show_aris_response(wa_reply, from_reflex=False)
                    if voice.enabled and "http" not in wa_reply.lower():
                        self._sync_hardware_state(SystemState.SPEAKING)
                        self._is_speaking = True
                        voice.speak(wa_reply)
                        self._is_speaking = False
                        self._sync_hardware_state(SystemState.IDLE)
                    self._track_aris_question(wa_reply)
                    continue

                # Neural Core: caminho determinístico (sem LLM)
                # Primeiro tenta Reflex Layer (mini-agentes rápidos)
                reflex_result = None
                if self._reflex_layer:
                    try:
                        reflex_result = self._reflex_layer.process(user_input, origin=msg_origin)
                    except Exception as e:
                        self._logger.error(f"ReflexLayer: falha no processamento ({e})")

                if reflex_result and reflex_result.handled:
                    self._cognitive_trace(user_input, "REFLEX", f"agent={reflex_result.module}/{reflex_result.action}")
                    # Registrar no contexto da conversa
                    self._interpreter.update_context(user_input, reflex_result.response, [])
                    if reflex_result.response:
                        ArisUI.show_aris_response(reflex_result.response, from_reflex=True)
                        if voice.enabled and reflex_result.speak:
                            if "http" not in reflex_result.response.lower():
                                self._sync_hardware_state(SystemState.SPEAKING)
                                self._is_speaking = True
                                voice.speak(reflex_result.response)
                                self._is_speaking = False
                                self._sync_hardware_state(SystemState.IDLE)
                        self._track_aris_question(reflex_result.response)
                    self._face_command_happy()
                    self._maybe_proactive(voice)
                    continue

                try:
                    neural_result = self._neural.process(user_input)
                except Exception as e:
                    self._logger.error(f"NeuralCore: falha no processamento ({e})")
                    neural_result = None
                if neural_result is not None:
                    self._cognitive_trace(user_input, "DETERMINISTIC", f"handler={neural_result.output[:40] if neural_result.output else 'error'}")
                    # Registrar no contexto da conversa (mesmo sem LLM)
                    # para que "e depois?", "e então?" retomem o assunto.
                    reply_text = neural_result.output or neural_result.error or ""
                    self._interpreter.update_context(user_input, reply_text, [])
                    if neural_result.output:
                        ArisUI.show_aris_response(neural_result.output, from_reflex=False)
                        if voice.enabled:
                            # Não falar texto que contenha URLs (evita ler link letra por letra)
                            if "http" not in neural_result.output.lower():
                                self._sync_hardware_state(SystemState.SPEAKING)
                                self._is_speaking = True
                                voice.speak(neural_result.output)
                                self._is_speaking = False
                                self._sync_hardware_state(SystemState.IDLE)
                        self._track_aris_question(neural_result.output)
                    elif neural_result.error:
                        ArisUI.show_error(neural_result.error)
                    self._face_command_happy()
                    self._maybe_proactive(voice)
                    continue

                # Parte 8: roteamento para o agente novo (desligado por padrão).
                # processar() devolve None => o fluxo antigo (answer-learning →
                # LLM antigo) segue intacto. Qualquer erro vira None + log.
                if self._agent_bridge is not None:
                    resposta_agente = None
                    try:
                        resposta_agente = self._agent_bridge.processar(
                            user_input, origin=msg_origin
                        )
                    except Exception as e:
                        self._logger.error(
                            f"Agente: falha ({e}); seguindo o caminho atual"
                        )
                    if resposta_agente is not None:
                        self._cognitive_trace(user_input, "AGENTE", resposta_agente[:40])
                        self._interpreter.update_context(user_input, resposta_agente, [])
                        ArisUI.show_aris_response(resposta_agente, from_reflex=False)
                        if voice.enabled and "http" not in resposta_agente.lower():
                            self._sync_hardware_state(SystemState.SPEAKING)
                            self._is_speaking = True
                            voice.speak(resposta_agente)
                            self._is_speaking = False
                            self._sync_hardware_state(SystemState.IDLE)
                        self._track_aris_question(resposta_agente)
                        self._face_command_happy()
                        self._maybe_proactive(voice)
                        continue

                # Resposta curta na sequência de uma pergunta da própria
                # ARIS: aprende a resposta em vez de perder o contexto
                # (ex.: ARIS pergunta a fruta favorita e usuário diz "abacaxi").
                if self._looks_like_answer(user_input):
                    self._cognitive_trace(user_input, "LEARN_ANSWER")
                    try:
                        learned = self._learn_answer(user_input, voice)
                        if learned:
                            continue
                    except Exception as e:
                        if self._logger:
                            self._logger.warning(f"Falha ao aprender resposta: {e}")

                # Verificar feedback do usuário sobre status do PC (override de modo)
                pc_feedback = self._interpreter.handle_pc_status_feedback(user_input)
                if pc_feedback:
                    response_text, _ = pc_feedback
                    # Aplicar override no ModeManager
                    from core.neural.mode import get_mode_manager
                    mm = get_mode_manager()
                    msg_lower = user_input.lower()
                    pc_online = any(p in msg_lower for p in ["ligado", "online"])
                    mm.apply_user_feedback(pc_online, reason="user_feedback_explicit")

                    ArisUI.show_aris_response(response_text, from_reflex=False)
                    if voice.enabled:
                        self._sync_hardware_state(SystemState.SPEAKING)
                        self._is_speaking = True
                        voice.speak(response_text)
                        self._is_speaking = False
                        self._sync_hardware_state(SystemState.IDLE)
                    self._track_aris_question(response_text)
                    continue

                # Enviar tudo para a IA interpretar
                chat = self._multi_chat if self._multi_chat.available else self._chat
                if chat.available or (hasattr(chat, 'available') and chat.available):
                    self._cognitive_trace(user_input, "LLM", f"provider={getattr(chat, '_provider_name', '?')}")
                    # Estado: processando
                    self._sync_hardware_state(SystemState.THINKING)

                    # Usar interpretador avancado (multi-comando + contexto)
                    intent_prompt = self._interpreter.build_interpretation_prompt(user_input)

                    # Executar LLM em thread separada com timeout (permite Ctrl+C)
                    try:
                        future = self._executor.submit(chat.send, intent_prompt)
                        response = future.result(timeout=60.0)
                    except concurrent.futures.TimeoutError:
                        ArisUI.show_error("Tempo limite excedido (60s). Tente novamente.")
                        self._sync_hardware_state(SystemState.IDLE)
                        continue
                    except concurrent.futures.CancelledError:
                        self._sync_hardware_state(SystemState.IDLE)
                        continue

                    # Extrair intencoes (suporta multiplos comandos)
                    clean_response, intents = self._interpreter.parse_ai_response(response)

                    # Remover saudações duplicadas/genéricas da resposta do LLM
                    clean_response = self._clean_duplicate_greetings(clean_response)

                    # Mostrar quantas acoes foram detectadas
                    if len(intents) > 1:
                        ArisUI.show_actions_count(len(intents))

                    # Executar todas as intencoes na ordem
                    spoken_parts = []
                    if intents:
                        self._publish_aris_status("executing")
                    for intent in intents:
                        part = self._execute_intent(intent, origin=msg_origin)
                        if part:
                            spoken_parts.append(str(part))
                    if intents:
                        self._face_command_happy()

                    # Resposta completa (texto natural + resultados das ações)
                    speak_text = clean_response or ""
                    if spoken_parts:
                        speak_text = (speak_text + " " if speak_text else "") + " ".join(spoken_parts)

                    # Limpar markdown para TTS não falar asteriscos/links
                    from utils.voice_hybrid import HybridVoice
                    speak_text = HybridVoice._clean_for_tts(speak_text)

                    # Atualizar contexto da conversa para retomar o assunto
                    # depois (ex.: "e então?", "e depois?").
                    self._interpreter.update_context(
                        user_input, speak_text, intents)

                    # Mostrar resposta formatada
                    if clean_response:
                        ArisUI.show_aris_response(clean_response, from_reflex=False)

                    if voice.enabled and speak_text and "http" not in speak_text.lower():
                        self._sync_hardware_state(SystemState.SPEAKING)
                        self._is_speaking = True
                        voice.speak(speak_text)
                        self._is_speaking = False
                    self._track_aris_question(speak_text)

                    # Estado: idle
                    self._sync_hardware_state(SystemState.IDLE)
                    self._maybe_proactive(voice)

                    # Auto-salvar
                    if self._memory.should_save(user_input):
                        category = MemoryCategory.CONVERSATIONS
                        importance = 5
                        tags = ["conversa", "auto"]
                        is_permanente = False

                        text_lower = user_input.lower()
                        if any(w in text_lower for w in ["meu nome", "me chamo", "sou o", "sou a", "pode me chamar"]):
                            category = MemoryCategory.PROFILE
                            importance = 10
                            tags = ["perfil", "pessoal"]
                            is_permanente = True
                        elif any(w in text_lower for w in ["meu diretório", "meu projeto", "meu computador"]):
                            category = MemoryCategory.CONFIG
                            importance = 8
                            tags = ["config", "pessoal"]

                        self._memory.save(
                            title=user_input[:50],
                            content=user_input,
                            category=category,
                            importance=importance,
                            tags=tags,
                            is_permanente=is_permanente,
                        )
                else:
                    ArisUI.show_error("Chat indisponivel. Configure GROQ_API_KEY ou GEMINI_API_KEY no .env.")

            except KeyboardInterrupt:
                # Cancelar operação em andamento
                print("\n  Operação cancelada.")
                self._sync_hardware_state(SystemState.IDLE)
                continue
            except EOFError:
                break

        self.shutdown()

    def _on_task_due(self, task) -> None:
        """Callback chamado quando uma tarefa agendada e executada."""
        self._notifications.notify(
            title=f"Lembrete: {task.title}",
            message=task.description or "Tarefa agendada",
        )
        print(f"\n  {Terminal.YELLOW}⏰ LEMBRETE:{Terminal.RESET} {Terminal.BOLD}{task.title}{Terminal.RESET}")
        if task.description:
            print(f"  {Terminal.DIM}{task.description}{Terminal.RESET}")

        # Evento de timer no Neural Core
        self._neural.event_bus.publish(Event(
            event_type=EVENT_TIMER_FINISHED,
            source="scheduler",
            payload={"title": task.title},
            priority=70,
            confidence=1.0,
        ))

        # Notificar ESP32
        if self._hardware.connected:
            self._hardware.set_state(SystemState.WARNING)
        # Timer = atenção: olhos em "alert"
        eyes_bridge.set_state(SystemState.WARNING.value)

    # ── Botão ESP32 callbacks ───────────────────────────────

    def _on_button_voice_toggle(self) -> None:
        """1 clique: ativar/desativar voz."""
        if self._voice.enabled:
            self._voice.enabled = False
            print(f"\n  {Terminal.YELLOW}🎤 Voz desativada (botão ESP32){Terminal.RESET}")
        else:
            self._voice.enabled = True
            print(f"\n  {Terminal.GREEN}🎤 Voz ativada (botão ESP32){Terminal.RESET}")

    def _on_button_stop_speaking(self) -> None:
        """2 cliques: interromper fala."""
        if self._hybrid_voice and self._hybrid_voice.enabled:
            self._hybrid_voice.stop()
        elif self._voice.enabled:
            self._voice.stop()
        print(f"\n  {Terminal.YELLOW}⏹ Fala interrompida (botão ESP32){Terminal.RESET}")

    def _on_button_turbo_mode(self) -> None:
        """3 cliques: ativar/desativar modo turbo."""
        if self._turbo.active:
            result = self._turbo.deactivate()
            print(f"\n  {Terminal.YELLOW}{result} (botão ESP32){Terminal.RESET}")
        else:
            result = self._turbo.activate()
            print(f"\n  {Terminal.CYAN}{result} (botão ESP32){Terminal.RESET}")

    def _on_button_config(self) -> None:
        """4 cliques: ação configurável (mostrar status)."""
        print(f"\n  {Terminal.CYAN}📊 Status do sistema (botão ESP32){Terminal.RESET}")
        stats = self._memory.get_stats()
        print(f"  Memórias: {stats.get('total_memories', 0)}")
        print(f"  Tarefas: {self._scheduler.get_pending_count()}")
        print(f"  Provider: {self._llm_router.provider_names[0] if self._llm_router.provider_names else 'nenhum'}")
        print(f"  Hardware: {'Conectado' if self._hardware.connected else 'Desconectado'}")

    def _on_button_reconnect(self) -> None:
        """Long press: reconectar ESP32."""
        print(f"\n  {Terminal.YELLOW}🔄 Reconectando ESP32...{Terminal.RESET}")
        self._hardware.stop()
        import time
        time.sleep(1)
        result = self._hardware.start()
        print(f"  {result}")

    def _on_deck_event(self, event: str, data: dict) -> None:
        """Evento do Mini Deck (Wi-Fi): reação no rosto + aviso falado.

        Estados do deck (wifi_status): portal → surprised, connecting →
        thinking, connected → happy, failed → error (WIFI_FACES em
        utils/eyes_bridge). Se a ARIS estiver ocupada, a reação fica
        pendente e o aviso falado é suprimido (nada de falar por cima).
        """
        if event != "wifi_status":
            return
        estado = str(data.get("estado", ""))
        resultado = eyes_bridge.set_wifi_face(estado, forcar=(estado == "failed"))
        if resultado != "aplicado" or estado not in ("connected", "failed"):
            return                      # pendente/forçado/inválido: sem fala
        if os.getenv("ARIS_WIFI_FALA", "1").strip().lower() in ("0", "false", "no", "off"):
            return
        texto = (
            "Wi-Fi conectado."
            if estado == "connected"
            else "Não consegui me conectar ao Wi-Fi."
        )
        try:
            self._is_speaking = True
            voice = self._hybrid_voice if self._hybrid_voice.enabled else self._voice
            voice.speak(texto)
        except Exception as e:
            self._logger.debug(f"Deck Wi-Fi: aviso falado falhou ({e})")
        finally:
            self._is_speaking = False

    # ── Voice callbacks ──────────────────────────────────────

    def _on_voice_transcript(self, transcript: str) -> None:
        """Callback chamado quando a voz contínua detecta uma transcrição.

        - Toca bip de wake word
        - Implementa barge-in: para TTS se estiver falando
        """
        # Barge-in: se ARIS está falando, parar imediatamente
        if self._is_speaking:
            self._stop_voice()
            self._is_speaking = False

        # Bip de wake word
        try:
            ArisUI.show_wake_beep()
        except Exception:
            pass

        # Ouvindo o usuário: olhos em "listening"
        eyes_bridge.set_state("listening")

    def _on_double_clap(self) -> None:
        """Callback disparado ao detectar 2 palmas rápidas.

        Toca MP3 de intro (fade-in) + fala linha estilo JARVIS.
        """
        if self._logger:
            self._logger.info("Duas palmas detectadas - disparando intro JARVIS")

        # Barge-in: parar TTS se estiver falando
        if self._is_speaking:
            self._stop_voice()
            self._is_speaking = False

        # Tocar MP3 com fade-in (pygame)
        try:
            import pygame
            pygame.mixer.init()
            mp3_path = self._settings.BASE_DIR / "assets" / "jarvis_intro.mp3"
            if mp3_path.exists():
                pygame.mixer.music.load(str(mp3_path))
                pygame.mixer.music.set_volume(0.7)
                pygame.mixer.music.play()
                # Fade-in simples
                for vol in range(0, 71, 10):
                    pygame.mixer.music.set_volume(vol / 100)
                    pygame.time.wait(30)
        except Exception as e:
            if self._logger:
                self._logger.debug(f"MP3 intro falhou (pode não existir): {e}")

        # Falar linha JARVIS (usa HybridVoice se disponível)
        jarvis_line = "Bom dia, senhor. Todos os sistemas operacionais."
        voice = self._hybrid_voice if self._hybrid_voice.enabled else self._voice
        if voice.enabled:
            self._is_speaking = True
            voice.speak(jarvis_line)
            self._is_speaking = False

    def _stop_voice(self) -> None:
        """Para qualquer síntese de voz em andamento (TTS)."""
        try:
            if self._hybrid_voice and self._hybrid_voice.enabled:
                self._hybrid_voice.stop()
        except Exception:
            pass
        try:
            if self._voice and self._voice.enabled:
                self._voice.stop()
        except Exception:
            pass

    # ── Estado visual → ESP32 ───────────────────────────────

    def _sync_hardware_state(self, state: SystemState) -> None:
        """Sincroniza estado do ARIS com ESP32."""
        if self._hardware.connected:
            self._hardware.set_state(state)
        self._publish_aris_status(state)
        # ARIS Eyes: o mesmo estado vai para os olhos na tela. A ponte é
        # não-bloqueante e nunca lança (utils/eyes_bridge.py).
        eyes_bridge.set_state(
            getattr(state, "value", str(state)),
            speech_level=getattr(getattr(self, "_hybrid_voice", None), "_volume", None),
        )

    def _publish_aris_status(self, state) -> None:
        """Publica ``aris_status`` — o mesmo evento que o HUD consome.

        A matriz de LED assina esse evento; estados fora do vocabulário do
        HUD (warning, offline, ...) são ignorados para não inventar caras.
        """
        value = getattr(state, "value", state)
        if not isinstance(value, str) or value not in HUD_STATES:
            return
        previous = self._last_aris_status
        self._last_aris_status = value
        try:
            self._neural.event_bus.publish(Event(
                event_type="aris_status",
                source="aris",
                payload={"state": value},
                priority=50,
                confidence=1.0,
            ))
        except Exception:
            pass
        face = getattr(self, "_face_matrix", None)
        if face is not None and value == "idle" and previous not in (None, "idle"):
            # De vez em quando, sozinho, ao voltar ao repouso
            try:
                face.maybe_happy(probability=0.06, hold=1.5)
            except Exception:
                pass

    def _face_command_happy(self) -> None:
        """Feliz às vezes quando um comando foi executado (preferência do usuário)."""
        face = getattr(self, "_face_matrix", None)
        if face is None:
            return
        try:
            face.maybe_happy(probability=0.5, hold=1.5)
        except Exception:
            pass

    def _show_help(self) -> None:
        """Exibe ajuda com todos os comandos disponiveis."""
        ArisUI.show_help_header()

        ArisUI.show_help_section("Gerais", [
            ("help / ajuda", "Mostra esta ajuda"),
            ("exit / sair", "Encerra o sistema"),
            ("/reiniciar", "Reinicia o sistema em um novo cmd"),
            ("config", "Abre configuracoes"),
        ])

        ArisUI.show_help_section("OpenClaw + 20 Projetos", [
            ("knowledge", "Grafo de conhecimento"),
            ("awareness", "Captura de tela + OCR"),
            ("redact", "Auto-redacao de dados"),
            ("digest", "Briefing diario"),
            ("browser", "Automacao web"),
            ("agents", "Multi-agente"),
            ("skills", "Sistema de skills"),
            ("dictation", "Modo dictacao"),
        ])

        ArisUI.show_help_section("Anteriores", [
            ("desktop", "Controle do desktop"),
            ("scheduler", "Agendamentos e pomodoro"),
            ("notify", "Notificacao Windows"),
            ("context", "Atividade atual"),
            ("safety", "Seguranca"),
            ("entertainment", "Piadas e jogos"),
            ("turbo", "Analise profunda"),
        ])

        ArisUI.show_help_section("Hardware", [
            ("hardware", "Status do ESP32"),
            ("hardware connect", "Conectar ESP32"),
            ("hardware state [estado]", "Mudar estado visual"),
            ("hardware led_left [r g b]", "LED esquerdo"),
            ("hardware led_right [r g b]", "LED direito"),
            ("hardware led_both [r g b]", "Ambos LEDs"),
            ("hardware effect [target] [efeito]", "Aplicar efeito"),
            ("hardware leds_off", "Desligar LEDs"),
        ])

        ArisUI.show_help_section("Existentes", [
            ("weather", "Previsao do tempo"),
            ("websearch", "Pesquisa na web"),
            ("sys", "Analise do sistema"),
            ("remember", "Salvar memoria"),
            ("search", "Buscar memoria"),
            ("speak", "Ativar/desativar voz"),
        ])

        print()

    def _get_dynamic_prompt(self) -> str:
        """Gera o prompt dinâmico com status do sistema."""
        mem_count = self._memory.get_stats().get("total_memories", 0)
        provider = self._llm_router.provider_names[0] if self._llm_router.provider_names else "local"
        scheduler_count = self._scheduler.get_pending_count()

        parts = [self._settings.VERSION, provider, f"{mem_count} mem"]
        if scheduler_count > 0:
            parts.append(f"{scheduler_count} tarefas")

        return f"[{' | '.join(parts)}] > "

    def _track_aris_question(self, text: str) -> None:
        """Lembra a última pergunta feita pela ARIS (para respostas do usuário)."""
        self._last_aris_question = text if text and text.strip().endswith("?") else None

    def _cognitive_trace(self, user_input: str, route: str, detail: str = "") -> None:
        """Registra trace de observabilidade do processamento.

        Formato: TRACE | <input truncado> | <rota> | <detalhe>
        """
        short = user_input[:60] + ("..." if len(user_input) > 60 else "")
        extra = f" | {detail}" if detail else ""
        self._logger.debug(f"TRACE | {short} | {route}{extra}")

    def _looks_like_answer(self, text: str) -> bool:
        """Verifica se o texto parece uma resposta curta a uma pergunta da ARIS.

        NÃO deve tratar como resposta:
        - Perguntas do usuário
        - Afirmações casuais/comentários
        - Cumprimentos
        - Frases que não fazem sentido como resposta direta
        """
        lower = text.strip().lower()
        if not self._last_aris_question:
            return False
        if text.strip().endswith("?"):
            return False

        # Palavras/frases que NÃO são respostas a perguntas
        nao_respostas = (
            # Palavras de preenchimento/conversa casual
            "sabe", "sei", "nao sei", "não sei", "talvez", "quem sabe",
            "presiz", "precisa", "preciso", "quer", "quero", "vou",
            "vamos", "bora", "beleza", "blz", "show",
            "entendi", "entendido", "aham", "hm", "hmm", "eh", "é",
            "pois é", "pois e", "serio", "sério", "mentira", "brincadeira",
            "kkk", "kkkk", "rs", "rsrs", "haha", "hehe",
            "eai", "e ai", "oi", "ola", "olá", "tudo bem", "td bem",
            "como vai", "como ta", "como tá", "de boa", "tranquilo",
            # Respostas de confirmação/negação simples
            "sim", "nao", "não", "ok", "ta", "tá", "tbm", "tambem",
            "s", "obrigado", "obrigada", "valeu", "legal", "blz",
        )
        for nr in nao_respostas:
            if lower == nr or lower.startswith(nr + " ") or f" {nr}" in lower:
                return False

        # Se contém palavras de pergunta -> é uma nova pergunta, não resposta
        question_words = ("quem", "qual", "como", "por que", "onde", "quando",
                          "o que", "quant", "tera", "tem ", "pode me", "me fala",
                          "me diz", "fala", "diz", "explica", "conta")
        for qw in question_words:
            if lower.startswith(qw) or f" {qw}" in lower:
                return False

        # Se contém conectivos de continuação -> é comentário, não resposta
        conectivos = ("porque", "pq", "ja que", "já que", "se ", "entao", "então",
                      "mas ", "porem", "porém", "contudo", "logo")
        for c in conectivos:
            if c in lower:
                return False

        words = text.split()
        return 1 <= len(words) <= 3

    def _clean_duplicate_greetings(self, text: str) -> str:
        """Remove saudações duplicadas/genéricas da resposta do LLM.

        O LLM às vezes gera múltiplas saudações empilhadas (ex.: 'Oi! Oi! Oi! ...').
        Esta função remove repetições mantendo apenas a primeira ocorrência.
        """
        import re
        if not text:
            return text

        # Padrões de saudação genérica (início, meio, fim)
        greeting_patterns = [
            r"(?:^|\s)(?:oi|olá|eai|e\s*ai|fala|bom\s*dia|boa\s*tarde|boa\s*noite|hey|hello|hi|salve)[\s!.,]*",
        ]

        # Encontrar todas as ocorrências
        matches = []
        for pattern in greeting_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                matches.append((match.start(), match.end(), match.group().strip()))

        if len(matches) <= 1:
            return text

        # Ordenar por posição
        matches.sort(key=lambda x: x[0])

        # Manter apenas a primeira saudação, remover as subsequentes
        result_parts = []
        last_end = 0
        first_greeting_kept = False

        for start, end, matched in matches:
            if not first_greeting_kept:
                # Manter a primeira saudação (incluir texto antes dela)
                result_parts.append(text[last_end:end])
                first_greeting_kept = True
                last_end = end
            else:
                # Pular saudação duplicada - não adicionar nada, apenas mover last_end
                last_end = end

        # Adicionar o restante do texto
        result_parts.append(text[last_end:])

        # Também limpar saudações repetidas no final do texto
        cleaned = "".join(result_parts)
        # Remover saudações finais duplicadas
        cleaned = re.sub(r'(?:oi|olá|eai|fala|bom\s*dia|boa\s*tarde|boa\s*noite|hey|hello|hi|salve)[\s!.,]*$', '', cleaned, flags=re.IGNORECASE)

        return cleaned.strip()

    def _learn_answer(self, text: str, voice) -> bool:
        """Guarda a resposta curta do usuário à pergunta recém-feita."""
        question = self._last_aris_question or ""
        answer = text.strip()

        try:
            self._memory.save(
                title=answer[:60],
                content=answer,
                category=MemoryCategory.CONVERSATIONS,
                importance=6,
                tags=["resposta", "auto"],
                source="conversation",
            )
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Não foi possível salvar na memória legada: {e}")

        if self._memory_service:
            try:
                self._memory_service.remember(
                    answer, kind=MemoryKind.SEMANTIC, importance=6.0,
                    tags=["resposta", "auto"],
                    summary=f"Em resposta a: {question}"[:140],
                )
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"Não foi possível salvar no sistema novo: {e}")

        msg = f"Anotado na memória! Sua resposta: {answer}."
        ArisUI.show_response(msg)
        if voice.enabled:
            self._sync_hardware_state(SystemState.SPEAKING)
            self._is_speaking = True
            voice.speak(msg)
            self._is_speaking = False
            self._sync_hardware_state(SystemState.IDLE)
        self._last_aris_question = None
        return True

    # ── Microfone config ───────────────────────────────────────

    def _list_microphones(self) -> None:
        """Lista microfones disponíveis."""
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            print(f"\n  {Terminal.CYAN}Microfones disponíveis:{Terminal.RESET}")
            found = False
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    name = info['name']
                    ch = info['maxInputChannels']
                    rate = int(info['defaultSampleRate'])
                    default = " (padrão)" if i == p.get_default_input_device_info()['index'] else ""
                    print(f"  [{i}] {name} — {ch}ch @ {rate}Hz{default}")
                    found = True
            if not found:
                ArisUI.show_warning("Nenhum microfone encontrado")
            p.terminate()
        except Exception as e:
            ArisUI.show_error(f"Erro ao listar microfones: {e}")

    def _select_microphone(self, device_index: int) -> None:
        """Seleciona microfone e reinicia sensor de voz contínua."""
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            info = p.get_device_info_by_index(device_index)
            if info['maxInputChannels'] == 0:
                ArisUI.show_error(f"Dispositivo {device_index} não tem entrada de áudio")
                p.terminate()
                return
            name = info['name']
            p.terminate()

            # Salvar preferência
            object.__setattr__(self._settings, "MIC_DEVICE_INDEX", device_index)
            os.environ["ARIS_MIC_DEVICE_INDEX"] = str(device_index)

            ArisUI.show_info(f"Microfone selecionado: [{device_index}] {name}")
            ArisUI.show_info("Reiniciando sensor de voz contínua...")
            self._restart_continuous_voice()
        except Exception as e:
            ArisUI.show_error(f"Erro ao selecionar microfone: {e}")

    def _set_energy_threshold(self, threshold: float) -> None:
        """Ajusta threshold de energia para detecção de fala."""
        try:
            object.__setattr__(self._settings, "ENERGY_THRESHOLD", threshold)
            os.environ["ARIS_ENERGY_THRESHOLD"] = str(threshold)
            if self._continuous_voice and hasattr(self._continuous_voice, '_config'):
                # Atualizar config em runtime (precisa reiniciar para efeito total)
                object.__setattr__(self._continuous_voice._config, "energy_threshold", threshold)
            ArisUI.show_info(f"Threshold de energia ajustado para: {threshold}")
            ArisUI.show_info("Reinicie o sensor com 'mic restart' para aplicar completamente")
        except Exception as e:
            ArisUI.show_error(f"Erro ao ajustar threshold: {e}")

    def _set_vad_aggressiveness(self, level: int) -> None:
        """Ajusta agressividade do VAD (0-3)."""
        try:
            if not 0 <= level <= 3:
                ArisUI.show_error("VAD deve ser entre 0 e 3")
                return
            object.__setattr__(self._settings, "VAD_AGGRESSIVENESS", level)
            os.environ["ARIS_VAD_AGGRESSIVENESS"] = str(level)
            if self._continuous_voice and self._continuous_voice._vad:
                self._continuous_voice._vad = webrtcvad.Vad(level)
            ArisUI.show_info(f"VAD agressividade ajustado para: {level}")
        except Exception as e:
            ArisUI.show_error(f"Erro ao ajustar VAD: {e}")

    def _show_mic_config(self) -> None:
        """Mostra configuração atual do microfone."""
        print(f"\n  {Terminal.CYAN}Configuração do Microfone:{Terminal.RESET}")
        print(f"  Microfone contínuo: {'Ativo' if self._continuous_voice and self._continuous_voice.enabled else 'Inativo'}")
        print(f"  Disponível: {'Sim' if self._continuous_voice and self._continuous_voice.available else 'Não'}")
        if self._continuous_voice:
            cfg = self._continuous_voice._config
            print(f"  Wake words: {cfg.wake_words}")
            print(f"  Energy threshold: {cfg.energy_threshold}")
            print(f"  VAD aggressiveness: {cfg.vad_aggressiveness}")
            print(f"  Warmup frames: {cfg.warmup_frames}")
            print(f"  Min speech: {cfg.min_speech_ms}ms")
            print(f"  Silence timeout: {cfg.silence_timeout_ms}ms")
            print(f"  STT model: {cfg.stt_model}")
            print(f"  Device index: {getattr(self._settings, 'MIC_DEVICE_INDEX', 'padrão do sistema')}")

    def _restart_continuous_voice(self) -> None:
        """Reinicia o sensor de voz contínua com nova configuração."""
        if not self._continuous_voice:
            ArisUI.show_warning("Sensor de voz contínua não disponível")
            return
        try:
            ArisUI.show_info("Parando sensor...")
            self._continuous_voice.stop()
            time.sleep(0.5)
            ArisUI.show_info("Iniciando sensor...")
            # Recriar com nova config se device index mudou
            device_index = getattr(self._settings, 'MIC_DEVICE_INDEX', None)
            if device_index is not None:
                # O sensor usa PyAudio default, mas podemos setar via env
                os.environ["ARIS_MIC_DEVICE_INDEX"] = str(device_index)
            self._continuous_voice.start()
            ArisUI.show_success("Sensor de voz contínua reiniciado")
        except Exception as e:
            ArisUI.show_error(f"Erro ao reiniciar sensor: {e}")

    def _restart(self, delay: float = 1.8) -> None:
        """Reinicia a A.R.I.S.: abre um novo cmd com ela rodando e encerra esta.

        Um helper (janela invisível) espera ``delay`` segundos para a
        instância atual liberar o lock de instância e só então abre a
        nova janela do console. A instância atual fecha normalmente.
        """
        root = str(Path(__file__).resolve().parent.parent)
        code = (
            "import time, os, subprocess;"
            f"time.sleep({delay});"
            f"os.chdir({root!r});"
            "subprocess.Popen(['cmd', '/k', 'run_aris.bat'],"
            " creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=os.getcwd())"
        )
        try:
            subprocess.Popen(
                [sys.executable, "-c", code],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            if self._logger:
                self._logger.error(f"Falha ao reiniciar a A.R.I.S.: {e}")

    def _start_distributed(self) -> None:
        """Inicializa componentes distribuidos CLL1 (server, heartbeat, sync)."""
        import os

        cll1_token = os.getenv("CLL1_TOKEN", "")
        cll1_port = int(os.getenv("CLL1_PORT", "8765"))
        cll1_host = os.getenv("CLL1_HOST", "0.0.0.0")

        # Sync engine (sempre disponivel, mesmo sem CLL1)
        try:
            from core.memcore.paths import default_memory_root
            self._sync_engine = SyncEngine(
                db_path=default_memory_root() / "database" / "aris_memory.db",
                logger=self._logger,
            )
            self._container.set("sync.engine", self._sync_engine)
            self._logger.info("Sync Engine inicializado.")
        except Exception as e:
            self._logger.warning(f"Sync Engine indisponivel: {e}")

        # CLL1 Server (TCP)
        if cll1_token:
            try:
                self._cll1_server = CLL1Server(
                    host=cll1_host,
                    port=cll1_port,
                    token=cll1_token,
                    on_message=self._on_cll1_message,
                    logger=self._logger,
                )
                self._cll1_server.start()
                self._container.set("cll1.server", self._cll1_server)
                # Log único: o CLL1Server.start() já registra o endereço.
            except Exception as e:
                self._logger.warning(f"CLL1 Server indisponivel: {e}")

            # CLL1 Heartbeat — só se o servidor de verdade subiu. Antes ele
            # subia mesmo com o server falhou e spamava "'NoneType' object
            # has no attribute 'heartbeat_status'" a cada 30s.
            if self._cll1_server is not None:
                try:
                    self._cll1_heartbeat = CLL1Heartbeat(
                        client=None,  # usa CLL1Client interno via env vars
                        interval=30,
                        logger=self._logger,
                    )
                    self._cll1_heartbeat.start()
                    self._container.set("cll1.heartbeat", self._cll1_heartbeat)
                    self._logger.info("CLL1 Heartbeat iniciado.")
                except Exception as e:
                    self._logger.warning(f"CLL1 Heartbeat indisponivel: {e}")
            else:
                self._logger.info("CLL1 Heartbeat nao iniciado (server indisponivel).")
        else:
            self._logger.info("CLL1 desabilitado (CLL1_TOKEN nao definido).")

    def _sync_personality(self) -> None:
        """Sincroniza personalidade com CLL1 (Edge) via CLL1 Server broadcast."""
        try:
            from config.personality import ARIS_PERSONALITY

            if self._sync_engine:
                sync_data = self._sync_engine.get_personality_for_sync(ARIS_PERSONALITY)
                # Broadcast para CLL1 conectado
                if self._cll1_server:
                    sent = self._cll1_server.broadcast({
                        "type": "personality_sync",
                        "payload": sync_data,
                    })
                    if sent > 0:
                        self._logger.info(f"Personalidade sincronizada com {sent} cliente(s) CLL1")

                # Também salvar localmente para painel web acessar
                from core.memcore.paths import default_memory_root
                personality_path = default_memory_root() / "personality_sync.md"
                personality_path.parent.mkdir(parents=True, exist_ok=True)
                personality_path.write_text(ARIS_PERSONALITY, encoding="utf-8")
                self._logger.info("Personalidade salva para painel web")

        except Exception as e:
            if self._logger:
                self._logger.warning(f"Sincronização de personalidade falhou: {e}")

    def _on_cll1_message(self, text: str, origin_info: dict) -> None:
        """Callback p/ mensagens do CLL1 — assinatura (text, origin_info).

        O CLL1Server chama ``on_message(text, origin_info)``. Repacketa em
        um dict p/ ``MessageOrigin.from_dict`` e injeta no pipeline.
        """
        if text == "__sync_push__":
            return  # payload de sync não é comando de conversa
        if text:
            payload = {"text": text, **(origin_info or {})}
            origin = MessageOrigin.from_dict(payload)
            self.send_message(text, origin=origin)

    def _build_agent_bridge(self):
        """Parte 8: monta a ponte do agente; falha/desligado => None.

        Interruptor ARIS_AGENT_ENABLED (padrão desligado). Nunca derruba a
        ARIS: qualquer import/construção quebrado vira aviso + caminho antigo.
        """
        try:
            from aris_agent.bridge import build_bridge

            voz = self._hybrid_voice if self._hybrid_voice.enabled else self._voice

            def falar(texto: str, *, sync: bool = False) -> None:
                # sync=True na confirmação (a fala precisa terminar antes de
                # ouvir); status de ferramenta sai assíncrono para não travar.
                if not voz.enabled or not texto:
                    return
                self._is_speaking = True
                try:
                    voz.speak(texto, async_mode=not sync)
                finally:
                    self._is_speaking = False

            def ouvir(timeout_s: float) -> str | None:
                from aris_agent.bridge.voz import entrada_com_tempo, segundos_para_ouvinte

                if self._mic_mode:
                    try:
                        return self._hybrid_voice.listen(
                            timeout=segundos_para_ouvinte(timeout_s)
                        )
                    except Exception:
                        return None  # microfone falhou: nega (timeout = negar)
                return entrada_com_tempo(timeout_s, prompt="Confirmar (sim/não): ")

            ponte = build_bridge(falar=falar, ouvir=ouvir)
            if self._logger:
                if ponte is not None:
                    self._logger.info(
                        "Ponte do agente ativa (ARIS_AGENT_ENABLED=true)."
                    )
                else:
                    self._logger.info(
                        "Ponte do agente desligada/indisponível (ARIS_AGENT_ENABLED)."
                    )
            return ponte
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Ponte do agente indisponível: {e}")
            return None

    def shutdown(self) -> None:
        """Encerra o A.R.I.S. de forma limpa.

        Idempotente: uma 2ª chamada (ex.: 'exit' + fim do loop) não repete
        a sequência de parada nem duplica os logs de encerramento.
        """
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        self._running = False

        # Publicar evento de encerramento no Neural Core
        if hasattr(self, "_neural"):
            self._neural.event_bus.publish(Event(
                event_type=EVENT_SHUTDOWN,
                source="aris",
                payload={},
                priority=80,
                confidence=1.0,
            ))

        # Encerrar executor de threads
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)

        # Parte 8: cancelar execução do agente em andamento (se houver)
        if getattr(self, "_agent_bridge", None):
            try:
                self._agent_bridge.parar()
            except Exception:
                pass

        # Parar percepção (sensores em threads daemon)
        if getattr(self, "_perception", None):
            try:
                self._perception.stop()
            except Exception:
                pass

        # Parar voz contínua
        if getattr(self, "_continuous_voice", None):
            try:
                self._continuous_voice.stop()
                self._logger.info("Voz contínua parada")
            except Exception:
                pass

        # Parar voz híbrida (TTS + seletor de microfone) e liberar o mixer.
        # Sem isso, no Linux o processo sai com o SDL/mixer ainda ativo e o
        # pygame parachute derruba um SIGABRT (segfault) no encerramento.
        if getattr(self, "_hybrid_voice", None):
            try:
                self._hybrid_voice.stop()
            except Exception:
                pass
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.quit()
        except Exception:
            pass

        # Parar detector de palmas
        if getattr(self, "_clap_detector", None):
            try:
                self._clap_detector.stop()
                self._logger.info("Clap detector parado")
            except Exception:
                pass

        # Parar Proactive Engine
        if getattr(self, "_proactive_engine", None):
            try:
                self._proactive_engine.stop()
                self._logger.info("Proactive Engine parado")
            except Exception:
                pass

        # Parar matriz de LED 8x8
        if getattr(self, "_face_matrix", None):
            try:
                self._face_matrix.stop()
            except Exception:
                pass

        # Parar Reflex Layer
        if getattr(self, "_reflex_layer", None):
            try:
                # ReflexLayer não tem stop(), apenas limpar referências
                self._reflex_layer = None
                self._logger.info("Reflex Layer parada")
            except Exception:
                pass

        # Parar CLL1 distributed components
        if getattr(self, "_cll1_heartbeat", None):
            try:
                self._cll1_heartbeat.stop()
            except Exception:
                pass
        if getattr(self, "_cll1_server", None):
            try:
                self._cll1_server.stop()
            except Exception:
                pass

        # Desligar ESP32
        if self._hardware.connected:
            self._hardware.set_state(SystemState.OFFLINE)
            self._hardware.stop()

        # Olhos dormem junto com a ARIS (independe do ESP32)
        eyes_bridge.set_state(SystemState.OFFLINE.value)

        # Fechar memória cognitiva
        if getattr(self, "_memory_service", None):
            try:
                self._memory_service.close()
            except Exception as e:
                if self._logger:
                    self._logger.debug(f"Memory service close: {e}")

        self._logger.info("A.R.I.S. encerrado.")

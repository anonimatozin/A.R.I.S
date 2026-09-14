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
from pathlib import Path

import core.handlers  # noqa: F401 — auto-registra todos os handlers
from config.esp32_config import ESP32Config
from config.settings import Settings
from core.advanced_interpreter import AdvancedInterpreter
from core.commands import registry
from core.advanced_interpreter import Intent
from core.memcore import MemoryKind
from core.memory import MemoryManager
from core.memory_models import MemoryCategory
from core.memory_organizer import MemoryOrganizer
from core.greeting import GreetingService
from core.gmail import GmailService
from core.llm import LLMRouter
from core.module_manager import ModuleManager
from core.multi_provider import MultiProviderChat
from core.neural import NeuralCore
from core.neural.events import (
    EVENT_BOOT,
    EVENT_SHUTDOWN,
    EVENT_TIMER_FINISHED,
    Event,
)
from core.perception import PerceptionConfig, PerceptionManager
from core.services import ServiceContainer
from modules.auto_redaction import AutoRedaction
from modules.browser_automation import BrowserAutomation
from modules.chat import Chat
from modules.context_detector import ContextDetector
from modules.desktop_awareness import DesktopAwareness
from modules.desktop_tools import DesktopTools
from modules.dictation_mode import DictationMode
from modules.entertainment import Entertainment
from modules.esp32_hardware import HardwareManager, SystemState
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

        self._voice = Voice(
            rate=self._settings.VOICE_RATE,
            volume=self._settings.VOICE_VOLUME,
        )

        self._hybrid_voice = HybridVoice(
            rate=self._settings.VOICE_RATE,
            volume=self._settings.VOICE_VOLUME,
        )

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

        # Gmail (read-only)
        self._gmail = GmailService(
            client_id=os.getenv("ARIS_GMAIL_CLIENT_ID", ""),
            client_secret=os.getenv("ARIS_GMAIL_CLIENT_SECRET", ""),
            safety_manager=self._safety,
            auth_port=int(os.getenv("ARIS_GMAIL_AUTH_PORT", "8741")),
        )
        if self._gmail.is_configured:
            self._gmail.load_stored_tokens()

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
        ):
            self._container.set(name, instance)

    def send_message(self, text: str) -> None:
        """Enfileira uma mensagem para processamento assíncrono.

        Pode ser chamado de qualquer thread. O loop principal consome
        a fila via _get_input() a cada iteração.
        """
        self._input_queue.put(text)

    def _get_input(self, mic_mode: bool = False) -> str:
        """Obtém próxima entrada: fila assíncrona primeiro, depois blocking input.

        Retorna string vazia se nada disponível (não-bloqueante na fila).
        """
        # 1. Fila assíncrona (não-bloqueante)
        try:
            return self._input_queue.get_nowait()
        except queue.Empty:
            pass

        # 2. Input do usuário (bloqueante)
        if mic_mode:
            if self._hybrid_voice._recognizer is None:
                return ""
            print("  Escutando...", end="\r")
            result = self._hybrid_voice.listen(timeout=6) or ""
            print(" " * 60, end="\r")
            if result:
                print(f"  Voce disse: {result}")
            return result
        else:
            return ArisUI.input_modern(
                version=self._settings.VERSION,
                provider=self._llm_router.provider_names[0] if self._llm_router.provider_names else "local",
                mem_count=self._memory.get_stats().get("total_memories", 0),
                task_count=self._scheduler.get_pending_count(),
            )

    def _setup_signal_handlers(self) -> None:
        """Configura handlers para sinais do sistema."""
        def signal_handler(sig: int, frame: object) -> None:
            self._logger.info("Sinal de interrupção recebido. Encerrando...")
            self.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal_handler)

    def _build_handler_context(self) -> dict:
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
            "event_bus": self._neural.event_bus,
            "state": self._neural.state,
            "perception": self._perception,
            "vision": self._vision,
            "multi_chat": self._multi_chat,
            "llm_router": self._llm_router,
            "gmail": self._gmail,
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

        return ctx

    def _execute_intent(self, intent: Intent) -> str | None:
        """Executa uma intenção detectada pela IA.

        Delega para o CommandRegistry através do Neural Core (Security
        Gate + Ação + Feedback). Se o handler não existe, cai no
        fallback legacy. Retorna o resumo falável do resultado.
        """
        module = intent.module
        params = intent.params

        ArisUI.show_action(module, intent.action, params)

        # Comando de saída (sempre funciona)
        if module == "exit":
            self.shutdown()
            return None

        # Tentar registry primeiro
        if registry.has_intent(module):
            ctx = self._build_handler_context()
            decision = self._neural.decision.decide(intent, source="llm")
            result = self._neural.execute(decision, ctx=ctx)
            if not result.success and result.error.startswith("Segurança:"):
                ArisUI.show_error(result.error)
                return None
            return result.output if result.success else None

        # Fallback: módulos sem handler registrado ainda
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
                voice.speak(suggestion)
        except Exception as e:
            if self._logger:
                self._logger.debug(f"Proactive suggestion skipped: {e}")

    def _execute_intent_legacy(self, intent: Intent) -> None:
        """Fallback: route through SecurityGate for unregistered handlers."""
        decision = self._neural.decision.decide(intent, source="llm_legacy")
        ctx = self._build_handler_context()
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

            # Estado inicial (sem logs falsos se hardware indisponível)
            self._hardware.set_state(SystemState.IDLE)
            self._neural.state.update_hardware(
                connected=self._hardware.connected,
                available=self._hardware.available,
            )
        else:
            self._neural.state.update_hardware(connected=False, available=False)

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

        # Exibir banner
        self._print_banner()

        # Saudação por voz
        voice = self._hybrid_voice if self._hybrid_voice.enabled else self._voice
        if voice.enabled:
            voice.speak("A.R.I.S. inicializado. Todos os sistemas operacionais.")

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

        while self._running:
            try:
                # Input: fila assíncrona, teclado ou microfone
                voice = self._hybrid_voice if self._hybrid_voice.enabled else self._voice
                if self._mic_mode and self._hybrid_voice._recognizer is None:
                    self._mic_mode = False
                user_input = self._get_input(mic_mode=self._mic_mode)

                if not user_input.strip():
                    continue

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
                        print("  🎙️ Modo voz ativado. Fale seus comandos. Digite 'modo texto' para voltar a digitar.")
                    else:
                        print("  ⚠️ Sem microfone disponível. Instale: pip install SpeechRecognition pyaudio")
                    continue
                if ui in ("modo texto", "voz off", "mic off", "desativar mic"):
                    self._mic_mode = False
                    print("  ⌨️ Modo digitação ativado.")
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

                # Neural Core: caminho determinístico (sem LLM)
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
                        ArisUI.show_response(neural_result.output)
                        if voice.enabled:
                            # Não falar texto que contenha URLs (evita ler link letra por letra)
                            if "http" not in neural_result.output.lower():
                                self._sync_hardware_state(SystemState.SPEAKING)
                                voice.speak(neural_result.output)
                                self._sync_hardware_state(SystemState.IDLE)
                        self._track_aris_question(neural_result.output)
                    elif neural_result.error:
                        ArisUI.show_error(neural_result.error)
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

                    # Mostrar quantas acoes foram detectadas
                    if len(intents) > 1:
                        ArisUI.show_actions_count(len(intents))

                    # Executar todas as intencoes na ordem
                    spoken_parts = []
                    for intent in intents:
                        part = self._execute_intent(intent)
                        if part:
                            spoken_parts.append(str(part))

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
                        ArisUI.show_response(clean_response)

                    if voice.enabled and speak_text and "http" not in speak_text.lower():
                        self._sync_hardware_state(SystemState.SPEAKING)
                        voice.speak(speak_text)
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

    # ── Estado visual → ESP32 ───────────────────────────────

    def _sync_hardware_state(self, state: SystemState) -> None:
        """Sincroniza estado do ARIS com ESP32."""
        if self._hardware.connected:
            self._hardware.set_state(state)

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
            voice.speak(msg)
            self._sync_hardware_state(SystemState.IDLE)
        self._last_aris_question = None
        return True

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

    def shutdown(self) -> None:
        """Encerra o A.R.I.S. de forma limpa."""
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

        # Parar percepção (sensores em threads daemon)
        if getattr(self, "_perception", None):
            try:
                self._perception.stop()
            except Exception:
                pass

        # Desligar ESP32
        if self._hardware.connected:
            self._hardware.set_state(SystemState.OFFLINE)
            self._hardware.stop()

        # Fechar memória cognitiva
        if getattr(self, "_memory_service", None):
            try:
                self._memory_service.close()
            except Exception as e:
                if self._logger:
                    self._logger.debug(f"Memory service close: {e}")

        self._logger.info("A.R.I.S. encerrado.")

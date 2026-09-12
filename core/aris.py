"""Classe principal do A.R.I.S.

Orquestra o funcionamento do sistema, gerenciando módulos,
comandos e a interface do terminal.
"""

import signal
import sys
import os
import concurrent.futures
from pathlib import Path

from config.settings import Settings
from config.esp32_config import ESP32Config
from core.module_manager import ModuleManager
from core.intent import IntentAnalyzer, Intent
from core.advanced_interpreter import AdvancedInterpreter
from core.commands import registry
import core.handlers  # noqa: F401 — auto-registra todos os handlers
from core.memory import MemoryManager
from core.memory_organizer import MemoryOrganizer
from core.memory_models import MemoryCategory, Priority
from core.multi_provider import MultiProviderChat
from modules.chat import Chat
from modules.desktop_tools import DesktopTools
from modules.scheduler import Scheduler, TaskPriority
from modules.notifications import NotificationManager
from modules.context_detector import ContextDetector
from modules.safety import SafetyManager
from modules.entertainment import Entertainment
from modules.turbo_mode import TurboMode
from modules.knowledge_graph import KnowledgeGraph
from modules.desktop_awareness import DesktopAwareness
from modules.auto_redaction import AutoRedaction
from modules.morning_digest import MorningDigest
from modules.browser_automation import BrowserAutomation
from modules.multi_agent import MultiAgentSystem
from modules.skills_system import SkillsSystem
from modules.dictation_mode import DictationMode
from modules.esp32_hardware import HardwareManager, SystemState
from system.analyzer import PersonalAnalyzer

from weather.hyper_weather import HyperWeather
from search.hyper_search import HyperSearch
from utils.logger import Logger
from utils.terminal import Terminal, ArisUI
from utils.voice import Voice
from utils.voice_hybrid import HybridVoice


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

        self._multi_chat = MultiProviderChat(logger=self._logger)

        self._chat = Chat(
            api_key=self._settings.GROQ_API_KEY,
            model=self._settings.CHAT_MODEL,
            logger=self._logger,
            memory=self._memory,
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

        self._intent = IntentAnalyzer()
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
        self._browser = BrowserAutomation(data_dir=self._settings.DATA_DIR)
        self._agents = MultiAgentSystem(data_dir=self._settings.DATA_DIR)
        self._skills = SkillsSystem(data_dir=self._settings.DATA_DIR)
        self._dictation = DictationMode()

        # Hardware ESP32
        self._esp32_config = ESP32Config()
        self._hardware = HardwareManager(config=self._esp32_config, logger=self._logger)

        if self._settings.SAFETY_PASSWORD:
            self._safety.set_master_password(self._settings.SAFETY_PASSWORD)

        # Conectar safety ao registry
        registry.set_safety(self._safety)

        self._running = False
        self._setup_signal_handlers()

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
            "voice": self._voice,
            "settings": self._settings,
            "hardware": self._hardware,
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

    def _execute_intent(self, intent: Intent) -> None:
        """Executa uma intenção detectada pela IA.

        Delega para o CommandRegistry. Se o handler não existe,
        cai no fallback legacy.
        """
        module = intent.module
        params = intent.params

        ArisUI.show_action(module, intent.action, params)

        # Comando de saída (sempre funciona)
        if module == "exit":
            self.shutdown()
            return

        # Tentar registry primeiro
        if registry.has_intent(module):
            ctx = self._build_handler_context()
            result = registry.execute_intent(
                module=module,
                action=intent.action,
                params=params,
                **ctx,
            )
            return

        # Fallback: módulos sem handler registrado ainda
        self._execute_intent_legacy(intent)

    def _execute_intent_legacy(self, intent: Intent) -> None:
        """Fallback legado para módulos que ainda não foram migrados."""
        module = intent.module
        params = intent.params

    def _print_banner(self) -> None:
        """Exibe o banner inicial do sistema."""
        ArisUI.show_banner(self._settings.VERSION)

    def start(self) -> None:
        """Inicia o A.R.I.S."""
        self._logger.info("Iniciando A.R.I.S.")

        # Carregar módulos
        self._module_manager.load_modules()

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

            # Estado inicial
            self._hardware.set_state(SystemState.IDLE)

        # Iniciar scheduler em background
        self._scheduler.start_checker(callback=self._on_task_due)

        # Exibir banner
        self._print_banner()

        # Saudação por voz
        voice = self._hybrid_voice if self._hybrid_voice.enabled else self._voice
        if voice.enabled:
            voice.speak("A.R.I.S. inicializado. Todos os sistemas operacionais.")

        # Status do provider
        provider_status = self._multi_chat.get_status()
        if provider_status["providers"]:
            active = provider_status["current"]
            print(f"  Provider ativo: {Terminal.colorize(active, Terminal.CYAN)}")
        print()

        # Loop principal
        self._running = True
        self._logger.info("Sistema pronto para recebimento de comandos.")
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="aris-llm")

        while self._running:
            try:
                # Input moderno com status
                user_input = ArisUI.input_modern(
                    version=self._settings.VERSION,
                    provider=self._multi_chat.provider_name if self._multi_chat.available else "local",
                    mem_count=self._memory.get_stats().get("total_memories", 0),
                    task_count=self._scheduler.get_pending_count(),
                )

                if not user_input.strip():
                    continue

                # Safety: exit sempre funciona
                if user_input.strip().lower() in ("exit", "sair", "encerrar", "desligar"):
                    self.shutdown()
                    break

                # Comandos diretos do terminal
                if user_input.strip().lower() in ("help", "ajuda", "comandos"):
                    self._show_help()
                    continue

                # Enviar tudo para a IA interpretar
                chat = self._multi_chat if self._multi_chat.available else self._chat
                if chat.available or (hasattr(chat, 'available') and chat.available):
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
                    for intent in intents:
                        self._execute_intent(intent)

                    # Atualizar contexto da conversa
                    self._interpreter.update_context(user_input, clean_response, intents)

                    # Mostrar resposta formatada
                    if clean_response:
                        ArisUI.show_response(clean_response)

                    if voice.enabled and clean_response:
                        self._sync_hardware_state(SystemState.SPEAKING)
                        voice.speak(clean_response)

                    # Estado: idle
                    self._sync_hardware_state(SystemState.IDLE)

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
        print(f"  Provider: {self._multi_chat.provider_name}")
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
        provider = self._multi_chat.provider_name if self._multi_chat.available else "local"
        scheduler_count = self._scheduler.get_pending_count()
        context = self._context.format_context().split("\n")[0] if self._context else ""

        parts = [self._settings.VERSION, provider, f"{mem_count} mem"]
        if scheduler_count > 0:
            parts.append(f"{scheduler_count} tarefas")

        return f"[{' | '.join(parts)}] > "

    def shutdown(self) -> None:
        """Encerra o A.R.I.S. de forma limpa."""
        self._running = False

        # Encerrar executor de threads
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)

        # Desligar ESP32
        if self._hardware.connected:
            self._hardware.set_state(SystemState.OFFLINE)
            self._hardware.stop()

        self._logger.info("A.R.I.S. encerrado.")

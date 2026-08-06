"""Classe principal do J.A.R.V.I.S.

Orquestra o funcionamento do sistema, gerenciando módulos,
comandos e a interface do terminal.
"""

import signal
import sys
import os
from pathlib import Path

from config.settings import Settings
from core.module_manager import ModuleManager
from core.intent import IntentAnalyzer, Intent
from core.memory import MemoryManager
from core.memory_organizer import MemoryOrganizer
from core.memory_models import MemoryCategory, Priority
from modules.chat import Chat
from system.analyzer import PersonalAnalyzer
from hud.display import HUD
from hud.settings_menu import SettingsMenu
from weather.hyper_weather import HyperWeather
from search.hyper_search import HyperSearch
from utils.logger import Logger
from utils.terminal import Terminal
from utils.voice import Voice


class Jarvis:
    """Classe principal do assistente J.A.R.V.I.S.

    Responsável por inicializar todos os subsistemas,
    carregar módulos e executar o loop principal.
    """

    def __init__(self) -> None:
        """Inicializa o J.A.R.V.I.S. com todas as dependências."""
        self._settings = Settings()
        self._settings.ensure_directories()

        self._logger = Logger(
            name="jarvis",
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

        self._memory = MemoryManager(
            logger=self._logger,
            memory_root=self._settings.MEMORY_ROOT,
        )

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
        self._hud = HUD(analyzer=self._analyzer)
        self._weather = HyperWeather(api_keys={
            "openweather": os.getenv("OPENWEATHER_API_KEY", ""),
            "weatherapi": os.getenv("WEATHERAPI_KEY", ""),
        })
        self._search = HyperSearch(api_keys={
            "serpapi": os.getenv("SERPAPI_KEY", ""),
        })

        self._intent = IntentAnalyzer()

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

    def _execute_intent(self, intent: Intent) -> None:
        """Executa uma intenção detectada pela IA.

        Args:
            intent: Intenção a ser executada.
        """
        module = intent.module
        params = intent.params

        if module == "weather":
            city = params.get("city", "")
            if city:
                report = self._weather.format_report(city)
                print()
                for line in report.split("\n"):
                    print(f"  {line}")
                print()

        elif module == "websearch":
            query = params.get("query", "")
            if query:
                result = self._search.search_and_summarize(query)
                print()
                for line in result.split("\n"):
                    print(f"  {line}")
                print()

        elif module == "sys":
            report = self._analyzer.get_full_report()
            Terminal.print_separator()
            Terminal.print_centered("ANÁLISE DO SISTEMA")
            Terminal.print_separator()
            cpu = report["cpu"]
            print(f"  CPU: {cpu['cores_physical']}C/{cpu['cores_logical']}T @ {cpu['frequency_mhz']:.0f}MHz")
            print(f"       Uso: {Terminal.colorize(str(cpu['usage_percent']) + '%', Terminal.CYAN)}")
            mem = report["memory"]
            print(f"  RAM: {mem['used_gb']:.1f}GB / {mem['total_gb']:.1f}GB ({mem['percent']}%)")
            disk = report["disk"]
            print(f"  Disco: {disk['used_gb']:.1f}GB / {disk['total_gb']:.1f}GB ({disk['percent']}%)")
            net = report["network"]
            print(f"  Rede: ↓{net['bytes_recv_gb']:.2f}GB ↑{net['bytes_sent_gb']:.2f}GB")
            bat = report["battery"]
            if bat["percent"] is not None:
                print(f"  Bateria: {bat['percent']:.0f}% {'(carregando)' if bat['plugged'] else ''}")
            print(f"  Processos: {report['processes']}")
            print()
            alerts = self._analyzer.diagnose()
            for alert in alerts:
                color = Terminal.RED if "CRÍTICO" in alert else Terminal.YELLOW if "AVISO" in alert else Terminal.GREEN
                print(f"  {Terminal.colorize(alert, color)}")
            Terminal.print_separator()

        elif module == "hud":
            self._hud.render()
            Terminal.input_prompt("  Pressione Enter para voltar...")

        elif module == "remember":
            text = params.get("text", "")
            if text:
                importance = 5
                category = MemoryCategory.KNOWLEDGE
                tags = []
                text_lower = text.lower()
                if any(w in text_lower for w in ["meu nome", "me chamo", "sou o", "pode me chamar"]):
                    category = MemoryCategory.PROFILE
                    importance = 10
                    tags = ["perfil", "pessoal"]
                elif any(w in text_lower for w in ["projeto", "código", "script"]):
                    category = MemoryCategory.PROJECTS
                    importance = 8
                    tags.append("projeto")
                elif any(w in text_lower for w in ["dispositivo", "esp32", "arduino"]):
                    category = MemoryCategory.DEVICES
                    importance = 8
                    tags.append("dispositivo")
                elif any(w in text_lower for w in ["config", "configuração", "preferência"]):
                    category = MemoryCategory.CONFIG
                    importance = 10
                    tags.append("configuração")
                entry = self._memory.save(
                    title=text[:50],
                    content=text,
                    category=category,
                    importance=importance,
                    tags=tags,
                )
                print(f"  Memória salva: {Terminal.colorize(entry.id, Terminal.CYAN)}")

        elif module == "search":
            query = params.get("query", "")
            if query:
                results = self._memory.search(query=query)
                if not results:
                    print("  Nenhuma memória encontrada.")
                else:
                    Terminal.print_separator()
                    for entry in results:
                        imp_color = Terminal.GREEN if entry.importance >= 7 else Terminal.YELLOW
                        print(f"  [{Terminal.colorize(entry.id, Terminal.CYAN)}] {entry.title}")
                        print(f"    {entry.category.value} | Imp: {Terminal.colorize(str(entry.importance), imp_color)}")
                    Terminal.print_separator()

        elif module == "config":
            menu = SettingsMenu(env_path=self._settings.BASE_DIR / ".env")
            menu.show()

        elif module == "speak":
            if self._voice.enabled:
                self._voice.enabled = False
                print("  Voz desativada.")
            else:
                self._voice.enabled = True
                print("  Voz ativada.")

        elif module == "exit":
            self.shutdown()

    def _get_dynamic_prompt(self) -> str:
        """Gera o prompt dinâmico com status do sistema."""
        mem_count = self._memory.get_stats().get("total_memories", 0)
        model_short = self._settings.CHAT_MODEL.split("/")[-1][:15]
        return f"[{self._settings.VERSION} | {model_short} | {mem_count} mem] > "

    def _print_banner(self) -> None:
        """Exibe o banner inicial do sistema."""
        Terminal.clear()
        print(Terminal.colorize("╔" + "═" * 58 + "╗", Terminal.CYAN))
        print(Terminal.colorize("║" + " J.A.R.V.I.S. NEXUS ".center(58) + "║", Terminal.CYAN))
        print(Terminal.colorize("║" + " v" + self._settings.VERSION + " ".center(54) + "║", Terminal.CYAN))
        print(Terminal.colorize("╠" + "═" * 58 + "╣", Terminal.CYAN))
        print(Terminal.colorize("║" + " Todos os sistemas operacionais ".center(58) + "║", Terminal.CYAN))
        print(Terminal.colorize("║" + " Pronto para receber comandos ".center(58) + "║", Terminal.CYAN))
        print(Terminal.colorize("╚" + "═" * 58 + "╝", Terminal.CYAN))
        print()

    def start(self) -> None:
        """Inicia o J.A.R.V.I.S."""
        self._logger.info("Iniciando J.A.R.V.I.S.")

        # Carregar módulos
        self._module_manager.load_modules()

        # Exibir banner
        self._print_banner()

        # Saudação por voz
        if self._voice.enabled:
            self._voice.speak("J.A.R.V.I.S. inicializado. Todos os sistemas operacionais.")

        # Loop principal
        self._running = True
        self._logger.info("Sistema pronto para recebimento de comandos.")

        while self._running:
            try:
                user_input = Terminal.input_prompt(
                    prompt=self._get_dynamic_prompt(),
                    color=Terminal.CYAN,
                )

                if not user_input.strip():
                    continue

                # Safety: exit sempre funciona
                if user_input.strip().lower() in ("exit", "sair", "encerrar", "desligar"):
                    self.shutdown()
                    break

                # Enviar tudo para a IA interpretar
                if self._chat.available:
                    print()

                    intent_prompt = self._intent.build_intent_prompt(user_input)
                    response = self._chat.send(intent_prompt)

                    # Extrair intenções
                    clean_response, intents = self._intent.parse_ai_response(response)

                    # Executar intenções
                    for intent in intents:
                        self._execute_intent(intent)

                    # Mostrar resposta
                    if clean_response:
                        print(f"  {Terminal.colorize('J.A.R.V.I.S.:', Terminal.GREEN)} {clean_response}")
                        print()

                    if self._voice.enabled and clean_response:
                        self._voice.speak(clean_response)

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
                    print("Chat indisponível. Configure GROQ_API_KEY no .env.")

            except KeyboardInterrupt:
                print()
                continue
            except EOFError:
                break

        self.shutdown()

    def shutdown(self) -> None:
        """Encerra o J.A.R.V.I.S. de forma limpa."""
        self._running = False
        self._logger.info("J.A.R.V.I.S. encerrado.")

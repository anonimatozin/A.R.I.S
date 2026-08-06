"""Menu de Configurações do J.A.R.V.I.S. NEXUS.

Permite configurar todos os aspectos do sistema via terminal.
"""

import os
from pathlib import Path

from utils.terminal import Terminal
from utils.voice import Voice


class SettingsMenu:
    """Menu interativo de configurações."""

    def __init__(self, env_path: Path) -> None:
        self._env_path = env_path
        self._settings = self._load_env()

    def _load_env(self) -> dict[str, str]:
        """Carrega variáveis do .env."""
        settings = {}
        if self._env_path.exists():
            with open(self._env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        settings[key.strip()] = value.strip()
        return settings

    def _save_env(self) -> None:
        """Salva as configurações no .env."""
        lines = [
            "# ============================================================",
            "# J.A.R.V.I.S. - Environment Variables",
            "# ============================================================",
            "",
            "# Log",
            f"JARVIS_LOG_LEVEL={self._settings.get('JARVIS_LOG_LEVEL', 'INFO')}",
            f"JARVIS_MAX_LOG_SIZE_MB={self._settings.get('JARVIS_MAX_LOG_SIZE_MB', '10')}",
            "",
            "# Prompt",
            f"JARVIS_PROMPT={self._settings.get('JARVIS_PROMPT', '> ')}",
            "",
            "# Voz (SAPI)",
            f"JARVIS_VOICE_RATE={self._settings.get('JARVIS_VOICE_RATE', '0')}",
            f"JARVIS_VOICE_VOLUME={self._settings.get('JARVIS_VOICE_VOLUME', '100')}",
            "",
            "# Chat",
            f"JARVIS_CHAT_MODEL={self._settings.get('JARVIS_CHAT_MODEL', 'llama-3.3-70b-versatile')}",
            "",
            "# Memória",
            f"JARVIS_MEMORY_ROOT={self._settings.get('JARVIS_MEMORY_ROOT', 'E:\\\\JARVIS_MEMORY')}",
            "",
            "# API Keys",
            f"GROQ_API_KEY={self._settings.get('GROQ_API_KEY', '')}",
            f"OPENWEATHER_API_KEY={self._settings.get('OPENWEATHER_API_KEY', '')}",
            f"WEATHERAPI_KEY={self._settings.get('WEATHERAPI_KEY', '')}",
            f"SERPAPI_KEY={self._settings.get('SERPAPI_KEY', '')}",
        ]

        with open(self._env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def show(self) -> None:
        """Exibe o menu de configurações."""
        while True:
            Terminal.clear()
            print(Terminal.colorize("=" * 60, Terminal.CYAN))
            print(Terminal.colorize("MENU DE CONFIGURAÇÕES".center(60), Terminal.CYAN))
            print(Terminal.colorize("=" * 60, Terminal.CYAN))
            print()
            print(f"  {Terminal.colorize('1', Terminal.CYAN)} - Modelo de IA")
            print(f"  {Terminal.colorize('2', Terminal.CYAN)} - Voz")
            print(f"  {Terminal.colorize('3', Terminal.CYAN)} - Memória")
            print(f"  {Terminal.colorize('4', Terminal.CYAN)} - Log")
            print(f"  {Terminal.colorize('5', Terminal.CYAN)} - API Keys")
            print(f"  {Terminal.colorize('6', Terminal.CYAN)} - Ver configurações")
            print(f"  {Terminal.colorize('0', Terminal.RED)} - Voltar")
            print()
            print(Terminal.colorize("=" * 60, Terminal.CYAN))

            choice = Terminal.input_prompt("  Opção: ", Terminal.CYAN)

            if choice == "1":
                self._config_model()
            elif choice == "2":
                self._config_voice()
            elif choice == "3":
                self._config_memory()
            elif choice == "4":
                self._config_log()
            elif choice == "5":
                self._config_api_keys()
            elif choice == "6":
                self._show_all()
            elif choice == "0":
                break

    def _config_model(self) -> None:
        """Configura o modelo de IA."""
        Terminal.clear()
        print(f"  Modelo atual: {Terminal.colorize(self._settings.get('JARVIS_CHAT_MODEL', ''), Terminal.CYAN)}")
        print()
        print("  Modelos disponíveis (Groq):")
        print("    1 - llama-3.3-70b-versatile")
        print("    2 - llama-3.1-8b-instant")
        print("    3 - mixtral-8x7b-32768")
        print()
        choice = Terminal.input_prompt("  Opção (ou digite o nome): ", Terminal.CYAN)

        models = {
            "1": "llama-3.3-70b-versatile",
            "2": "llama-3.1-8b-instant",
            "3": "mixtral-8x7b-32768",
        }

        model = models.get(choice, choice)
        self._settings["JARVIS_CHAT_MODEL"] = model
        self._save_env()
        print(f"  Modelo alterado para: {Terminal.colorize(model, Terminal.GREEN)}")
        Terminal.input_prompt("  Pressione Enter...")

    def _config_voice(self) -> None:
        """Configura a voz."""
        Terminal.clear()
        print(f"  Velocidade atual: {self._settings.get('JARVIS_VOICE_RATE', '0')}")
        print(f"  Volume atual: {self._settings.get('JARVIS_VOICE_VOLUME', '100')}")
        print()

        rate = Terminal.input_prompt(f"  Nova velocidade (-10 a 10, Enter para manter): ", Terminal.CYAN)
        if rate:
            self._settings["JARVIS_VOICE_RATE"] = str(max(-10, min(10, int(rate))))

        volume = Terminal.input_prompt(f"  Novo volume (0-100, Enter para manter): ", Terminal.CYAN)
        if volume:
            self._settings["JARVIS_VOICE_VOLUME"] = str(max(0, min(100, int(volume))))

        self._save_env()
        print("  Voz configurada!")
        Terminal.input_prompt("  Pressione Enter...")

    def _config_memory(self) -> None:
        """Configura o diretório de memória."""
        Terminal.clear()
        print(f"  Diretório atual: {self._settings.get('JARVIS_MEMORY_ROOT', '')}")
        new_path = Terminal.input_prompt("  Novo diretório (Enter para manter): ", Terminal.CYAN)
        if new_path:
            self._settings["JARVIS_MEMORY_ROOT"] = new_path
            self._save_env()
            print("  Memória configurada!")
        Terminal.input_prompt("  Pressione Enter...")

    def _config_log(self) -> None:
        """Configura o log."""
        Terminal.clear()
        print(f"  Nível atual: {self._settings.get('JARVIS_LOG_LEVEL', 'INFO')}")
        print()
        print("  Níveis: DEBUG, INFO, WARNING, ERROR, CRITICAL")
        level = Terminal.input_prompt("  Novo nível (Enter para manter): ", Terminal.CYAN)
        if level:
            self._settings["JARVIS_LOG_LEVEL"] = level.upper()
            self._save_env()
            print("  Log configurado!")
        Terminal.input_prompt("  Pressione Enter...")

    def _config_api_keys(self) -> None:
        """Configura chaves de API."""
        Terminal.clear()
        print(Terminal.colorize("CONFIGURAR API KEYS", Terminal.CYAN))
        print()

        keys = [
            ("GROQ_API_KEY", "Groq (obrigatória)"),
            ("OPENWEATHER_API_KEY", "OpenWeatherMap"),
            ("WEATHERAPI_KEY", "WeatherAPI"),
            ("SERPAPI_KEY", "SerpAPI (Google)"),
        ]

        for env_key, label in keys:
            current = self._settings.get(env_key, "")
            masked = current[:8] + "..." if len(current) > 8 else "(não configurada)"
            print(f"  {label}: {masked}")
            new_key = Terminal.input_prompt(f"  Nova chave (Enter para manter): ", Terminal.CYAN)
            if new_key:
                self._settings[env_key] = new_key

        self._save_env()
        print("  API Keys configuradas!")
        Terminal.input_prompt("  Pressione Enter...")

    def _show_all(self) -> None:
        """Mostra todas as configurações."""
        Terminal.clear()
        print(Terminal.colorize("CONFIGURAÇÕES ATUAIS", Terminal.CYAN))
        print(Terminal.colorize("=" * 50, Terminal.CYAN))
        for key, value in sorted(self._settings.items()):
            display = value[:30] + "..." if len(value) > 30 else value
            if "KEY" in key and value:
                display = value[:8] + "..."
            print(f"  {key:<25} = {display}")
        print(Terminal.colorize("=" * 50, Terminal.CYAN))
        Terminal.input_prompt("  Pressione Enter...")

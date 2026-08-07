"""Morning Digest - Briefing Diário do J.A.R.V.I.S.

Gera um resumo completo ao iniciar o dia.
Inspirado em open-jarvis/OpenJarvis.
"""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta


class MorningDigest:
    """Gerador de briefing diário."""

    def __init__(self, data_dir: Optional[Path] = None):
        self._data_dir = data_dir
        self._digest_file = data_dir / "morning_digest.json" if data_dir else None
        self._history: list[dict] = []
        self._config = {
            "enabled": True,
            "include_weather": True,
            "include_calendar": True,
            "include_tasks": True,
            "include_news": True,
            "include_system": True,
            "include_memory": True,
        }

        if self._digest_file:
            self._load()

    def _load(self) -> None:
        """Carrega configuração e histórico."""
        if self._digest_file and self._digest_file.exists():
            try:
                data = json.loads(self._digest_file.read_text(encoding="utf-8"))
                self._history = data.get("history", [])
                self._config.update(data.get("config", {}))
            except Exception:
                pass

    def _save(self) -> None:
        """Salva dados."""
        if self._digest_file:
            try:
                data = {
                    "config": self._config,
                    "history": self._history[-30:],  # Manter 30 dias
                }
                self._digest_file.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

    def generate(
        self,
        weather_data: Optional[str] = None,
        tasks_data: Optional[str] = None,
        system_data: Optional[str] = None,
        memory_data: Optional[str] = None,
        calendar_data: Optional[str] = None,
        news_data: Optional[str] = None,
    ) -> str:
        """Gera o briefing diário.

        Args:
            weather_data: Dados do clima.
            tasks_data: Tarefas pendentes.
            system_data: Status do sistema.
            memory_data: Memórias recentes.
            calendar_data: Eventos do dia.
            news_data: Notícias.

        Returns:
            Briefing formatado.
        """
        now = datetime.now()
        greeting = self._get_greeting(now)

        lines = [
            f"{'═' * 50}",
            f"  🌅 BRIEFING DIÁRIO — {now.strftime('%d/%m/%Y %H:%M')}",
            f"{'═' * 50}",
            "",
            f"  {greeting}",
            "",
        ]

        # Clima
        if self._config["include_weather"] and weather_data:
            lines.append("  ☀️ CLIMA")
            lines.append(f"  {weather_data}")
            lines.append("")

        # Calendário
        if self._config["include_calendar"] and calendar_data:
            lines.append("  📅 AGENDA")
            lines.append(f"  {calendar_data}")
            lines.append("")

        # Tarefas
        if self._config["include_tasks"] and tasks_data:
            lines.append("  📋 TAREFAS PENDENTES")
            lines.append(f"  {tasks_data}")
            lines.append("")

        # Notícias
        if self._config["include_news"] and news_data:
            lines.append("  📰 NOTÍCIAS")
            lines.append(f"  {news_data}")
            lines.append("")

        # Sistema
        if self._config["include_system"] and system_data:
            lines.append("  💻 SISTEMA")
            lines.append(f"  {system_data}")
            lines.append("")

        # Memórias
        if self._config["include_memory"] and memory_data:
            lines.append("  🧠 MEMÓRIAS RECENTES")
            lines.append(f"  {memory_data}")
            lines.append("")

        lines.append(f"{'═' * 50}")

        digest_text = "\n".join(lines)

        # Salvar no histórico
        self._history.append({
            "date": now.isoformat(),
            "preview": digest_text[:200],
        })
        self._save()

        return digest_text

    def _get_greeting(self, now: datetime) -> str:
        """Retorna saudação baseada no horário."""
        hour = now.hour
        if 5 <= hour < 12:
            return "Bom dia, operador. Espero que esteja descansado."
        elif 12 <= hour < 18:
            return "Boa tarde, operador. Como posso ajudar?"
        elif 18 <= hour < 22:
            return "Boa noite, operador. Vamos finalizar o dia?"
        else:
            return "Operador, você está trabalhando tarde. Cuide de si."

    def set_config(self, key: str, value: bool) -> str:
        """Altera configuração do digest."""
        if key in self._config:
            self._config[key] = value
            self._save()
            return f"Configuração '{key}' alterada para {value}"
        return f"Configuração '{key}' não encontrada"

    def get_config(self) -> dict:
        """Retorna configuração atual."""
        return dict(self._config)

    def get_history(self, limit: int = 7) -> list[dict]:
        """Retorna histórico de digests."""
        return self._history[-limit:]

    def should_generate(self) -> bool:
        """Verifica se deve gerar um novo digest."""
        if not self._history:
            return True

        last = datetime.fromisoformat(self._history[-1]["date"])
        now = datetime.now()

        # Gerar se for um novo dia
        return last.date() < now.date()

    def format_compact(self, digest: str) -> str:
        """Formata digest de forma compacta."""
        lines = digest.split("\n")
        compact = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("═"):
                compact.append(stripped)
        return "\n".join(compact[:15])

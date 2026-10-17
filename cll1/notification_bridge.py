"""CLL1 Notification Bridge — captura notificações Android via Termux:API.

Usa `termux-notification-list` (app companion + pacote termux-api)
para ler notificações do sistema e publica no EventBus da ARIS.

Eventos publicados: `notification.received`
Payload: {app, title, text, sender, timestamp, is_ongoing}
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from core.neural.event_bus import EventBus
from core.neural.events import Event

logger = logging.getLogger(__name__)


@dataclass
class AndroidNotification:
    """Notificação capturada do Android."""
    id: str
    package: str
    app_name: str
    title: str | None
    text: str | None
    sender: str | None
    timestamp: datetime
    is_ongoing: bool = False
    raw: dict = field(default_factory=dict)

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "package": self.package,
            "app": self.app_name,
            "title": self.title,
            "text": self.text,
            "sender": self.sender,
            "timestamp": self.timestamp.isoformat(),
            "is_ongoing": self.is_ongoing,
        }


class TermuxNotificationListener:
    """Listener de notificações Android via Termux:API.

    Requer:
    - App Termux:API instalado no Android
    - Pacote `termux-api` instalado no Termux (`pkg install termux-api`)
    - Permissão de notificação concedida ao Termux:API
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        poll_interval: float = 5.0,
        logger: logging.Logger | None = None,
    ):
        self._event_bus = event_bus
        self._poll_interval = poll_interval
        self._logger = logger or logger
        self._running = False
        self._thread: threading.Thread | None = None
        self._seen_ids: set[str] = set()
        self._last_check = 0.0
        self._filter_packages: set[str] | None = None  # None = all

    def set_package_filter(self, packages: list[str]) -> None:
        """Limita captura a pacotes específicos (ex: ['com.whatsapp', 'com.instagram.android'])."""
        self._filter_packages = set(packages) if packages else None

    def start(self) -> bool:
        """Inicia o listener em background thread."""
        if self._running:
            return True

        # Verificar se termux-notification-list está disponível
        if not self._check_termux_api():
            if self._logger:
                self._logger.error("termux-notification-list não disponível. Instale termux-api.")
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="cll1-notification-bridge",
            daemon=True,
        )
        self._thread.start()

        if self._logger:
            self._logger.info("CLL1 Notification Bridge iniciado (Termux:API)")
        return True

    def stop(self) -> None:
        """Para o listener."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def _check_termux_api(self) -> bool:
        """Verifica se termux-notification-list funciona."""
        try:
            result = subprocess.run(
                ["termux-notification-list", "--help"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _poll_loop(self) -> None:
        """Loop principal de polling."""
        while self._running:
            try:
                self._check_notifications()
            except Exception as e:
                if self._logger:
                    self._logger.error(f"Erro no notification bridge: {e}")
            time.sleep(self._poll_interval)

    def _check_notifications(self) -> None:
        """Captura notificações atuais e emite eventos para novas."""
        try:
            result = subprocess.run(
                ["termux-notification-list", "-j"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                if self._logger:
                    self._logger.debug(f"termux-notification-list falhou: {result.stderr}")
                return

            notifications = json.loads(result.stdout) if result.stdout.strip() else []
            if not isinstance(notifications, list):
                return

            now = datetime.now()
            new_count = 0

            for notif_data in notifications:
                notif = self._parse_notification(notif_data, now)
                if not notif:
                    continue

                # Filtro de pacotes
                if self._filter_packages and notif.package not in self._filter_packages:
                    continue

                # Deduplicação por ID
                if notif.id in self._seen_ids:
                    continue

                self._seen_ids.add(notif.id)
                new_count += 1

                # Emitir evento
                self._emit_notification(notif)

            if new_count > 0 and self._logger:
                self._logger.debug(f"Capturadas {new_count} novas notificações")

        except json.JSONDecodeError:
            pass
        except subprocess.TimeoutExpired:
            if self._logger:
                self._logger.warning("Timeout ao capturar notificações")
        except Exception as e:
            if self._logger:
                self._logger.error(f"Erro ao processar notificações: {e}")

    def _parse_notification(self, data: dict, now: datetime) -> AndroidNotification | None:
        """Parseia notificação do formato JSON do termux-notification-list."""
        try:
            # ID único: package + id + tag
            notif_id = data.get("id", "")
            package = data.get("packageName", "")
            tag = data.get("tag", "")
            unique_id = f"{package}:{notif_id}:{tag}"

            # App name (fallback para package)
            app_name = data.get("appName") or package

            # Título e texto
            title = data.get("title") or data.get("contentTitle")
            text = data.get("text") or data.get("contentText") or data.get("bigText")

            # Sender (para mensagens)
            sender = data.get("sender") or data.get("from") or data.get("person")

            # Timestamp
            posted = data.get("postTime")
            if posted:
                try:
                    timestamp = datetime.fromtimestamp(posted / 1000)
                except (ValueError, TypeError):
                    timestamp = now
            else:
                timestamp = now

            is_ongoing = bool(data.get("ongoing", False))

            return AndroidNotification(
                id=unique_id,
                package=package,
                app_name=app_name,
                title=title,
                text=text,
                sender=sender,
                timestamp=timestamp,
                is_ongoing=is_ongoing,
                raw=data,
            )
        except Exception:
            return None

    def _emit_notification(self, notif: AndroidNotification) -> None:
        """Publica notificação no EventBus."""
        if not self._event_bus:
            return

        try:
            event = Event(
                event_type="notification.received",
                source="cll1_notification_bridge",
                payload=notif.to_event_payload(),
                priority=60,
                confidence=0.9,
            )
            self._event_bus.publish(event)
        except Exception as e:
            if self._logger:
                self._logger.error(f"Falha ao emitir evento de notificação: {e}")

    def get_recent(self, limit: int = 20) -> list[AndroidNotification]:
        """Retorna notificações recentes (últimas capturadas)."""
        # Esta é uma versão síncrona para consulta imediata
        try:
            result = subprocess.run(
                ["termux-notification-list", "-j"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []

            notifications = json.loads(result.stdout) if result.stdout.strip() else []
            parsed = []
            for data in notifications[:limit]:
                notif = self._parse_notification(data, datetime.now())
                if notif:
                    parsed.append(notif)
            return parsed
        except Exception:
            return []


class NotificationBridgeManager:
    """Gerenciador de alto nível para a ponte de notificações."""

    def __init__(
        self,
        event_bus: EventBus,
        logger: logging.Logger | None = None,
    ):
        self._event_bus = event_bus
        self._logger = logger or logger
        self._listener = TermuxNotificationListener(
            event_bus=event_bus,
            logger=self._logger,
        )
        self._query_cache: list[AndroidNotification] = []
        self._cache_lock = threading.Lock()

    def start(self, package_filter: list[str] | None = None) -> bool:
        """Inicia a ponte com filtro opcional de pacotes."""
        if package_filter:
            self._listener.set_package_filter(package_filter)
        return self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def query_recent(
        self,
        app: str | None = None,
        sender: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Consulta notificações recentes (para responder 'alguém me mandou mensagem?').

        Args:
            app: Filtrar por nome do app (ex: 'WhatsApp', 'Instagram')
            sender: Filtrar por remetente
            limit: Máximo de resultados

        Returns:
            Lista de dicts com notificações (resumidas, sem texto completo sensível)
        """
        with self._cache_lock:
            recent = self._listener.get_recent(limit=limit * 3)

        results = []
        for n in recent:
            if app and app.lower() not in n.app_name.lower():
                continue
            if sender and n.sender and sender.lower() not in n.sender.lower():
                continue

            # Resumir: não persistir texto completo de mensagens privadas
            summary = {
                "app": n.app_name,
                "sender": n.sender,
                "title": n.title[:50] if n.title else None,
                "preview": (n.text[:100] + "...") if n.text and len(n.text) > 100 else n.text,
                "time": n.timestamp.strftime("%H:%M"),
                "is_ongoing": n.is_ongoing,
            }
            results.append(summary)

            if len(results) >= limit:
                break

        return results

    def get_status(self) -> dict:
        return {
            "running": self._listener._running,
            "poll_interval": self._listener._poll_interval,
            "package_filter": list(self._listener._filter_packages) if self._listener._filter_packages else None,
            "termux_api_available": self._listener._check_termux_api(),
        }
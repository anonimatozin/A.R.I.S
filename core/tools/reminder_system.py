"""Reminder System — lembretes com recorrencia e notificacoes.

Persiste em SQLite, suporta lembretes unicos e recorrentes,
notifica via canal disponivel (Discord/local).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class Reminder:
    """Representa um lembrete."""

    def __init__(
        self,
        id: str,
        text: str,
        trigger_at: str,
        repeat: str = "none",
        channel: str = "auto",
        created_at: str = "",
        active: bool = True,
    ) -> None:
        self.id = id
        self.text = text
        self.trigger_at = trigger_at
        self.repeat = repeat
        self.channel = channel
        self.created_at = created_at or datetime.now().isoformat()
        self.active = active

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "trigger_at": self.trigger_at,
            "repeat": self.repeat,
            "channel": self.channel,
            "created_at": self.created_at,
            "active": self.active,
        }


class ReminderSystem:
    """Sistema de lembretes com thread de verificacao."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or str(Path.home() / ".aris" / "reminders.db")
        self._callbacks: list[Any] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._init_db()

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                trigger_at TEXT NOT NULL,
                repeat_cycle TEXT DEFAULT 'none',
                channel TEXT DEFAULT 'auto',
                created_at TEXT NOT NULL,
                active INTEGER DEFAULT 1
            )
        """)
        conn.commit()
        conn.close()

    def on_reminder(self, callback) -> None:
        """Registra callback para quando lembrete dispara."""
        self._callbacks.append(callback)

    def create(
        self,
        text: str,
        trigger_at: str | None = None,
        hours_from_now: float | None = None,
        minutes_from_now: float | None = None,
        repeat: str = "none",
        channel: str = "auto",
    ) -> dict:
        """Cria um lembrete.

        Args:
            text: Texto do lembrete.
            trigger_at: Horario exato "HH:MM", "YYYY-MM-DD HH:MM" ou "YYYY-MM-DDTHH:MM:SS".
            hours_from_now: Horas a partir de agora.
            minutes_from_now: Minutos a partir de agora.
            repeat: "none", "daily", "weekly", "monthly".
            channel: "auto", "discord", "local".
        """
        if hours_from_now is not None:
            dt = datetime.now() + timedelta(hours=hours_from_now)
            trigger_str = dt.strftime("%Y-%m-%dT%H:%M:%S")
        elif minutes_from_now is not None:
            dt = datetime.now() + timedelta(minutes=minutes_from_now)
            trigger_str = dt.strftime("%Y-%m-%dT%H:%M:%S")
        elif trigger_at:
            try:
                if len(trigger_at) == 5 and ":" in trigger_at:
                    now = datetime.now()
                    dt = datetime.strptime(trigger_at, "%H:%M").replace(
                        year=now.year, month=now.month, day=now.day
                    )
                    if dt <= now:
                        dt += timedelta(days=1)
                    trigger_str = dt.strftime("%Y-%m-%dT%H:%M:%S")
                elif "T" in trigger_at:
                    trigger_str = trigger_at
                else:
                    dt = datetime.strptime(trigger_at, "%Y-%m-%d %H:%M")
                    trigger_str = dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return {"ok": False, "error": f"Formato invalido: {trigger_at}"}
        else:
            return {"ok": False, "error": "Especifique horario do lembrete."}

        id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT INTO reminders (id, text, trigger_at, repeat_cycle, channel, created_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (id, text, trigger_str, repeat, channel, now),
        )
        conn.commit()
        conn.close()

        return {"ok": True, "id": id, "trigger_at": trigger_str, "repeat": repeat}

    def cancel(self, reminder_id: str) -> dict:
        """Cancela um lembrete."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute("SELECT id FROM reminders WHERE id = ?", (reminder_id,))
        if not cursor.fetchone():
            conn.close()
            return {"ok": False, "error": "Lembrete nao encontrado."}
        conn.execute("UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "message": f"Lembrete {reminder_id} cancelado."}

    def list_active(self) -> list[dict]:
        """Lista lembretes ativos."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute(
            "SELECT id, text, trigger_at, repeat_cycle, channel, created_at "
            "FROM reminders WHERE active = 1 ORDER BY trigger_at"
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "text": r[1],
                "trigger_at": r[2],
                "repeat": r[3],
                "channel": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def get_pending(self) -> list[dict]:
        """Retorna lembretes que ja passaram do horario."""
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute(
            "SELECT id, text, trigger_at, repeat_cycle, channel FROM reminders "
            "WHERE active = 1 AND trigger_at <= ?",
            (now,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "text": r[1], "trigger_at": r[2], "repeat": r[3], "channel": r[4]}
            for r in rows
        ]

    def start_checker(self, interval: int = 30) -> None:
        """Inicia thread que verifica lembretes periodicamente."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._check_loop, args=(interval,), daemon=True)
        self._thread.start()

    def stop_checker(self) -> None:
        self._running = False

    def _check_loop(self, interval: int) -> None:
        while self._running:
            pending = self.get_pending()
            for r in pending:
                self._fire(r)
            time.sleep(interval)

    def _fire(self, reminder: dict) -> None:
        """Dispara lembrete e reagenda se recorrente."""
        for cb in self._callbacks:
            try:
                cb(reminder)
            except Exception:
                pass

        repeat = reminder.get("repeat", "none")
        if repeat != "none":
            self._reschedule(reminder)
        else:
            self.cancel(reminder["id"])

    def _reschedule(self, reminder: dict) -> None:
        """Reagenda lembrete recorrente."""
        try:
            current = datetime.fromisoformat(reminder["trigger_at"])
            if reminder["repeat"] == "daily":
                next_dt = current + timedelta(days=1)
            elif reminder["repeat"] == "weekly":
                next_dt = current + timedelta(weeks=1)
            elif reminder["repeat"] == "monthly":
                next_dt = current + timedelta(days=30)
            else:
                return
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "UPDATE reminders SET trigger_at = ? WHERE id = ?",
                (next_dt.isoformat(), reminder["id"]),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

"""Analisador temporal para expressões de tempo em linguagem natural.

Converte expressões como "às 15:00", "daqui 2 horas", "amanhã às 7"
em objetos TemporalInfo estruturados com valores absolutos e relativos.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .models import TemporalInfo


# Mapeamento de dias da semana
_WEEKDAYS = {
    "segunda": 0, "segunda-feira": 0, "segunda feira": 0,
    "terca": 1, "terça": 1, "terca-feira": 1, "terça-feira": 1,
    "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4,
    "sabado": 5, "sábado": 5,
    "domingo": 6,
}


def parse_temporal(text: str) -> TemporalInfo | None:
    """Extrai informação temporal de um texto.

    Suporta:
    - "às 15:00", "as 23h", "as 9 da manha"
    - "daqui 2 horas", "em 30 minutos"
    - "amanhã às 7"
    - "segunda às 8"
    - "hoje mais tarde"
    - "depois"
    """
    text = text.lower().strip()
    now = datetime.now()

    # "às HH:MM" ou "as HH:MM"
    m = re.search(r"(?:às|as|@)\s*(\d{1,2})\s*:\s*(\d{2})\s*(?:da\s*noite|pm)?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if "noite" in text or "pm" in text:
            if hour < 12:
                hour += 12
        if hour > 23:
            hour = 23
        if minute > 59:
            minute = 59
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return TemporalInfo(
            time_str=f"{hour:02d}:{minute:02d}",
            time_value=target,
            is_relative=False,
        )

    # "às HHh" ou "as HHh" ou "as HH"
    m = re.search(r"(?:às|as|@)\s*(\d{1,2})\s*h?\s*(?:da\s*noite|de\s*manha|pm|am)?", text)
    if m:
        hour = int(m.group(1))
        if "noite" in text or "pm" in text:
            if hour < 12:
                hour += 12
        if "manha" in text or "am" in text:
            if hour == 12:
                hour = 0
        if hour > 23:
            hour = 23
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return TemporalInfo(
            time_str=f"{hour:02d}:00",
            time_value=target,
            is_relative=False,
        )

    # "daqui X horas" / "em X horas"
    m = re.search(r"(?:daqui|em)\s+(\d+)\s*(?:hora|horas|h)", text)
    if m:
        hours = int(m.group(1))
        target = now + timedelta(hours=hours)
        return TemporalInfo(
            time_str=target.strftime("%H:%M"),
            time_value=target,
            relative_hours=float(hours),
            is_relative=True,
        )

    # "daqui X minutos" / "em X minutos"
    m = re.search(r"(?:daqui|em)\s+(\d+)\s*(?:minuto|minutos|min|mins|m)", text)
    if m:
        minutes = int(m.group(1))
        target = now + timedelta(minutes=minutes)
        return TemporalInfo(
            time_str=target.strftime("%H:%M"),
            time_value=target,
            relative_minutes=float(minutes),
            is_relative=True,
        )

    # "amanhã às HH" / "amanha as HH"
    m = re.search(r"(?:amanhã|amanha)\s+(?:às|as)\s*(\d{1,2})\s*(?:h|:\d{2})?", text)
    if m:
        hour = int(m.group(1))
        if hour > 23:
            hour = 23
        target = (now + timedelta(days=1)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        return TemporalInfo(
            time_str=f"{hour:02d}:00",
            time_value=target,
            is_relative=False,
        )

    # "dia_da_semana às HH"
    for day_name, day_num in _WEEKDAYS.items():
        m = re.search(
            rf"{day_name}\s+(?:às|as)\s*(\d{{1,2}})\s*(?:h|:\d{{2}})?", text
        )
        if m:
            hour = int(m.group(1))
            if hour > 23:
                hour = 23
            days_ahead = (day_num - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target = (now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            return TemporalInfo(
                time_str=f"{hour:02d}:00",
                time_value=target,
                is_relative=False,
                day_of_week=day_name,
            )

    # "hoje mais tarde" (aproximação)
    if "hoje" in text and "mais tarde" in text:
        target = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if target <= now:
            target = now + timedelta(hours=2)
        return TemporalInfo(
            time_str=target.strftime("%H:%M"),
            time_value=target,
            is_relative=False,
        )

    # "depois" (sem tempo específico)
    if re.search(r"^depois$", text):
        return TemporalInfo(
            time_str="depois",
            is_relative=True,
            relative_minutes=5.0,
        )

    return None


def parse_temporal_from_segments(segments: list[str]) -> list[TemporalInfo | None]:
    """Analisa temporal de múltiplos segmentos.

    Retorna lista de TemporalInfo (ou None) na mesma ordem dos segmentos.
    """
    return [parse_temporal(seg) for seg in segments]


def compute_absolute_time(temporal: TemporalInfo, reference: datetime | None = None) -> datetime | None:
    """Converte TemporalInfo para datetime absoluto.

    Se temporal já tem time_value, retorna ele.
    Se é relativo, calcula a partir de reference (ou agora).
    """
    if temporal.time_value:
        return temporal.time_value

    now = reference or datetime.now()
    if temporal.is_relative:
        delta = timedelta(
            hours=temporal.relative_hours or 0,
            minutes=temporal.relative_minutes or 0,
        )
        return now + delta

    return None

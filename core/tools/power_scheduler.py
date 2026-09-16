"""Scheduled Shutdown/Wake — agendamento de desligamento e ligamento.

Usa mecanismos nativos do Windows (shutdown.exe + Task Scheduler).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta


def schedule_shutdown(hours: float = 0, minutes: float = 0, at: str | None = None) -> dict:
    """Agenda desligamento do PC.

    Args:
        hours: horas a partir de agora.
        minutes: minutos a partir de agora.
        at: horario exato "HH:MM" ou "YYYY-MM-DD HH:MM".

    Returns:
        dict com resultado.
    """
    if at:
        try:
            if len(at) == 5 and ":" in at:
                now = datetime.now()
                target = datetime.strptime(at, "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                if target <= now:
                    target += timedelta(days=1)
            else:
                target = datetime.strptime(at, "%Y-%m-%d %H:%M")
        except ValueError:
            return {"ok": False, "error": f"Formato de horario invalido: {at}"}
        delay_seconds = int((target - datetime.now()).total_seconds())
    else:
        delay_seconds = int(hours * 3600 + minutes * 60)

    if delay_seconds < 60:
        return {"ok": False, "error": "Tempo minimo de 1 minuto."}

    try:
        result = subprocess.run(
            ["shutdown", "/s", "/t", str(delay_seconds), "/f"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            target_time = datetime.now() + timedelta(seconds=delay_seconds)
            return {
                "ok": True,
                "message": f"PC desligara as {target_time.strftime('%H:%M')}",
                "seconds": delay_seconds,
                "target": target_time.isoformat(),
            }
        return {"ok": False, "error": result.stderr.strip() or "Erro ao agendar."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cancel_shutdown() -> dict:
    """Cancela desligamento agendado."""
    try:
        result = subprocess.run(
            ["shutdown", "/a"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Desligamento cancelado."}
        return {"ok": False, "error": result.stderr.strip() or "Nenhum desligamento agendado."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_scheduled_shutdown() -> dict:
    """Verifica se ha desligamento agendado."""
    try:
        result = subprocess.run(
            ["shutdown", "/query"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if "Nao ha" in result.stdout or "No shutdown" in result.stdout:
            return {"ok": True, "scheduled": False, "message": "Nenhum desligamento agendado."}
        return {"ok": True, "scheduled": True, "raw": result.stdout.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def schedule_wake(at: str) -> dict:
    """Agenda ligamento do PC via Task Scheduler + Wake Timer.

    IMPORTANTE: So funciona se o hardware suportar (RTC Wake, S3/S4 wake).
    A maioria dos PCs desktop modernos suporta. Laptops podem ter limitacoes.

    Args:
        at: horario "HH:MM" ou "YYYY-MM-DD HH:MM".

    Returns:
        dict com resultado.
    """
    try:
        if len(at) == 5 and ":" in at:
            now = datetime.now()
            target = datetime.strptime(at, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            if target <= now:
                target += timedelta(days=1)
        else:
            target = datetime.strptime(at, "%Y-%m-%d %H:%M")
    except ValueError:
        return {"ok": False, "error": f"Formato invalido: {at}"}

    task_name = "ARIS_WakeUp"
    python_exe = sys.executable
    wake_script = (
        "import subprocess; "
        "subprocess.run(['powershell', '-Command', "
        "'(Get-CimInstance -ClassName RTCWakeTimer | Where-Object {$_.TimerId -ne $null}).TimerId'], "
        "capture_output=True)"
    )

    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{target.strftime('%Y-%m-%dT%H:%M:00')}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>powershell</Command>
      <Arguments>-Command "Write-Output 'ARIS Wake Triggered'"</Arguments>
    </Exec>
  </Actions>
  <Settings>
    <WakeToRun>true</WakeToRun>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
  </Settings>
</Task>"""

    try:
        xml_path = r"C:\Users\Administrator\AppData\Local\Temp\aris_wake.xml"
        with open(xml_path, "w", encoding="utf-16") as f:
            f.write(xml)

        result = subprocess.run(
            ["schtasks", "/create", "/tn", task_name, "/xml", xml_path, "/f"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {
                "ok": True,
                "message": f"PC ligara as {target.strftime('%H:%M')}",
                "target": target.isoformat(),
                "note": "Requer que o hardware suporte Wake-on-Timer (RTC).",
            }
        return {"ok": False, "error": result.stderr.strip() or "Erro ao criar tarefa."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cancel_wake() -> dict:
    """Cancela ligamento agendado."""
    try:
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", "ARIS_WakeUp", "/f"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Ligamento cancelado."}
        return {"ok": False, "error": result.stderr.strip() or "Nenhuma tarefa de ligamento encontrada."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

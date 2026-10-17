"""Informações do sistema e lista de processos (psutil)."""

from __future__ import annotations

import logging
import time

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import bounded_int, err, fmt_size, guarded, ok_result, out, schema

log = logging.getLogger("aris.agent.tools.pc.system")

try:
    import psutil
except ImportError:  # pragma: no cover - dependência opcional ausente
    psutil = None  # type: ignore[assignment]

SPEC_SYSTEM_INFO = ToolSpec(
    name="pc_system_info",
    description="Resumo do computador: CPU, RAM, disco, bateria e tempo ligado (psutil).",
    parameters=schema({}),
    risk=Risk.READ,
    tags=("pc", "system"),
    timeout_s=15.0,
)

SPEC_LIST_PROCESSES = ToolSpec(
    name="pc_list_processes",
    description="Lista processos por uso de CPU/RAM, com filtro por nome e limite de itens.",
    parameters=schema(
        {
            "name": {"type": "string", "description": "Filtro (parte do nome, sem maiúsculas)."},
            "sort": {
                "type": "string",
                "enum": ["cpu", "mem"],
                "description": "Ordenação: cpu (padrão) ou mem.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de processos (padrão 30, até 200).",
                "minimum": 1,
                "maximum": 200,
            },
        }
    ),
    risk=Risk.READ,
    tags=("pc", "system"),
    timeout_s=20.0,
)


@function_tool(SPEC_SYSTEM_INFO)
@guarded
def pc_system_info(args: dict, ctx: ToolContext) -> ToolResult:
    """Devolve CPU, RAM, disco, bateria e uptime."""
    if psutil is None:
        return err("dependência psutil não instalada (requirements/parte2.txt)")
    if ctx.cancel.is_set():
        return err("cancelado antes de começar")

    cpu_percent = psutil.cpu_percent(interval=0.3)
    memory = psutil.virtual_memory()
    data: dict = {
        "cpu_percent": cpu_percent,
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "mem_total": memory.total,
        "mem_available": memory.available,
        "mem_percent": memory.percent,
    }
    lines = [
        f"CPU: {data['cpu_count_physical'] or '?'} núcleos físicos / "
        f"{data['cpu_count_logical'] or '?'} lógicos, uso {cpu_percent:.0f}%",
        f"RAM: {fmt_size(memory.total)} total, {fmt_size(memory.available)} livre "
        f"({memory.percent:.0f}% usado)",
    ]

    try:
        freq = psutil.cpu_freq()
    except Exception:  # noqa: BLE001 - nem todo sistema expõe frequência
        freq = None
    if freq and freq.current:
        lines[0] += f", {freq.current / 1000:.2f} GHz"

    anchor = ctx.config.workspace_dir
    try:
        usage = psutil.disk_usage(str(anchor))
        disk_target = str(anchor)
    except Exception:  # noqa: BLE001 - workspace pode estar num disco indisponível
        try:
            usage = psutil.disk_usage("C:\\")
            disk_target = "C:\\"
        except Exception:  # noqa: BLE001
            usage = None
            disk_target = ""
    if usage:
        data["disk_total"] = usage.total
        data["disk_free"] = usage.free
        data["disk_percent"] = usage.percent
        lines.append(
            f"Disco {disk_target}: {fmt_size(usage.total)} total, {fmt_size(usage.free)} livre "
            f"({usage.percent:.0f}% usado)"
        )

    battery = None
    if hasattr(psutil, "sensors_battery"):
        try:
            battery = psutil.sensors_battery()
        except Exception:  # noqa: BLE001
            battery = None
    if battery is None:
        lines.append("Bateria: não detectada")
    else:
        data["battery_percent"] = battery.percent
        data["battery_plugged"] = battery.power_plugged
        lines.append(
            f"Bateria: {battery.percent:.0f}% "
            + ("(carregando)" if battery.power_plugged else "(usando bateria)")
        )

    uptime = max(0.0, time.time() - psutil.boot_time())
    days, rem = divmod(int(uptime), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _seconds = divmod(rem, 60)
    data["uptime_s"] = uptime
    lines.append(f"Tempo ligado: {days}d {hours}h {minutes}min")

    return ok_result(out(ctx, "\n".join(lines)), data=data)


@function_tool(SPEC_LIST_PROCESSES)
@guarded
def pc_list_processes(args: dict, ctx: ToolContext) -> ToolResult:
    """Lista processos ordenados por CPU ou RAM, com filtro opcional por nome."""
    if psutil is None:
        return err("dependência psutil não instalada (requirements/parte2.txt)")
    if ctx.cancel.is_set():
        return err("cancelado antes de começar")

    name_filter = str(args.get("name") or "").strip().lower()
    sort_by = "mem" if str(args.get("sort") or "cpu").lower() == "mem" else "cpu"
    limit = bounded_int(args, "limit", 30, 1, 200)

    processes = list(psutil.process_iter())
    for proc in processes:  # primeira chamada devolve 0.0; precisamos "esquentar"
        try:
            proc.cpu_percent(None)
        except Exception:  # noqa: BLE001 - processo pode morrer a qualquer momento
            continue
    time.sleep(0.15)
    if ctx.cancel.is_set():
        return err("cancelado")

    rows: list[dict] = []
    for proc in processes:
        try:
            info = proc.as_dict(
                attrs=["pid", "name", "cpu_percent", "memory_info", "status"]
            )
        except Exception:  # noqa: BLE001 - NoSuchProcess/AccessDenied
            continue
        name = info.get("name") or ""
        if name_filter and name_filter not in name.lower():
            continue
        rss = 0
        memory_info = info.get("memory_info")
        if memory_info is not None:
            rss = getattr(memory_info, "rss", 0)
        rows.append(
            {
                "pid": info.get("pid"),
                "name": name,
                "cpu_percent": float(info.get("cpu_percent") or 0.0),
                "rss": rss,
                "status": info.get("status") or "?",
            }
        )

    rows.sort(key=lambda row: row["rss"] if sort_by == "mem" else row["cpu_percent"], reverse=True)
    selected = rows[:limit]
    if not selected:
        return ok_result(
            out(ctx, f"Nenhum processo corresponde a {name_filter!r}."),
            data={"processes": [], "total": 0},
        )
    lines = [f"{'PID':>7}  {'CPU%':>6}  {'RAM':>9}  nome"]
    for row in selected:
        lines.append(
            f"{row['pid']:>7}  {row['cpu_percent']:>6.1f}  {fmt_size(row['rss']):>9}  {row['name']}"
        )
    header = f"{len(selected)} de {len(rows)} processo(s) — ordenado por {sort_by}"
    return ok_result(
        out(ctx, f"{header}\n" + "\n".join(lines)),
        data={"processes": selected, "total": len(rows)},
    )

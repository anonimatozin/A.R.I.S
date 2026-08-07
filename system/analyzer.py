"""Personal Analyzer - Monitor de Sistema do J.A.R.V.I.S.

Coleta e analisa dados do sistema operacional do operador.
"""

import platform
import psutil
from datetime import datetime
from pathlib import Path


class PersonalAnalyzer:
    """Analisador de sistema. Fornece dados em tempo real."""

    def __init__(self) -> None:
        self._start_time = datetime.now()

    @property
    def uptime(self) -> str:
        """Tempo desde a inicialização do analyzer."""
        delta = datetime.now() - self._start_time
        hours = int(delta.total_seconds() // 3600)
        minutes = int((delta.total_seconds() % 3600) // 60)
        seconds = int(delta.total_seconds() % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def cpu_usage(self) -> float:
        """Porcentagem de uso da CPU."""
        return psutil.cpu_percent(interval=0.5)

    def cpu_info(self) -> dict:
        """Informações sobre a CPU."""
        return {
            "cores_physical": psutil.cpu_count(logical=False) or 0,
            "cores_logical": psutil.cpu_count(logical=True) or 0,
            "frequency_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else 0,
            "usage_percent": self.cpu_usage(),
        }

    def memory_info(self) -> dict:
        """Informações sobre a memória RAM."""
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent": mem.percent,
        }

    def disk_info(self, path: str = "C:\\") -> dict:
        """Informações sobre o disco."""
        try:
            disk = psutil.disk_usage(path)
            return {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent,
            }
        except Exception:
            return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}

    def network_info(self) -> dict:
        """Informações de rede."""
        net = psutil.net_io_counters()
        return {
            "bytes_sent_gb": round(net.bytes_sent / (1024**3), 2),
            "bytes_recv_gb": round(net.bytes_recv / (1024**3), 2),
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }

    def battery_info(self) -> dict:
        """Informações da bateria (se disponível)."""
        try:
            battery = psutil.sensors_battery()
            if battery:
                return {
                    "percent": battery.percent,
                    "plugged": battery.power_plugged,
                    "remaining_sec": battery.secsleft if battery.secsleft > 0 else None,
                }
        except Exception:
            pass
        return {"percent": None, "plugged": None, "remaining_sec": None}

    def process_count(self) -> int:
        """Quantidade de processos ativos."""
        return len(psutil.pids())

    def top_processes(self, limit: int = 5) -> list[dict]:
        """Top processos por uso de CPU."""
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                if info["cpu_percent"] and info["cpu_percent"] > 0:
                    processes.append({
                        "pid": info["pid"],
                        "name": info["name"][:25],
                        "cpu": round(info["cpu_percent"], 1),
                        "ram": round(info["memory_percent"] or 0, 1),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        processes.sort(key=lambda x: x["cpu"], reverse=True)
        return processes[:limit]

    def system_info(self) -> dict:
        """Informações gerais do sistema."""
        return {
            "os": platform.system(),
            "os_version": platform.version(),
            "hostname": platform.node(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        }

    def get_full_report(self) -> dict:
        """Relatório completo do sistema."""
        return {
            "uptime": self.uptime,
            "system": self.system_info(),
            "cpu": self.cpu_info(),
            "memory": self.memory_info(),
            "disk": self.disk_info(),
            "network": self.network_info(),
            "battery": self.battery_info(),
            "processes": self.process_count(),
            "top_processes": self.top_processes(),
        }

    def diagnose(self) -> list[str]:
        """Gera diagnósticos e recomendações."""
        alerts = []
        mem = self.memory_info()
        disk = self.disk_info()
        cpu = self.cpu_info()

        if mem["percent"] > 90:
            alerts.append("CRÍTICO: Memória RAM acima de 90%")
        elif mem["percent"] > 75:
            alerts.append("AVISO: Memória RAM acima de 75%")

        if disk["percent"] > 90:
            alerts.append("CRÍTICO: Disco acima de 90% cheio")
        elif disk["percent"] > 80:
            alerts.append("AVISO: Disco acima de 80% cheio")

        if cpu["usage_percent"] > 90:
            alerts.append("AVISO: CPU com uso muito alto")

        if not alerts:
            alerts.append("Todos os sistemas normais")

        return alerts

from __future__ import annotations

from pathlib import Path

import psutil

from .schemas import SystemStatus


class SystemStatusService:
    """Safe machine information only: CPU/memory/storage/battery/network
    and a count of VYOM-managed processes. Queried on demand -- this is
    not a permanent diagnostics dashboard."""

    def __init__(self, allowed_root: Path, vyom_process_names: tuple[str, ...] = ("vyom", "python")):
        self.allowed_root = allowed_root
        self.vyom_process_names = vyom_process_names

    def snapshot(self) -> SystemStatus:
        disk = psutil.disk_usage(str(self.allowed_root))
        memory = psutil.virtual_memory()
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        vyom_processes = sum(
            1 for proc in psutil.process_iter(["name"])
            if proc.info.get("name") and any(name in proc.info["name"].lower() for name in self.vyom_process_names)
        )
        return SystemStatus(
            cpu_percent=psutil.cpu_percent(interval=0.1),
            memory_percent=memory.percent,
            memory_total_gb=round(memory.total / (1024 ** 3), 2),
            disk_free_gb=round(disk.free / (1024 ** 3), 2),
            disk_total_gb=round(disk.total / (1024 ** 3), 2),
            battery_percent=battery.percent if battery else None,
            battery_plugged=battery.power_plugged if battery else None,
            network_connected=self._network_connected(),
            vyom_processes=vyom_processes,
        )

    @staticmethod
    def _network_connected() -> bool:
        try:
            stats = psutil.net_if_stats()
            return any(interface.isup for name, interface in stats.items() if "loopback" not in name.lower())
        except Exception:
            return True

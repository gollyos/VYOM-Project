"""System control intent handlers: Volume, Battery, Hardware status, and Screen lock.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time

import psutil

logger = logging.getLogger(__name__)


def handle_volume(query: str) -> str:
    """Control system audio volume and mute state."""
    q = query.lower()
    try:
        import pyautogui

        if "mute" in q or "unmute" in q:
            pyautogui.press("volumemute")
            return "Toggled system audio mute, sir."
        elif "up" in q or "increase" in q or "raise" in q:
            for _ in range(5):
                pyautogui.press("volumeup")
            return "Volume increased, sir."
        elif "down" in q or "decrease" in q or "lower" in q:
            for _ in range(5):
                pyautogui.press("volumedown")
            return "Volume decreased, sir."
    except Exception as exc:
        logger.warning("Volume hotkey control failed: %s", exc)

    return "Audio volume adjusted, sir."


def handle_system_status(query: str = "") -> str:
    """Get battery percentage, CPU load, and RAM consumption."""
    q = query.lower()

    # Battery
    battery = psutil.sensors_battery()
    battery_info = ""
    if battery is not None:
        percent = battery.percent
        plugged = "plugged in" if battery.power_plugged else "on battery power"
        battery_info = f"Battery is at {percent}%, {plugged}."
    else:
        battery_info = "Desktop power supply active (no battery)."

    if "battery" in q and "cpu" not in q and "ram" not in q and "memory" not in q:
        return battery_info

    # CPU & RAM
    cpu_percent = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    ram_percent = ram.percent
    ram_used_gb = ram.used / (1024**3)
    ram_total_gb = ram.total / (1024**3)

    return (
        f"{battery_info} "
        f"CPU usage is at {cpu_percent:.0f}%, and RAM usage is at {ram_percent:.0f}% "
        f"({ram_used_gb:.1f} GB of {ram_total_gb:.1f} GB), sir."
    )


def handle_speed_test(query: str = "") -> str:
    """Check internet responsiveness and round-trip ping latency."""
    try:
        import requests

        start = time.time()
        resp = requests.get("https://www.google.com", timeout=5)
        duration_ms = (time.time() - start) * 1000
        if resp.status_code == 200:
            return f"Internet connection is active. Ping latency is {duration_ms:.0f} milliseconds, sir."
    except Exception as exc:
        logger.warning("Ping test failed: %s", exc)
    return "Internet connection appears to be offline or unreachable, sir."


def handle_lock(query: str = "") -> str:
    """Lock the Windows desktop session."""
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.LockWorkStation()
            return "Locking workstation now, sir."
        except Exception as exc:
            os.system("rundll32.exe user32.dll,LockWorkStation")
            return "Lock command executed, sir."
    return "Workstation lock is only supported on Windows systems."

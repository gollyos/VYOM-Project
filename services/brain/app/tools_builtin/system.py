from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any

from app.schemas.approvals import PermissionLevel
from app.security.path_policy import PathPolicy
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class SystemTool(BaseTool):
    metadata = ToolMetadata(
        name="system",
        description="Limited explicit desktop actions and basic machine status",
        category="system",
        required_permissions=[PermissionLevel.L0],
        risk_level="medium",
    )

    #: Reading machine state changes nothing, so every query below is L0.
    READ_ACTIONS = {"status", "processes", "clock", "disks", "interpreter", "which", "battery", "ping"}

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L0 if inputs.get("action") in self.READ_ACTIONS else PermissionLevel.L1

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", ""))
        if action == "status":
            disk = shutil.disk_usage(context.allowed_roots[0])
            output = {"platform": platform.platform(), "python": platform.python_version(), "disk_free": disk.free, "disk_total": disk.total}
        # -- native answers that used to be shell commands -----------------
        #
        # Each of these replaces a PowerShell/cmd invocation VYOM used to
        # generate: `Get-Process`, `Get-Date`, `Get-Volume`, `where.exe`,
        # `python --version`. They are read directly from the OS, which is
        # faster, cannot fail on shell quoting, and never flashes a
        # console window.
        elif action == "processes":
            import psutil

            limit = int(inputs.get("limit", 10))
            sort_by = str(inputs.get("sort_by", "memory"))
            rows = []
            for process in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
                try:
                    info = process.info
                    memory = getattr(info.get("memory_info"), "rss", 0) or 0
                    rows.append({
                        "pid": info.get("pid"),
                        "name": info.get("name") or "",
                        "memory_mb": round(memory / (1024 * 1024), 1),
                        "cpu_percent": info.get("cpu_percent") or 0.0,
                    })
                except Exception:
                    continue
            key = "cpu_percent" if sort_by == "cpu" else "memory_mb"
            rows.sort(key=lambda row: row[key], reverse=True)
            output = {"processes": rows[:limit], "sorted_by": key, "total": len(rows)}
        elif action == "battery":
            import psutil

            battery = psutil.sensors_battery()
            if battery is not None:
                output = {
                    "percent": battery.percent,
                    "power_plugged": battery.power_plugged,
                    "secsleft": battery.secsleft if battery.secsleft != -1 else None,
                    "state": "plugged in" if battery.power_plugged else "on battery",
                }
            else:
                output = {"percent": 100, "power_plugged": True, "state": "AC power (no battery sensor)"}
        elif action == "volume":
            import pyautogui
            pyautogui.FAILSAFE = False

            direction = str(inputs.get("direction", "up")).strip().lower()
            if direction in {"mute", "toggle_mute"}:
                pyautogui.press("volumemute")
                output = {"volume_action": "toggled_mute"}
            elif direction in {"down", "decrease", "lower"}:
                steps = int(inputs.get("steps", 5))
                for _ in range(steps):
                    pyautogui.press("volumedown")
                output = {"volume_action": "decreased", "steps": steps}
            else:
                steps = int(inputs.get("steps", 5))
                for _ in range(steps):
                    pyautogui.press("volumeup")
                output = {"volume_action": "increased", "steps": steps}
        elif action == "lock":
            if os.name == "nt":
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                output = {"lock_action": "workstation_locked"}
            else:
                output = {"lock_action": "unsupported_on_non_windows"}
        elif action == "ping":
            import time
            import httpx

            start_t = time.time()
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get("https://www.google.com")
                latency_ms = round((time.time() - start_t) * 1000, 1)
                output = {"status_code": resp.status_code, "latency_ms": latency_ms, "online": resp.status_code == 200}
        elif action == "clock":
            from datetime import datetime

            now = datetime.now().astimezone()
            output = {"iso": now.isoformat(), "local": now.strftime("%Y-%m-%d %H:%M:%S"),
                      "timezone": str(now.tzinfo)}
        elif action == "disks":
            import psutil

            volumes = []
            for partition in psutil.disk_partitions(all=False):
                try:
                    usage = shutil.disk_usage(partition.mountpoint)
                except OSError:
                    continue
                volumes.append({
                    "device": partition.device, "mount": partition.mountpoint,
                    "total_gb": round(usage.total / 1024**3, 1),
                    "free_gb": round(usage.free / 1024**3, 1),
                    "used_percent": round(100 * (usage.total - usage.free) / usage.total, 1) if usage.total else 0,
                })
            output = {"volumes": volumes}
        elif action == "interpreter":
            import sys

            output = {
                "python_version": platform.python_version(),
                "executable": sys.executable,
                "implementation": platform.python_implementation(),
                "build": " ".join(platform.python_build()),
                "machine": platform.machine(),
            }
        elif action == "which":
            name = str(inputs.get("target", "")).strip()
            if not name:
                raise ToolValidationError("A program name is required")
            found = shutil.which(name)
            output = {"program": name, "found": bool(found), "path": found}
        elif action in {"reveal", "open_application", "open_url"}:
            target = str(inputs.get("target", ""))
            if action == "reveal":
                target = str(PathPolicy(context.allowed_roots).require_allowed(target))
            if not target:
                raise ToolValidationError("System target is required")
            if os.name != "nt":
                raise ToolValidationError("Initial system actions currently support Windows only")
            try:
                os.startfile(target)  # type: ignore[attr-defined]
            except OSError:
                alias_map = {
                    "calculator": "calc",
                    "calc": "calc",
                    "chrome": "chrome",
                    "notepad": "notepad",
                    "explorer": "explorer",
                    "terminal": "wt",
                    "cmd": "cmd",
                    "vscode": "code",
                    "code": "code",
                    "paint": "mspaint",
                }
                resolved = alias_map.get(target.lower(), target)
                exe_path = shutil.which(resolved) or shutil.which(f"{resolved}.exe") or shutil.which(target)
                if exe_path:
                    os.startfile(exe_path)  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["cmd.exe", "/c", "start", "", target], shell=False)
            output = {"action": action, "target": target}
        elif action == "open_chrome":
            import subprocess
            profile = str(inputs.get("profile", "")).strip()
            url = str(inputs.get("url", "https://google.com")).strip()
            chrome_candidates = [
                shutil.which("chrome"),
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ]
            chrome_path = next((p for p in chrome_candidates if p and os.path.exists(p)), None)
            if not chrome_path:
                # Fallback to startfile
                os.startfile(url)
                output = {"action": "open_chrome", "status": "fallback_default_browser", "url": url}
            else:
                args = [chrome_path]
                if profile:
                    args.append(f'--profile-directory={profile}')
                if url:
                    args.append(url)
                subprocess.Popen(args)
                output = {"action": "open_chrome", "status": "launched", "profile": profile or "Default", "url": url}
        elif action == "screen_probe":
            import pyautogui
            screenshot_dir = Path("services/brain/data/artifacts")
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            probe_path = screenshot_dir / "screen_probe.png"
            grab_ok = False
            try:
                img = pyautogui.screenshot()
                img.save(str(probe_path))
                grab_ok = True
            except Exception as e:
                probe_path = None
            try:
                screen_width, screen_height = pyautogui.size()
                cur_x, cur_y = pyautogui.position()
            except Exception:
                screen_width, screen_height = 1920, 1080
                cur_x, cur_y = 0, 0
            output = {
                "action": "screen_probe",
                "screen_width": screen_width,
                "screen_height": screen_height,
                "cursor_pos": [cur_x, cur_y],
                "screenshot_captured": grab_ok,
                "screenshot": str(probe_path) if probe_path else None,
            }
        else:
            raise ToolValidationError("Unsupported system action")
        evidence = EvidenceItem(type="tool_result", summary=f"System {action}", data=output)
        return ToolResult.completed(f"System {action} completed", output=output, evidence=[evidence])

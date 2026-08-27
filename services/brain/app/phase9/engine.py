from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.desktop.controller import DesktopController
from app.execution.execution_context import ExecutionContextFactory
from app.native_apps.registry import NativeAppAdapterRegistry
from app.schemas.results import ExecutionResult
from app.schemas.tasks import Task, TaskProfile
from app.screen.observer import ScreenObserver
from app.screen.verifier import ScreenVerifier
from app.tools.executor import ToolExecutor

EventEmitter = Callable[[str, str, dict], Awaitable[None]]


def _frame(x: float, y: float, width: float, layer: int | None = None) -> dict:
    frame = {"x": x, "y": y, "width": width}
    if layer:
        frame["layer"] = layer
    return frame


def _composition(identifier: str, mode: str, label: str, summary: str, objects: list[dict]) -> dict:
    states = ["Executing", "Verifying", "Completed"]
    sequence = [
        {"id": f"reveal-{index}", "label": obj.get("eyebrow", obj["title"]), "atMs": index * 280, "state": states[min(index, len(states) - 1)], "objectIds": [obj["id"]]}
        for index, obj in enumerate(objects)
    ]
    return {
        "schemaVersion": 1, "id": identifier, "mode": mode, "label": label,
        "summary": summary, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "objects": objects, "sequence": sequence,
    }


class Phase9Engine:
    """Native desktop/device execution layer. Mirrors BusinessEngine /
    IntelligenceEngine / Phase8Engine: a deterministic intent-to-workflow
    delegate the Task Runtime reaches for before a paid model. Every
    desktop/screen/input action routes through the shared ToolExecutor so
    the Permission Engine, evidence collector, and audit log are never
    bypassed."""

    INTENTS = {
        "desktop_startup_status", "desktop_startup_enable", "desktop_startup_disable",
        "open_project", "window_arrangement", "screen_context", "contextual_save",
        "system_status_explain",
    }

    def __init__(
        self,
        tool_executor: ToolExecutor,
        context_factory: ExecutionContextFactory,
        desktop: DesktopController,
        adapters: NativeAppAdapterRegistry,
        screen_observer: ScreenObserver,
        project_root: Path,
        screenshots_root: Path,
    ):
        self.tool_executor = tool_executor
        self.context_factory = context_factory
        self.desktop = desktop
        self.adapters = adapters
        self.screen_observer = screen_observer
        self.screen_verifier = ScreenVerifier()
        self.project_root = project_root
        self.screenshots_root = screenshots_root

    def supports(self, intent: str) -> bool:
        return intent in self.INTENTS

    async def execute(self, task: Task, profile: TaskProfile, emit: EventEmitter) -> ExecutionResult:
        intent = profile.intent

        async def emit_event(event_type: str, message: str, payload: dict[str, Any]) -> None:
            await emit(event_type, message, payload)

        context = self.context_factory.create(task.id, task.permission_level, emit_event)

        if intent == "desktop_startup_status":
            return await self._startup(task, context, "startup_status")
        if intent == "desktop_startup_enable":
            return await self._startup(task, context, "startup_enable")
        if intent == "desktop_startup_disable":
            return await self._startup(task, context, "startup_disable")
        if intent == "open_project":
            return await self._open_project(task, context)
        if intent == "window_arrangement":
            return await self._window_arrangement(task, context)
        if intent == "screen_context":
            return await self._screen_context(task, context)
        if intent == "contextual_save":
            return await self._contextual_save(task, context)
        if intent == "system_status_explain":
            return await self._system_status_explain(task, context)
        raise RuntimeError(f"Unsupported Phase 9 intent: {intent}")

    async def _startup(self, task: Task, context, action: str) -> ExecutionResult:
        result = await self.tool_executor.invoke("desktop", {"action": action}, context)
        status = result.structured_output
        statement = f"Auto-start is {'enabled' if status.get('enabled') else 'disabled'}."
        obj = {
            "id": "startup", "type": "verified-result", "title": "Startup preference", "eyebrow": status.get("method", ""),
            "tone": "verified", "frame": _frame(20, 20, 46), "statement": statement,
            "evidence": [f"enabled:{status.get('enabled')}"], "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return ExecutionResult(
            response=statement, structured_data=status,
            ui_composition=_composition(f"startup-{task.id}", "brain-context", "Startup", statement, [obj]),
            evidence=[f"startup_enabled:{status.get('enabled')}"],
        )

    async def _open_project(self, task: Task, context) -> ExecutionResult:
        target = str(self.project_root)
        open_result = await self.tool_executor.invoke("desktop", {"action": "app_open", "app_id": "vscode", "target": target}, context)
        screenshot_path = self.screenshots_root / f"{task.id}-open-project.png"
        screen_result = await self.tool_executor.invoke("screen_observe", {"path": str(screenshot_path)}, context)
        observation = screen_result.structured_output
        active_window = (observation.get("active_window") or "").lower()
        verified = "code" in active_window or "visual studio" in active_window
        statement = f"Opened the VYOM project. Active window: {observation.get('active_window') or 'unknown'}."
        obj = {
            "id": "project", "type": "native-app-status", "title": "VS Code", "eyebrow": "Project opened",
            "tone": "verified" if verified else "attention", "frame": _frame(18, 18, 48),
            "appId": "vscode", "appName": "Visual Studio Code", "running": bool(open_result.success),
            "integrationType": "cli", "pid": open_result.structured_output.get("pid"),
        }
        return ExecutionResult(
            response=statement, structured_data={"open": open_result.structured_output, "observation": observation},
            ui_composition=_composition(f"open-project-{task.id}", "brain-context", "Open project", statement, [obj]),
            evidence=[f"open_success:{open_result.success}"],
        )

    async def _window_arrangement(self, task: Task, context) -> ExecutionResult:
        displays_result = await self.tool_executor.invoke("desktop", {"action": "displays"}, context)
        displays = displays_result.structured_output.get("displays", [])
        primary = displays[0] if displays else {"resolution": [1920, 1080]}
        width, height = primary["resolution"]
        half_width = width // 2

        moves: list[dict[str, Any]] = []
        for title, x in (("Visual Studio Code", 0), ("Chrome", half_width)):
            try:
                move_result = await self.tool_executor.invoke("desktop", {"action": "window_move", "title": title, "x": x, "y": 0}, context)
                resize_result = await self.tool_executor.invoke("desktop", {"action": "window_resize", "title": title, "width": half_width, "height": height}, context)
                moves.append({"title": title, "moved": move_result.success, "resized": resize_result.success})
            except Exception as error:
                moves.append({"title": title, "error": str(error)})

        statement = "Window arrangement attempted for the requested apps."
        rows = [[move.get("title"), "ok" if move.get("moved") else move.get("error", "not found")] for move in moves]
        obj = {
            "id": "arrangement", "type": "comparison-table", "title": "Window arrangement", "eyebrow": "Native window API",
            "tone": "intelligence", "frame": _frame(14, 18, 48), "headers": ["Window", "Result"], "rows": rows,
        }
        return ExecutionResult(
            response=statement, structured_data={"moves": moves},
            ui_composition=_composition(f"windows-{task.id}", "brain-context", "Window arrangement", statement, [obj]),
            evidence=[f"moves:{len(moves)}"],
        )

    async def _screen_context(self, task: Task, context) -> ExecutionResult:
        screenshot_path = self.screenshots_root / f"{task.id}-context.png"
        result = await self.tool_executor.invoke("screen_observe", {"path": str(screenshot_path)}, context)
        observation = result.structured_output
        statement = (
            f"You appear to be looking at: {observation.get('active_window')}."
            if observation.get("active_window") else "No active window could be identified."
        )
        obj = {
            "id": "context", "type": "screenshot-preview", "title": "Screen context",
            "eyebrow": observation.get("active_application") or "unknown app",
            "tone": "verified" if observation.get("confidence", 0) > 0 else "attention",
            "frame": _frame(18, 18, 48), "screenshotPath": observation.get("screenshot_path"),
            "activeWindow": observation.get("active_window"), "activeApplication": observation.get("active_application"),
            "confidence": observation.get("confidence", 0),
        }
        return ExecutionResult(
            response=statement, structured_data=observation,
            ui_composition=_composition(f"context-{task.id}", "brain-context", "Screen context", statement, [obj]),
            evidence=[f"screenshot:{observation.get('screenshot_path')}"],
        )

    async def _contextual_save(self, task: Task, context) -> ExecutionResult:
        # Best-effort, deliberately conservative: without a real editor
        # selection API, "this" resolves to the current clipboard content
        # rather than guessing a consequential target.
        read_result = await self.tool_executor.invoke("desktop", {"action": "clipboard_read"}, context)
        content = str(read_result.structured_output.get("content", ""))
        if not content.strip():
            statement = "No active selection/context was found to save (clipboard is empty)."
            obj = {
                "id": "save", "type": "verified-result", "title": "Contextual save", "eyebrow": "No context",
                "tone": "attention", "frame": _frame(18, 18, 48), "statement": statement, "evidence": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            return ExecutionResult(
                response=statement, structured_data={"saved": False},
                ui_composition=_composition(f"save-{task.id}", "brain-context", "Contextual save", statement, [obj]), evidence=[],
            )

        target_path = self.project_root / "data" / "saved-context" / f"{task.id}.txt"
        write_result = await self.tool_executor.invoke("filesystem", {"action": "create", "path": str(target_path), "content": content}, context)
        statement = f"Saved a copy of the current context to {target_path.name}."
        obj = {
            "id": "save", "type": "verified-result", "title": "Contextual save", "eyebrow": "Filesystem tool",
            "tone": "verified" if write_result.success else "attention", "frame": _frame(18, 18, 48), "statement": statement,
            "evidence": [f"path:{target_path}"], "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return ExecutionResult(
            response=statement, structured_data={"saved": write_result.success, "path": str(target_path)},
            ui_composition=_composition(f"save-{task.id}", "brain-context", "Contextual save", statement, [obj]),
            evidence=[f"path:{target_path}"],
        )

    async def _system_status_explain(self, task: Task, context) -> ExecutionResult:
        result = await self.tool_executor.invoke("desktop", {"action": "status"}, context)
        status = result.structured_output
        reasons = []
        if status.get("cpu_percent", 0) > 80:
            reasons.append("CPU usage is high")
        if status.get("memory_percent", 0) > 85:
            reasons.append("Memory usage is high")
        if status.get("disk_free_gb", 100) < 5:
            reasons.append("Free disk space is low")
        if not status.get("network_connected", True):
            reasons.append("No active network connection was detected")
        statement = "; ".join(reasons) if reasons else "No obvious resource pressure was found from safe system metrics."
        obj = {
            "id": "status", "type": "verified-result", "title": "System status", "eyebrow": "Safe machine metrics",
            "tone": "attention" if reasons else "verified", "frame": _frame(18, 18, 48), "statement": statement,
            "evidence": [f"cpu:{status.get('cpu_percent')}%", f"memory:{status.get('memory_percent')}%", f"disk_free:{status.get('disk_free_gb')}GB"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return ExecutionResult(
            response=statement, structured_data=status,
            ui_composition=_composition(f"sysstatus-{task.id}", "brain-context", "System status", statement, [obj]), evidence=[],
        )


DesktopExecutionEngine = Phase9Engine
__all__ = ["Phase9Engine", "DesktopExecutionEngine"]

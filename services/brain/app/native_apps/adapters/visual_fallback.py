from __future__ import annotations

from app.desktop.app_launcher import AppLauncher
from app.desktop.schemas import IntegrationType
from app.desktop.window_manager import WindowManager

from ..schemas import AdapterActionResult, AppAdapter


class VisualFallbackAdapter(AppAdapter):
    """Generic fallback for applications without a dedicated adapter: uses
    the Application Registry and native OS process/window APIs only. It
    does not itself perform mouse/keyboard automation -- bounded input
    automation is a distinct, explicitly last-resort tier
    (`input_control`), used only when this adapter's actions are
    insufficient for the requested workflow."""

    integration_type = IntegrationType.VISUAL_FALLBACK
    supported_actions = ("open", "focus", "close", "status")

    def __init__(self, app_id: str, launcher: AppLauncher, windows: WindowManager, window_title_hint: str):
        self.app_id = app_id
        self.launcher = launcher
        self.windows = windows
        self.window_title_hint = window_title_hint

    async def open(self, *, target: str | None = None) -> AdapterActionResult:
        status = self.launcher.open(self.app_id)
        return AdapterActionResult(status.running, f"Opened {self.app_id}", output=status.model_dump())

    async def focus(self) -> AdapterActionResult:
        window = self.windows.focus(self.window_title_hint)
        return AdapterActionResult(True, f"Focused {window.title}", output=window.model_dump())

    async def close(self) -> AdapterActionResult:
        status = self.launcher.close(self.app_id)
        return AdapterActionResult(not status.running, f"Closed {self.app_id}")

    async def status(self) -> AdapterActionResult:
        status = self.launcher.status(self.app_id)
        return AdapterActionResult(True, f"{self.app_id} running={status.running}", output=status.model_dump())

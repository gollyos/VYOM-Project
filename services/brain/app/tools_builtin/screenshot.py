from __future__ import annotations

from typing import Any

from app.browser.browser_actions import BrowserActions
from app.desktop.window_manager import WindowManager
from app.schemas.approvals import PermissionLevel
from app.screen.capture import ScreenCapture, ScreenCaptureUnavailableError
from app.screen.privacy_filter import PrivacyFilter
from app.screen.region_selector import RegionSelector
from app.security.path_policy import PathPolicy
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolUnavailableError, ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class ScreenshotTool(BaseTool):
    """Explicit, on-request screen capture only: browser page, full
    desktop, a specific monitor, a specific window, or an explicit region.
    There is no continuous recording; every capture emits a
    `screen_captured` event and is refused for windows matching a
    configured sensitive-content hint (see docs/SCREEN_UNDERSTANDING.md)."""

    metadata = ToolMetadata(
        name="screenshot",
        description="Explicit browser or desktop screenshot capture for verification",
        category="visual",
        required_permissions=[PermissionLevel.L1],
        risk_level="medium",
    )

    def __init__(
        self,
        browser_actions: BrowserActions,
        window_manager: WindowManager | None = None,
        privacy_filter: PrivacyFilter | None = None,
    ):
        self.browser_actions = browser_actions
        self.window_manager = window_manager or WindowManager()
        self.privacy_filter = privacy_filter or PrivacyFilter()
        self.capture = ScreenCapture()

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        path = PathPolicy(context.allowed_roots).require_allowed(str(inputs["path"]))
        target = str(inputs.get("target", "browser"))

        if target == "browser":
            output = await self.browser_actions.perform("screenshot", {"path": str(path), "full_page": inputs.get("full_page", True)})
        elif target == "desktop":
            self._grab(path, bbox=None)
            output = {"path": str(path), "target": "desktop"}
        elif target == "monitor":
            displays = self.window_manager.displays()
            index = int(inputs.get("display_id", 0))
            if index >= len(displays):
                raise ToolValidationError(f"No display with id {index}")
            self._grab_via(lambda: self.capture.monitor(path, displays[index]))
            output = {"path": str(path), "target": "monitor", "display_id": index}
        elif target == "window":
            title = str(inputs.get("title", ""))
            matches = [window for window in self.window_manager.list() if title.lower() in window.title.lower()]
            if not matches:
                raise ToolValidationError(f"No window found matching '{title}'")
            window = matches[0]
            if self.privacy_filter.is_sensitive_window(window.title):
                raise ToolValidationError(f"Refusing to capture a window matching a sensitive-content hint: '{window.title}'")
            self._grab_via(lambda: self.capture.window(path, window))
            output = {"path": str(path), "target": "window", "title": window.title}
        elif target == "region":
            region = RegionSelector.explicit(int(inputs["x"]), int(inputs["y"]), int(inputs["width"]), int(inputs["height"]))
            self._grab_via(lambda: self.capture.region(path, region))
            output = {"path": str(path), "target": "region"}
        else:
            raise ToolValidationError(f"Unsupported screenshot target: {target}")

        await context.emit("screen_captured", f"Captured {target} screenshot", {"path": str(path), "target": target})
        evidence = EvidenceItem(type="visual_verification", summary=f"Captured {target} screenshot", data=output)
        return ToolResult.completed("Screenshot captured", output=output, evidence=[evidence])

    def _grab(self, path, *, bbox) -> None:
        try:
            from PIL import ImageGrab
        except ImportError as error:
            raise ToolUnavailableError("Desktop screenshots require Pillow") from error
        path.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab(bbox=bbox)
        image.save(path)

    def _grab_via(self, capture_call) -> None:
        try:
            capture_call()
        except ScreenCaptureUnavailableError as error:
            raise ToolUnavailableError(str(error)) from error

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.approvals import PermissionLevel
from app.screen.observer import ScreenObserver
from app.security.path_policy import PathPolicy
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.result import EvidenceItem, ToolResult


class ScreenObserveTool(BaseTool):
    """Structured screen understanding: 'what am I looking at?'. Captures
    only the active window (never the full desktop when a single window
    is sufficient), skips capture entirely for sensitive-looking windows,
    and returns a `ScreenObservation` without inventing hidden content."""

    metadata = ToolMetadata(
        name="screen_observe",
        description="Capture the active window and produce a structured ScreenObservation",
        category="visual",
        required_permissions=[PermissionLevel.L1],
        risk_level="medium",
    )

    def __init__(self, observer: ScreenObserver):
        self.observer = observer

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        path = PathPolicy(context.allowed_roots).require_allowed(str(inputs["path"]))
        observation = self.observer.observe_active_window(Path(path))
        await context.emit("screen_observed", "Observed the active window", {"active_window": observation.active_window})
        output = observation.model_dump(mode="json")
        evidence = EvidenceItem(type="visual_verification", summary="Screen observation captured", data=output)
        return ToolResult.completed("Screen observation captured", output=output, evidence=[evidence])

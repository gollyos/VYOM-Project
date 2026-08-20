from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.browser.browser_actions import BrowserActions
from app.browser.browser_verifier import BrowserVerifier
from app.schemas.approvals import PermissionLevel
from app.security.path_policy import PathPolicy
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class BrowserTool(BaseTool):
    metadata = ToolMetadata(
        name="browser",
        description="Semantic Playwright browser actions with consequential-action gates",
        category="browser",
        required_permissions=[PermissionLevel.L0],
        risk_level="medium",
    )
    READ_ACTIONS = {"open", "navigate", "read", "extract", "scroll", "wait", "screenshot"}
    WRITE_ACTIONS = {"click", "type", "select"}

    def __init__(self, actions: BrowserActions, verifier: BrowserVerifier):
        self.actions = actions
        self.verifier = verifier

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", ""))
        if action in self.WRITE_ACTIONS:
            return PermissionLevel.L2 if inputs.get("consequential", False) else PermissionLevel.L1
        return PermissionLevel.L0

    def validate(self, inputs: dict[str, Any], context: ToolContext) -> None:
        super().validate(inputs, context)
        action = str(inputs.get("action", ""))
        if action not in self.READ_ACTIONS | self.WRITE_ACTIONS:
            raise ToolValidationError("Unsupported semantic browser action")
        if action in {"open", "navigate"}:
            parsed = urlparse(str(inputs.get("url", "")))
            if parsed.scheme not in {"http", "https"}:
                raise ToolValidationError("Browser URL must use http or https")
        if action == "screenshot":
            PathPolicy(context.allowed_roots).require_allowed(str(inputs.get("path", "")))

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        self.validate(inputs, context)
        action = str(inputs["action"])
        await context.emit("browser_action", f"Browser {action}", {"action": action, "url": inputs.get("url")})
        output = await self.actions.perform(action, inputs)
        evidence_type = "browser_screenshot" if action == "screenshot" else "browser_confirmation"
        evidence = EvidenceItem(type=evidence_type, summary=f"Browser {action} completed", data=output)
        return ToolResult.completed(f"Browser {action} completed", output=output, evidence=[evidence])

    async def verify(self, inputs: dict[str, Any], result: ToolResult, context: ToolContext) -> ToolResult:
        if not result.success or inputs.get("action") == "screenshot":
            return result
        verification = await self.verifier.verify(expected_text=inputs.get("expected_text"), expected_url=inputs.get("expected_url"))
        result.structured_output["verification"] = verification
        if not verification["passed"]:
            result.success = False
            result.error = "Browser state verification failed"
        return result

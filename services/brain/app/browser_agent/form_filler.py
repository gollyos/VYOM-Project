from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor
from app.tools.result import ToolResult

from .action_planner import ActionPlanner
from .session_memory import SessionMemory


@dataclass
class FormPreview:
    site: str
    purpose: str
    fields: dict[str, Any]
    consequence: str
    permission_level: str


class FormFiller:
    """Structured form filling. A preview is always available before a
    consequential submit; secrets are never written into session memory."""

    def __init__(self, executor: ToolExecutor, planner: ActionPlanner | None = None):
        self.executor = executor
        self.planner = planner or ActionPlanner()

    @staticmethod
    def build_preview(*, site: str, purpose: str, fields: dict[str, Any], consequence: str, permission_level: str) -> FormPreview:
        safe_fields = {key: ("***" if key.lower() in {"password", "otp", "credit_card", "cvv"} else value) for key, value in fields.items()}
        return FormPreview(site=site, purpose=purpose, fields=safe_fields, consequence=consequence, permission_level=permission_level)

    async def fill(self, fields: dict[str, str], context: ToolContext, memory: SessionMemory) -> list[ToolResult]:
        results: list[ToolResult] = []
        for description, value in fields.items():
            action = self.planner.plan_type(description, value)
            result = await self.executor.invoke("browser", {**action.inputs, "action": action.action}, context)
            memory.record_form_field(description, value)
            memory.record_action(action.action, action.inputs, result.success)
            results.append(result)
        return results

    async def submit(self, description: str, context: ToolContext, memory: SessionMemory) -> ToolResult:
        action = self.planner.plan_click(description)
        result = await self.executor.invoke("browser", {**action.inputs, "action": "click"}, context)
        memory.record_action("submit", action.inputs, result.success)
        return result

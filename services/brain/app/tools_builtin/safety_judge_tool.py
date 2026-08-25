from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class SafetyJudgeTool(BaseTool):
    """AI-as-a-judge query-safety gate (the LangGraph agentic-data-agent
    pattern applied to VYOM): before executing a model-generated SQL /
    query, decide whether it is SAFE to run — read-only retrieval only,
    never anything that modifies data or schema. L1 (reads a query
    string, returns a verdict; it does not itself execute anything or
    reach an external destination). Two layers: a deterministic
    destructive-keyword pre-check (no LLM cost) plus an LLM judge bound
    to a strict yes/no schema. Fails to UNSAFE if the judge can't run or
    its answer isn't an explicit boolean — a false rejection is far
    cheaper than a destructive query."""

    metadata = ToolMetadata(
        name="safety_judge",
        description=(
            "Judge whether a generated SQL/query is SAFE to execute before running it. "
            "action='judge' takes the query text and returns {'safe': bool, 'reason': str}. "
            "Use before executing any model-generated query to prevent destructive/unsafe "
            "SQL (INSERT/UPDATE/DELETE/DROP/ALTER or injection) from ever running."
        ),
        category="security",
        required_permissions=[PermissionLevel.L1],
        risk_level="low",
    )

    def __init__(self, judge) -> None:
        self.judge = judge

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L1

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", "judge"))
        if action != "judge":
            raise ToolValidationError(f"Unsupported safety_judge action: {action}")

        query = str(inputs.get("query", "")).strip()
        if not query:
            raise ToolValidationError("query is required")

        result = await self.judge.judge(query)
        return ToolResult.completed(
            f"Query judged {'SAFE' if result.safe else 'UNSAFE'}: {result.reason}",
            output={"safe": result.safe, "reason": result.reason},
            evidence=[EvidenceItem(
                type="tool_result",
                summary="Query safety verdict",
                data={"safe": result.safe, "reason": result.reason},
            )],
        )

    async def health(self) -> dict[str, Any]:
        return {"healthy": True, "reason": "connected"}

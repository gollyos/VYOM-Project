"""
Project File & Deliverable Explorer Tool for VYOM.
Allows VYOM to search, inspect, and explain where any project/client file is,
what purpose it serves ("kis kaam ki hai"), and why it was created ("kyu banayi hai").
"""

from __future__ import annotations

from typing import Any
from pathlib import Path

from app.knowledge.project_index import get_project_knowledge
from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class ProjectFileTool(BaseTool):
    metadata = ToolMetadata(
        name="project_files",
        description="Search and explain project files, client deliverables, spreadsheets, reports, and architecture modules.",
        category="knowledge",
        required_permissions=[PermissionLevel.L0],
        risk_level="low",
    )

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L0

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        svc = get_project_knowledge()
        svc.index_workspace_artifacts()

        action = str(inputs.get("action", "search")).strip().lower()

        if action in ("search", "find", "lookup"):
            query = str(inputs.get("query", "")).strip()
            if not query:
                raise ToolValidationError("Query string is required to search project files.")
            results = svc.find_files(query)
            items = [
                {
                    "filename": r.filename,
                    "path": r.path,
                    "category": r.category,
                    "purpose": r.purpose,
                    "why_created": r.why_created,
                    "size_bytes": r.size_bytes,
                }
                for r in results[:10]
            ]
            msg = f"Found {len(items)} matching file(s) for '{query}'."
            evidence = EvidenceItem(type="tool_result", summary=msg, data={"matches": items})
            return ToolResult.completed(msg, output={"matches": items, "count": len(items)}, evidence=[evidence])

        elif action in ("summary", "overview", "list_all"):
            summary = svc.get_summary_report()
            msg = f"Project index contains {summary['total_indexed_files']} tracked files across {len(summary['categories'])} categories."
            evidence = EvidenceItem(type="tool_result", summary=msg, data=summary)
            return ToolResult.completed(msg, output=summary, evidence=[evidence])

        else:
            raise ToolValidationError(f"Unsupported action for project_files: {action}")

from __future__ import annotations

import asyncio
from typing import Any

from app.schemas.approvals import PermissionLevel
from app.security.path_policy import PathPolicy
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult, ToolStatus


class GitTool(BaseTool):
    metadata = ToolMetadata(
        name="git",
        description="Controlled Git inspection and selected local mutations",
        category="coding",
        required_permissions=[PermissionLevel.L0],
        risk_level="medium",
    )
    ACTIONS = {"status", "diff", "log", "branch", "create_branch", "checkout", "add", "commit"}

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", ""))
        if action == "commit":
            return PermissionLevel.L2
        if action in {"create_branch", "checkout", "add"}:
            return PermissionLevel.L1
        return PermissionLevel.L0

    def validate(self, inputs: dict[str, Any], context: ToolContext) -> None:
        super().validate(inputs, context)
        if inputs.get("action") not in self.ACTIONS:
            raise ToolValidationError("Unsupported Git action")
        root = PathPolicy(context.allowed_roots).require_allowed(str(inputs.get("cwd", "")))
        if not (root / ".git").exists():
            raise ToolValidationError(f"Not a Git repository: {root}")

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        self.validate(inputs, context)
        root = PathPolicy(context.allowed_roots).require_allowed(str(inputs["cwd"]))
        action = str(inputs["action"])
        args = {
            "status": ["status", "--short", "--branch"],
            "diff": ["diff", "--", *list(inputs.get("paths", []))],
            "log": ["log", f"-{min(int(inputs.get('limit', 10)), 50)}", "--oneline"],
            "branch": ["branch", "--show-current"],
            "create_branch": ["switch", "-c", str(inputs.get("name", ""))],
            "checkout": ["switch", str(inputs.get("name", ""))],
            "add": ["add", "--", *list(inputs.get("paths", []))],
            "commit": ["commit", "-m", str(inputs.get("message", ""))],
        }[action]
        if action in {"create_branch", "checkout", "commit"} and not args[-1].strip():
            raise ToolValidationError(f"Git {action} requires a non-empty value")
        process = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(root), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout_raw, stderr_raw = await process.communicate()
        stdout, stderr = stdout_raw.decode(errors="replace"), stderr_raw.decode(errors="replace")
        branch_process = await asyncio.create_subprocess_exec(
            "git", "branch", "--show-current", cwd=str(root), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        branch_raw, _ = await branch_process.communicate()
        output = {"action": action, "branch": branch_raw.decode().strip(), "stdout": stdout, "stderr": stderr, "exit_code": process.returncode}
        evidence = EvidenceItem(type="file_diff" if action == "diff" else "tool_result", summary=f"Git {action} on {root.name}", data=output)
        result = ToolResult.completed(
            f"Git {action} {'completed' if process.returncode == 0 else 'failed'}",
            output=output,
            evidence=[evidence],
        )
        if process.returncode != 0:
            return result.model_copy(update={"success": False, "status": ToolStatus.FAILED})
        return result

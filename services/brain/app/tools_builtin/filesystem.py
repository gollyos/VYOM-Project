from __future__ import annotations

import difflib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.approvals import PermissionLevel
from app.security.path_policy import PathPolicy
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolPermissionError, ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class FilesystemTool(BaseTool):
    metadata = ToolMetadata(
        name="filesystem",
        description="Controlled file and directory operations inside allowed roots",
        category="filesystem",
        required_permissions=[PermissionLevel.L0],
        risk_level="low",
        input_schema={"required": ["action", "path"]},
        output_schema={"type": "object"},
    )

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", ""))
        if action == "delete":
            return PermissionLevel.L3
        if action in {"create", "update", "copy", "move", "mkdir"}:
            return PermissionLevel.L1
        return PermissionLevel.L0

    def validate(self, inputs: dict[str, Any], context: ToolContext) -> None:
        super().validate(inputs, context)
        if inputs.get("action") not in {"list", "search", "read", "create", "update", "copy", "move", "mkdir", "metadata", "delete"}:
            raise ToolValidationError("Unsupported filesystem action")
        if "path" not in inputs:
            raise ToolValidationError("Filesystem path is required")
        PathPolicy(context.allowed_roots).require_allowed(str(inputs["path"]))

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        self.validate(inputs, context)
        policy = PathPolicy(context.allowed_roots)
        path = policy.require_allowed(str(inputs["path"]))
        action = str(inputs["action"])
        before = self._metadata(path)
        evidence_type = "tool_result"
        output: dict[str, Any]

        if action == "list":
            if not path.is_dir():
                raise ToolValidationError(f"Directory does not exist: {path}")
            entries = [self._metadata(item) for item in sorted(path.iterdir(), key=lambda item: item.name.lower())]
            output = {"path": str(path), "entries": entries}
        elif action == "search":
            pattern = str(inputs.get("pattern", "*"))
            limit = min(int(inputs.get("limit", 200)), 1000)
            matches = [str(item) for item in path.rglob(pattern) if len(str(item)) <= 4096][:limit]
            output = {"path": str(path), "pattern": pattern, "matches": matches}
        elif action == "read":
            max_chars = min(int(inputs.get("max_chars", 200_000)), 1_000_000)
            text = path.read_text(encoding="utf-8")
            output = {"path": str(path), "content": text[:max_chars], "truncated": len(text) > max_chars}
        elif action in {"create", "update"}:
            content = str(inputs.get("content", ""))
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            if action == "create" and path.exists() and not inputs.get("overwrite", False):
                raise ToolValidationError(f"File already exists: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            diff = "".join(difflib.unified_diff(old.splitlines(True), content.splitlines(True), fromfile=str(path), tofile=str(path)))
            output = {"path": str(path), "bytes": len(content.encode("utf-8")), "diff": diff[:100_000]}
            evidence_type = "file_diff"
        elif action == "mkdir":
            path.mkdir(parents=bool(inputs.get("parents", True)), exist_ok=bool(inputs.get("exist_ok", True)))
            output = {"path": str(path)}
        elif action in {"copy", "move"}:
            destination = policy.require_allowed(str(inputs.get("destination", "")))
            destination.parent.mkdir(parents=True, exist_ok=True)
            if action == "copy":
                shutil.copy2(path, destination)
            else:
                shutil.move(str(path), str(destination))
            output = {"path": str(path), "destination": str(destination)}
        elif action == "metadata":
            output = self._metadata(path)
        else:
            if not inputs.get("confirmed", False):
                raise ToolPermissionError("Delete requires explicit confirmed=true after L3 approval")
            if path.is_dir():
                if any(path.iterdir()):
                    raise ToolPermissionError("Recursive directory deletion is not enabled")
                path.rmdir()
            else:
                path.unlink()
            output = {"path": str(path), "deleted": True}
            evidence_type = "file_diff"

        after = self._metadata(path)
        timestamp = datetime.now(timezone.utc).isoformat()
        evidence = EvidenceItem(
            type=evidence_type,
            summary=f"Filesystem {action}: {path.name}",
            data={"path": str(path), "operation": action, "before": before, "after": after, "timestamp": timestamp},
        )
        return ToolResult.completed(f"Filesystem {action} completed", output=output, evidence=[evidence])

    async def verify(self, inputs: dict[str, Any], result: ToolResult, context: ToolContext) -> ToolResult:
        if not result.success:
            return result
        action = str(inputs["action"])
        path = PathPolicy(context.allowed_roots).require_allowed(str(inputs["path"]))
        if action in {"create", "update", "mkdir"} and not path.exists():
            raise ToolValidationError(f"Filesystem verification failed: {path} does not exist")
        if action == "delete" and path.exists():
            raise ToolValidationError(f"Filesystem verification failed: {path} still exists")
        return result

    @staticmethod
    def _metadata(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"exists": False, "path": str(path)}
        stat = path.stat()
        return {
            "exists": True,
            "path": str(path),
            "kind": "directory" if path.is_dir() else "file",
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }

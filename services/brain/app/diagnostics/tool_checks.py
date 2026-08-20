from __future__ import annotations

from .system_checks import CheckResult


class ToolChecks:
    def __init__(self, tool_registry):
        self.tool_registry = tool_registry

    async def run_all(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        for tool in self.tool_registry.list():
            name = tool.metadata.name
            try:
                health = await tool.health()
            except Exception as error:
                results.append(CheckResult(f"tool:{name}", "FAIL", f"Health check raised: {error}"))
                continue
            status = str(health.get("status", "unknown")).lower()
            if status in ("healthy", "ok", "available"):
                results.append(CheckResult(f"tool:{name}", "PASS", "Tool healthy"))
            elif status == "unknown":
                results.append(CheckResult(f"tool:{name}", "WARNING", "Health unknown"))
            else:
                results.append(CheckResult(f"tool:{name}", "WARNING", f"Tool reports {status}"))
        return results

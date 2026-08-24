from __future__ import annotations

import time
from typing import Any

from app.execution.evidence_collector import EvidenceCollector

from .context import ToolContext
from .errors import ToolCancelledError, ToolError, ToolPermissionError
from .registry import ToolRegistry
from .result import EvidenceItem, ToolResult, ToolStatus


LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, evidence_collector: EvidenceCollector):
        self.registry = registry
        self.evidence_collector = evidence_collector

    async def invoke(
        self,
        name: str,
        inputs: dict[str, Any],
        context: ToolContext,
        *,
        dry_run: bool = False,
    ) -> ToolResult:
        started = time.perf_counter()
        tool = self.registry.get(name)
        required = tool.permission_for(inputs)
        summary_inputs = {key: value for key, value in inputs.items() if key.lower() not in {"password", "secret", "token", "api_key"}}
        await context.emit("tool_selected", f"Selected {name}", {"tool": name, "input_summary": summary_inputs})
        await context.emit(
            "tool_permission_check",
            f"Checking {required.value} permission for {name}",
            {"tool": name, "required": required.value, "granted": context.permission_level.value},
        )
        if LEVEL_ORDER[context.permission_level.value] < LEVEL_ORDER[required.value]:
            raise ToolPermissionError(f"{name} requires {required.value}; task has {context.permission_level.value}")

        try:
            tool.validate(inputs, context)
            await context.emit("tool_started", f"{name} started", {"tool": name})
            result = await (tool.dry_run(inputs, context) if dry_run else tool.execute(inputs, context))
            if not dry_run and tool.metadata.supports_verification:
                result = await tool.verify(inputs, result, context)
            result.duration_ms = (time.perf_counter() - started) * 1000
            if not dry_run and result.success:
                # Real, observed tool sequence for THIS task — feeds the
                # self-improvement loop's automatic skill promotion
                # (ExecutionContextFactory.tools_used / SkillAutoPromoter).
                used = context.metadata.setdefault("tools_used", [])
                used.append(name)
            for evidence in result.evidence:
                await self.evidence_collector.record(context.task_id, evidence)
                await context.emit(
                    "verification_evidence",
                    evidence.summary,
                    {"tool": name, "evidence": evidence.model_dump(mode="json")},
                )
            await context.emit(
                "tool_completed",
                result.summary,
                {"tool": name, "status": result.status.value, "duration_ms": result.duration_ms},
            )
            return result
        except ToolCancelledError as error:
            result = ToolResult(success=False, status=ToolStatus.CANCELLED, summary=str(error), error=str(error))
            await context.emit("tool_failed", str(error), {"tool": name, "cancelled": True})
            return result
        except ToolError as error:
            await context.emit("tool_failed", str(error), {"tool": name, "error": str(error)})
            raise
        except Exception as error:
            wrapped = ToolResult(
                success=False,
                status=ToolStatus.FAILED,
                summary=f"{name} failed",
                error=str(error),
                duration_ms=(time.perf_counter() - started) * 1000,
                evidence=[EvidenceItem(type="tool_result", summary=f"{name} failed", data={"error": str(error)})],
            )
            await context.emit("tool_failed", wrapped.summary, {"tool": name, "error": str(error)})
            return wrapped

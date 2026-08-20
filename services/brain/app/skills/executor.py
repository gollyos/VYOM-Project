from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from app.execution.action_engine import ActionEngine
from app.schemas.tasks import Task, TaskDomain, TaskProfile
from app.schemas.tasks import ActionProvenance, TaskStatus
from app.schemas.results import ExecutionResult
from app.schemas.routing import UsageRecord
from app.tools.result import ToolStatus

from .registry import SkillRegistry
from .schemas import SkillStatus
from .teachable import resolve_runtime_inputs, resolve_templates


class SkillExecutor:
    def __init__(self, registry: SkillRegistry, action_engine: ActionEngine):
        self.registry = registry
        self.action_engine = action_engine

    async def execute(self, skill_id: str, task: Task, emit, runtime_inputs: dict | None = None):
        skill = self.registry.get(skill_id)
        if not skill or skill.status not in {SkillStatus.APPROVED, SkillStatus.ACTIVE}:
            raise RuntimeError(f"Skill is not active: {skill_id}")
        started = time.perf_counter()
        if skill_id != "project-build-check":
            return await self._execute_teachable(skill, task, emit, runtime_inputs or {}, started)
        result = await self.action_engine.execute(
            task,
            TaskProfile(domain=TaskDomain.CODING, complexity=3, deterministic=True, intent="inspect_project_build", needs={"tools"}),
            emit,
        )
        elapsed = (time.perf_counter() - started) * 1000
        passed = bool(result.structured_data.get("verification", {}).get("passed"))
        skill.metrics.executions += 1
        skill.metrics.successes += int(passed)
        skill.metrics.failures += int(not passed)
        skill.metrics.verification_score = 1.0 if passed else 0.0
        skill.metrics.average_runtime_ms = (
            (skill.metrics.average_runtime_ms * (skill.metrics.executions - 1) + elapsed) / skill.metrics.executions
        )
        skill.success_rate = skill.metrics.successes / skill.metrics.executions
        skill.last_used = datetime.now(timezone.utc)
        self.registry.save(skill)
        return result

    async def _execute_teachable(self, skill, task: Task, emit, supplied: dict, started: float) -> ExecutionResult:
        inputs, sensitive = resolve_runtime_inputs(skill, supplied)
        if task.status in {TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.COMPLETED}:
            raise RuntimeError("A terminal task cannot execute a taught skill")
        try:
            ActionProvenance((task.metadata or {}).get("provenance"))
        except ValueError as error:
            raise RuntimeError("Taught skill execution requires valid action provenance") from error
        order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
        if order[task.permission_level.value] < order[skill.required_permissions.value]:
            raise RuntimeError(
                f"Taught skill requires {skill.required_permissions.value}; task has {task.permission_level.value}"
            )

        sensitive_values = [str(inputs[name]) for name in sensitive if name in inputs]

        def redact(value):
            if isinstance(value, str):
                for secret in sensitive_values:
                    if secret:
                        value = value.replace(secret, "[REDACTED]")
                return value
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        async def safe_emit(event_type, message, payload):
            await emit(event_type, redact(message), redact(payload))

        context = self.action_engine.context_factory.create(task.id, task.permission_level, safe_emit)
        results = []
        completed: set[str] = set()
        try:
            for step in skill.steps:
                if len(results) >= skill.budget.max_tool_calls:
                    raise RuntimeError("Skill tool-call budget exceeded")
                if not set(step.depends_on).issubset(completed):
                    raise RuntimeError(f"Dependencies were not completed for step {step.id}")
                safe_names = sorted(name for name in inputs if name not in sensitive)
                await emit("skill_step_started", f"Running taught step: {step.action}", {
                    "skill_id": skill.id, "step_id": step.id, "runtime_input_names": safe_names,
                    "sensitive_inputs_present": bool(sensitive),
                })
                remaining = skill.budget.max_runtime_seconds - (time.perf_counter() - started)
                if remaining <= 0:
                    raise TimeoutError("Taught skill runtime budget exceeded")
                tool_result = await asyncio.wait_for(
                    self.action_engine.executor.invoke(step.tool, resolve_templates(step.inputs, inputs), context),
                    timeout=remaining,
                )
                results.append({
                    "step_id": step.id, "tool": step.tool, "success": tool_result.success,
                    "status": tool_result.status.value, "summary": redact(tool_result.summary),
                    "evidence": [redact(item.summary) for item in tool_result.evidence],
                })
                if not tool_result.success or tool_result.status != ToolStatus.COMPLETED:
                    raise RuntimeError(f"Taught skill step {step.id} failed: {tool_result.summary}")
                completed.add(step.id)
        except Exception as error:
            self._record_metrics(skill, False, started, str(error))
            raise
        finally:
            self.action_engine.context_factory.release(task.id)

        evidence = [item for result in results for item in result["evidence"]]
        passed = len(completed) == len(skill.steps) and (
            bool(evidence) or not skill.verification.require_evidence
        )
        self._record_metrics(skill, passed, started, None if passed else "Evidence requirement failed")
        if not passed:
            raise RuntimeError("Taught skill verification failed; no verified completion was claimed")
        summary = f"Taught skill {skill.name} completed {len(results)} verified step(s)."
        return ExecutionResult(
            response=summary,
            structured_data={"skill_id": skill.id, "version": skill.version, "steps": results},
            evidence=evidence or [f"All {len(results)} tool steps completed"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    def _record_metrics(self, skill, passed: bool, started: float, reason: str | None) -> None:
        elapsed = (time.perf_counter() - started) * 1000
        skill.metrics.executions += 1
        skill.metrics.successes += int(passed)
        skill.metrics.failures += int(not passed)
        skill.metrics.verification_score = 1.0 if passed else 0.0
        skill.metrics.average_runtime_ms = (
            (skill.metrics.average_runtime_ms * (skill.metrics.executions - 1) + elapsed) / skill.metrics.executions
        )
        skill.metrics.common_failure_reason = reason
        skill.success_rate = skill.metrics.successes / skill.metrics.executions
        skill.last_used = datetime.now(timezone.utc)
        self.registry.save(skill)

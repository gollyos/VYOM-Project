from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.providers.base import ProviderRateLimitError, ProviderRequest, ToolSchema
from app.schemas.approvals import PermissionLevel
from app.schemas.results import ExecutionResult
from app.schemas.routing import UsageRecord
from app.schemas.tasks import Task, TaskCreate, TaskProfile
from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


EventEmitter = Callable[[str, str, dict], Awaitable[None]]


class AutonomousMissionError(RuntimeError):
    pass


@dataclass
class AutonomousStepRecord:
    tool: str
    inputs: dict[str, Any]
    success: bool
    summary: str


SYSTEM_INSTRUCTION = (
    "You are an autonomous VYOM sub-agent given ONE free-form goal, not a pre-scripted skill. "
    "You have REAL tools, listed as callable functions - use them to actually accomplish the "
    "goal yourself.\n"
    "RULES:\n"
    "1. Work step by step: call ONE tool, wait for its REAL result, then decide the next step "
    "from what you actually observed. Never assume a result you have not seen.\n"
    "2. Never fabricate facts, file contents, command output, or outcomes. If a tool fails, say "
    "so plainly and either adapt or stop honestly - do not claim success you do not have.\n"
    "3. When the goal is genuinely satisfied by what you have done and observed, reply with a "
    "short plain-text summary of what you did and found, and call no further tools.\n"
    "4. You are bounded to a small number of steps. Prefer the fewest tool calls that truly "
    "satisfy the goal; do not repeat an identical call expecting a different result.\n"
)


class AutonomousAgentWorker:
    """Claude-Code-style bounded ReAct executor.

    Given a free-form goal (no pre-picked skill, no fixed step list), the
    agent itself asks the model for the NEXT tool call, runs it through
    the SAME ToolExecutor every other tool call in VYOM goes through,
    observes the REAL result, feeds it back, and repeats - until the
    model reports the goal satisfied in plain text, or the step count /
    wall-clock budget is exhausted. This is deliberately the counterpart
    to SkillExecutor: a skill runs a KNOWN sequence of steps; this runs
    an UNKNOWN one, decided live from observation.
    """

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        model_router,
        providers,
        max_steps: int = 8,
        max_runtime_seconds: float = 180.0,
        provider_health=None,
        default_allowed_roots: tuple = (),
    ):
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.model_router = model_router
        self.providers = providers
        self.max_steps = max_steps
        self.max_runtime_seconds = max_runtime_seconds
        self.provider_health = provider_health
        # Filesystem/terminal tools need SOME allowed roots to operate at
        # all. AgentRuntime.delegate has no per-call notion of "which
        # directories this mission may touch" (unlike ActionEngine, which
        # is always constructed with the project root) - so the worker
        # carries its own default, exactly like ExecutionContextFactory
        # does for the rest of the Brain. A caller may still override it
        # per run() call for a narrower mission.
        self.default_allowed_roots = tuple(default_allowed_roots)

    # -- tool contracts ----------------------------------------------------

    def _tool_schemas(self, allowed: list[str] | None) -> list[ToolSchema]:
        """Turn the LIVE tool registry into callable contracts for the
        model. Every tool VYOM has registered is a candidate unless the
        caller restricts the set via `allowed` (e.g. an agent's declared
        `tools` list)."""
        schemas: list[ToolSchema] = []
        for tool in self.tool_registry.list():
            if allowed and tool.metadata.name not in allowed:
                continue
            raw_schema = tool.metadata.input_schema or {}
            properties = dict(raw_schema.get("properties", {}))
            required = list(raw_schema.get("required", []))
            if not properties:
                # Built-in tool metadata mostly declares REQUIRED keys, not
                # a full per-property schema. A permissive string-typed
                # property per required key still lets the model supply
                # the arguments it needs; the tool's own validate() is the
                # real gate on correctness, exactly as it is for every
                # other caller of ToolExecutor.
                properties = {
                    key: {"type": "string", "description": f"'{key}' argument for the {tool.metadata.name} tool"}
                    for key in required
                }
            schemas.append(ToolSchema(
                name=tool.metadata.name,
                description=tool.metadata.description,
                parameters={"type": "object", "properties": properties, "required": required},
            ))
        return schemas

    # -- model decision, with the same fallback-chain pattern GeneralPlanner uses --

    async def _decide(self, goal: str, history: list[dict], tools: list[ToolSchema]):
        task = Task.from_create(TaskCreate(user_request=goal))
        profile = TaskProfile(domain=task.domain, complexity=4, deterministic=False, intent="autonomous_mission")
        decision = await self.model_router.route(task, profile)

        candidates: list[tuple[str, str]] = [(decision.primary_provider, decision.primary_model)]
        registry = getattr(self.model_router, "registry", None)
        for model_id in decision.fallback_models:
            provider_name = decision.primary_provider
            if registry is not None:
                record = registry.get(model_id)
                if record is not None:
                    provider_name = record.provider
            candidates.append((provider_name, model_id))

        last_error: Exception | None = None
        for provider_name, model_id in candidates:
            provider = self.providers.get(provider_name)
            if provider is None or not provider.configured or not provider.supports_tool_calls:
                continue
            if self.provider_health is not None and self.provider_health.rate_limited(provider_name, model_id):
                continue
            request = ProviderRequest(
                model=model_id, user_request=goal, system_instruction=SYSTEM_INSTRUCTION, profile=profile,
            )
            try:
                if self.provider_health is None:
                    response = await provider.generate_with_tools(request, tools, history)
                else:
                    async with self.provider_health.slot(provider_name, model_id):
                        if self.provider_health.rate_limited(provider_name, model_id):
                            continue
                        response = await provider.generate_with_tools(request, tools, history)
            except ProviderRateLimitError as error:
                last_error = error
                if self.provider_health is not None:
                    self.provider_health.record_rate_limit(
                        provider_name, model_id, daily_quota=getattr(error, "daily_quota", False))
                continue
            if self.provider_health is not None:
                self.provider_health.record_success(provider_name, model_id)
            return response

        if last_error is not None:
            raise last_error
        raise AutonomousMissionError(
            "No configured model with tool-calling support and remaining quota is available")

    # -- the bounded loop ----------------------------------------------------

    async def run(
        self,
        goal: str,
        task: Task,
        emit: EventEmitter,
        *,
        permission_level: PermissionLevel = PermissionLevel.L1,
        allowed_roots: tuple | None = None,
        allowed_tools: list[str] | None = None,
    ) -> ExecutionResult:
        """Run the bounded multi-step ReAct loop for `goal`. Returns an
        ExecutionResult compatible with the rest of the Brain: real
        evidence, structured step-by-step data, and a `verification.passed`
        flag other callers (AgentRuntime.delegate) already know to check."""
        tools = self._tool_schemas(allowed_tools)
        if not tools:
            raise AutonomousMissionError("No tools are registered/allowed for this autonomous mission")

        context = ToolContext(
            task_id=task.id,
            permission_level=permission_level,
            allowed_roots=allowed_roots if allowed_roots is not None else self.default_allowed_roots,
            emit=emit,
        )

        history: list[dict] = []
        steps: list[AutonomousStepRecord] = []
        evidence: list[str] = []
        started = time.perf_counter()
        final_text = ""
        hit_step_bound = False

        await emit(
            "task_planning",
            f"Autonomous mission planning for: {goal[:120]}",
            {"available_tools": [schema.name for schema in tools], "max_steps": self.max_steps},
        )

        for step_index in range(self.max_steps):
            elapsed = time.perf_counter() - started
            if elapsed >= self.max_runtime_seconds:
                final_text = (
                    f"Stopped at the mission time budget ({self.max_runtime_seconds:.0f}s) after "
                    f"{len(steps)} step(s)."
                )
                break

            response = await self._decide(goal, history, tools)

            if not response.tool_calls:
                final_text = response.text.strip() or "Mission finished with no further action needed."
                break

            call = response.tool_calls[0]
            await emit(
                "task_progress",
                f"Step {step_index + 1}/{self.max_steps}: deciding to call {call.name}",
                {"step": step_index + 1, "tool": call.name, "arguments": dict(call.arguments)},
            )

            remaining = max(self.max_runtime_seconds - (time.perf_counter() - started), 1.0)
            error_text: str | None = None
            result = None
            try:
                result = await asyncio.wait_for(
                    self.tool_executor.invoke(call.name, dict(call.arguments), context),
                    timeout=remaining,
                )
            except Exception as error:  # unregistered tool name, timeout, permission, etc.
                error_text = str(error)

            if result is None:
                success = False
                observation_text = f"error: {error_text}"
            else:
                success = result.success
                observation_text = result.summary if success else (result.error or result.summary)
                for item in result.evidence:
                    evidence.append(item.summary)

            steps.append(AutonomousStepRecord(
                tool=call.name, inputs=dict(call.arguments), success=success, summary=str(observation_text)[:400],
            ))

            model_part: dict = {"functionCall": {"name": call.name, "args": dict(call.arguments)}}
            if call.thought_signature:
                model_part["thoughtSignature"] = call.thought_signature
            history.append({"role": "model", "parts": [model_part]})
            history.append({"role": "user", "parts": [
                {"functionResponse": {"name": call.name, "response": {
                    "ok": success, "result": str(observation_text)[:4000],
                }}},
            ]})
        else:
            hit_step_bound = True
            final_text = f"Stopped after reaching the {self.max_steps}-step bound."

        successful_steps = [step for step in steps if step.success]
        # Passed means: real progress was made (at least one successful
        # tool call), or the goal genuinely needed no tool call and the
        # model still produced a real finishing statement (not just "no
        # action was taken" from hitting the bound with zero steps).
        passed = bool(successful_steps) or (not steps and not hit_step_bound and bool(final_text))

        response_text = final_text or ("Mission stopped without a final answer." if steps else "No action was taken.")
        structured = {
            "mission_goal": goal,
            "steps": [
                {"tool": step.tool, "inputs": step.inputs, "success": step.success, "summary": step.summary}
                for step in steps
            ],
            "step_count": len(steps),
            "hit_step_bound": hit_step_bound,
            "verification": {"passed": passed, "summary": response_text[:300]},
        }
        return ExecutionResult(
            response=response_text,
            structured_data=structured,
            evidence=evidence or ([f"{len(steps)} tool step(s) executed"] if steps else []),
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

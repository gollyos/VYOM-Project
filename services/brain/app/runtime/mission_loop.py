from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

from app.reliability.checkpoints import CheckpointStore, TaskCheckpoint
from app.runtime.error_messages import humanise_observation
from app.schemas.events import EventType
from app.schemas.tasks import TaskStatus

from .cognitive_runtime import CognitiveRuntime

StepExecutor = Callable[[str, dict], Awaitable[dict]]   # (step title, context) -> {ok, output}
StepVerifier = Callable[[str, dict], Awaitable[bool]]   # (step title, result) -> verified


@dataclass
class MissionLimits:
    max_steps: int = 20
    max_retries_per_step: int = 2
    max_runtime_seconds: float = 900.0
    max_model_calls: int = 15
    max_tool_calls: int = 40
    budget: float = 1.0


@dataclass
class MissionStepResult:
    title: str
    status: str            # completed | failed | skipped | needs_approval
    attempts: int = 0
    output: dict = field(default_factory=dict)
    verified: bool = False
    error: str | None = None


@dataclass
class MissionState:
    mission_id: str
    goal: str
    plan: list[str] = field(default_factory=list)
    current_step: int = 0
    completed: list[MissionStepResult] = field(default_factory=list)
    budget_used: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    pending_approval: str | None = None
    last_verified_state: str | None = None
    status: str = "running"   # running | paused | needs_approval | completed | failed | cancelled
    started_at: float = field(default_factory=time.monotonic)
    experience_saved: bool = False


class MissionLoop:
    """The main autonomous working loop:

    Goal -> resolve context -> plan -> execute step -> observe ->
    verify -> on failure: inspect + retrieve experience + alternative
    strategy + bounded retry -> continue -> final verification ->
    learn -> report.

    Bounded by MissionLimits (never endless); checkpoints persist
    through the EXISTING CheckpointStore; L2/L3 steps pause the mission
    (not abandon it); every event streams operational messages through
    the existing event bus (no chain-of-thought, no dashboard)."""

    def __init__(
        self,
        *,
        cognitive: CognitiveRuntime,
        planner,                       # existing runtime planner (create_plan)
        checkpoint_store: CheckpointStore,
        learner=None,                  # Phase 14 AdaptiveLearner
        emit=None,                     # async (task_id, EventType, message, payload)
        task_store=None,
        limits: MissionLimits | None = None,
    ):
        self.cognitive = cognitive
        self.planner = planner
        self.checkpoints = checkpoint_store
        self.learner = learner
        self.emit = emit
        self.task_store = task_store
        self.limits = limits or MissionLimits()
        self._cancel_events: dict[str, asyncio.Event] = {}

    async def _emit(self, mission_id: str, event_type: EventType, message: str, payload: dict | None = None) -> None:
        if self.emit is not None:
            await self.emit(mission_id, event_type, message, payload or {})

    # -- lifecycle -------------------------------------------------------------

    async def run(
        self,
        goal: str,
        *,
        executor: StepExecutor,
        verifier: StepVerifier | None = None,
        step_permissions: dict[str, str] | None = None,   # title -> "L0".."L3"
        mission_id: str | None = None,
        start_step: int = 0,                              # resume from checkpoint
        context: dict | None = None,                      # caller-supplied extras (e.g. url), merged under "goal"
        plan: list[str] | None = None,                    # caller-supplied plan; skips generic decomposition
    ) -> MissionState:
        mission = MissionState(mission_id=mission_id or f"mission_{uuid4().hex[:12]}", goal=goal)
        mission.current_step = start_step
        cancel = asyncio.Event()
        self._cancel_events[mission.mission_id] = cancel
        step_permissions = step_permissions or {}

        try:
            await self._emit(mission.mission_id, EventType.TASK_UNDERSTANDING, f"Resolving context for: {goal[:80]}")
            # Resolve context (cognitive runtime, memory-first). Caller-supplied
            # extras come first so "goal" always reflects the real mission goal.
            context = {**(context or {}), "goal": goal}
            if self.cognitive is not None:
                answer = await self.cognitive.answer_from_memory(goal)
                if answer:
                    context["prior_knowledge"] = answer
                    await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                                     f"Using prior knowledge: {str(answer.get('answer'))[:80]}")

            # Plan through the existing planner contract (a plan of titles).
            # A caller that has already resolved the goal into concrete,
            # executable steps supplies them directly: the generic
            # decomposition ("Understand the task and constraints", ...)
            # produces titles no tool can execute, which would turn a real
            # mission into a sequence of skipped steps.
            await self._emit(mission.mission_id, EventType.TASK_PLANNING, "Planning mission steps")
            mission.plan = plan if plan else await self._plan(goal, context)

            while mission.current_step < len(mission.plan):
                try:
                    self._check_limits(mission)
                except MissionLimitError as limit:
                    mission.status = "failed"
                    await self._checkpoint(mission)
                    await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                                     f"Mission stopped honestly at its limits: {limit}",
                                     {"mission_outcome": "failed"})
                    await self._learn(mission, success=False)
                    return mission
                if cancel.is_set():
                    mission.status = "cancelled"
                    await self._checkpoint(mission)
                    await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                                     "Mission cancelled; checkpoint persisted",
                                     {"mission_outcome": "cancelled"})
                    return mission

                title = mission.plan[mission.current_step]

                # Approval boundary: pause only this step, never abandon.
                permission = step_permissions.get(title, "L1")
                if permission in ("L2", "L3"):
                    mission.status = "needs_approval"
                    mission.pending_approval = title
                    await self._checkpoint(mission)
                    await self._emit(mission.mission_id, EventType.APPROVAL_REQUIRED,
                                     f"Mission step '{title}' requires {permission} approval; mission paused at checkpoint")
                    return mission

                result = await self._execute_step(mission, title, context, executor, verifier, cancel)
                mission.completed.append(result)

                if result.status == "completed" and result.verified:
                    mission.last_verified_state = title
                    mission.current_step += 1
                    await self._checkpoint(mission)
                elif result.status == "failed":
                    mission.status = "failed"
                    await self._checkpoint(mission)
                    await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                                     f"Mission step '{title}' failed after adaptation attempts: {result.error}",
                                     {"mission_outcome": "failed"})
                    await self._learn(mission, success=False)
                    return mission
                else:
                    mission.current_step += 1
                self._check_runtime(mission)

            # Final verification + learn + report.
            #
            # TERMINAL EVENTS ARE NOT OURS TO EMIT. TaskRuntime owns
            # terminalization: it runs goal verification FIRST and only then
            # emits the one task_completed/task_failed. When this loop also
            # emitted its own, the bus carried two terminals per task - the
            # UI rendered the result twice and TTS spoke it twice - and the
            # mission's event could even claim COMPLETED before the goal
            # verifier had run. The outcome travels as a progress event;
            # the caller turns the returned MissionState into the one
            # authoritative terminal.
            final_ok = bool(mission.completed) and all(step.status == "completed" for step in mission.completed)
            mission.status = "completed" if final_ok else "failed"
            await self._checkpoint(mission)
            await self._learn(mission, success=final_ok)
            # The user-facing message describes the OUTCOME, never the
            # instrumentation. "Mission finished: 5 step(s), 2 verified"
            # told the user nothing about whether their goal happened, and
            # read as a success even when it had not.
            achieved = [step.title for step in mission.completed if step.verified]
            await self._emit(
                mission.mission_id,
                EventType.TASK_PROGRESS,
                ("; ".join(achieved)[:300] if final_ok and achieved
                 else "I could not complete that."),
                {"mission_outcome": "completed" if final_ok else "failed",
                 "steps": len(mission.completed),
                 "verified": sum(1 for step in mission.completed if step.verified)},
            )
            return mission
        finally:
            self._cancel_events.pop(mission.mission_id, None)


    # -- adaptive (tool-calling) mode ------------------------------------
    #
    # `run` above executes a plan that is known up-front. This variant
    # decides the NEXT action from what was actually observed, which is
    # what an unknown goal needs: no prebuilt step list exists for
    # "review this company" or "why is my PC slow". Same class, same
    # bounds, same checkpointing and learning - only the source of the
    # next step differs.

    async def run_adaptive(
        self,
        goal: str,
        *,
        planner,                       # GeneralPlanner
        execute_call,                  # async (ToolCall) -> {"ok": bool, "output": ..., "error": ...}
        require_tool_use: bool = True,  # actionable/fresh goals may not be answered in prose
        mission_id: str | None = None,
    ) -> MissionState:
        """Goal -> choose next action -> execute -> observe -> repeat ->
        verify. Bounded by the same MissionLimits as every other mission."""
        mission = MissionState(mission_id=mission_id or f"mission_{uuid4().hex[:12]}", goal=goal)
        cancel = asyncio.Event()
        self._cancel_events[mission.mission_id] = cancel
        tools = planner.relevant_tools(goal)
        history: list[dict] = []
        final_text = ""
        # Grounding state: a freshness-dependent goal must be answered from
        # evidence a tool actually produced, never from model knowledge.
        from app.runtime.planner import needs_fresh_evidence

        grounding_required = needs_fresh_evidence(goal)
        grounded = False
        grounding_challenged = False
        # Repetition guard: an identical call repeated with the same
        # arguments is not progress. Without this a planner that could not
        # satisfy a goal spent its entire model budget (15 calls, ~60s)
        # re-listing the same directory.
        seen_calls: dict[str, int] = {}
        repeated_without_progress = False
        repetition_warnings = 0

        try:
            await self._emit(mission.mission_id, EventType.TASK_UNDERSTANDING,
                             f"Planning with {len(tools)} available capability contract(s)")
            if self.cognitive is not None:
                prior = await self.cognitive.answer_from_memory(goal)
                if prior:
                    history.append({
                        "role": "user",
                        "parts": [{"text": f"Verified prior knowledge: {str(prior.get('answer'))[:400]}"}],
                    })

            while True:
                try:
                    self._check_limits(mission)
                except MissionLimitError as limit:
                    mission.status = "failed"
                    await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                                     f"Mission stopped honestly at its limits: {limit}",
                                     {"mission_outcome": "failed"})
                    await self._checkpoint(mission)
                    await self._learn(mission, success=False)
                    return mission
                if cancel.is_set():
                    mission.status = "cancelled"
                    await self._checkpoint(mission)
                    await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                                     "Mission cancelled; checkpoint persisted",
                                     {"mission_outcome": "cancelled"})
                    return mission

                if repeated_without_progress and repetition_warnings >= 1:
                    await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                                     "No available capability advanced this goal",
                                     {"mission_outcome": "failed"})
                    mission.status = "failed"
                    await self._checkpoint(mission)
                    await self._learn(mission, success=False)
                    setattr(mission, "final_text", "")
                    return mission
                if repeated_without_progress:
                    repetition_warnings += 1
                    repeated_without_progress = False
                # A MISSION LOOP IS NOT AN LLM LOOP.
                #
                # Re-entering the model after every successful tool call is
                # what turned one goal into a dozen generateContent
                # requests. Reasoning is for deciding what to do when the
                # answer is not already determined - a tool that succeeded
                # and returned usable evidence has ALREADY determined the
                # next state. The model is re-entered only when reality
                # says something unexpected: a failure, an empty result, or
                # a genuine ambiguity.
                if mission.completed and not self._needs_reasoning(mission, grounded):
                    final_text = self._summarise_observations(mission)
                    break

                mission.model_calls += 1
                await self._emit(mission.mission_id, EventType.TASK_PLANNING,
                                 "Deciding the next action from what has been observed")
                # A per-minute burst limit is a WAIT, not a failure: that
                # quota returns in seconds, and one 429 should not end a
                # mission that may be minutes from verified completion.
                # The quota budgeter paces requests to stay under the
                # limit in the first place; this bounded resume covers
                # the residual case. A DAILY quota (or two waits already
                # spent) still fails honestly - that allowance does not
                # come back today and the router must move to a sibling.
                from app.providers.base import ProviderRateLimitError

                response = None
                rate_limit_waits = 0
                while True:
                    try:
                        response = await planner.next_action(goal, history, tools)
                        break
                    except ProviderRateLimitError as limit_error:
                        if limit_error.daily_quota or rate_limit_waits >= 2:
                            mission.status = "failed"
                            await self._emit(
                                mission.mission_id, EventType.TASK_PROGRESS,
                                "The reasoning provider is rate limited, so I stopped rather than "
                                "retrying against it.",
                                {"mission_outcome": "failed", "rate_limited": True,
                                 "daily_quota": limit_error.daily_quota,
                                 "verified_steps": sum(1 for step in mission.completed if step.verified)})
                            await self._checkpoint(mission)
                            await self._learn(mission, success=False)
                            setattr(mission, "final_text",
                                    "The reasoning provider is rate limited, so I stopped rather than "
                                    "retrying against it.")
                            return mission
                        wait_seconds = (8.0, 20.0)[rate_limit_waits]
                        rate_limit_waits += 1
                        await self._emit(
                            mission.mission_id, EventType.TASK_PROGRESS,
                            f"Provider burst limit reached; resuming in {wait_seconds:.0f}s",
                            {"rate_limited": True, "resuming_in_seconds": wait_seconds})
                        await asyncio.sleep(wait_seconds)

                if not response.tool_calls:
                    # No action chosen. For an actionable or freshness
                    # dependent goal that is a refusal to act, not an
                    # answer - VYOM never presents model prose as a result
                    # it did not obtain.
                    from app.runtime.planner import claims_inability

                    # GROUNDING GATE. A goal that depends on the world right
                    # now may only be answered from evidence a tool actually
                    # returned. Without this the model happily produced a
                    # detailed company "review" after its browser call had
                    # FAILED - fluent, confident and entirely invented.
                    if grounding_required and not grounded:
                        if not grounding_challenged:
                            grounding_challenged = True
                            history.append({"role": "model", "parts": [{"text": response.text[:400]}]})
                            history.append({"role": "user", "parts": [{"text":
                                "No tool call has returned usable evidence for this request. Do not "
                                "answer from your own knowledge. Either call a tool that can verify "
                                "it, or reply with exactly: UNVERIFIED"}]})
                            continue
                        mission.status = "failed"
                        await self._emit(
                            mission.mission_id, EventType.TASK_PROGRESS,
                            "No tool returned evidence for this request; VYOM will not answer from "
                            "model knowledge alone",
                            {"mission_outcome": "failed"})
                        await self._checkpoint(mission)
                        await self._learn(mission, success=False)
                        setattr(mission, "final_text",
                                "No tool returned evidence for this request, so I will not "
                                "answer from model knowledge alone.")
                        return mission

                    if require_tool_use and not mission.completed:
                        if claims_inability(response.text):
                            mission.status = "failed"
                            await self._emit(
                                mission.mission_id, EventType.TASK_PROGRESS,
                                "The planner claimed an inability instead of using an available capability",
                                {"mission_outcome": "failed"})
                            await self._learn(mission, success=False)
                            setattr(mission, "final_text",
                                    "A capability for this exists, but the planner did not use it. "
                                    "I will not pretend that is a completed request.")
                            return mission
                        # One bounded nudge, then accept reality.
                        history.append({"role": "model", "parts": [{"text": response.text[:500]}]})
                        history.append({"role": "user", "parts": [{"text":
                            "That answer was not obtained from any tool. Call the appropriate "
                            "function to actually perform or verify this now."}]})
                        require_tool_use = False
                        continue
                    final_text = response.text
                    break

                for call in response.tool_calls:
                    if cancel.is_set():
                        break
                    signature = f"{call.name}:{sorted(call.arguments.items())}"
                    seen_calls[signature] = seen_calls.get(signature, 0) + 1
                    if seen_calls[signature] > 2:
                        await self._emit(
                            mission.mission_id, EventType.TASK_PROGRESS,
                            f"'{call.name}' repeated without progress; stopping this approach")
                        history.append({"role": "user", "parts": [{"text":
                            f"You have already called {call.name} with those arguments and it did "
                            "not advance the goal. Either choose a DIFFERENT capability or, if none "
                            "can satisfy this request, say plainly what is missing."}]})
                        repeated_without_progress = True
                        break
                    mission.tool_calls += 1
                    await self._emit(mission.mission_id, EventType.TOOL_SELECTED,
                                     f"Selected {call.name}", {"tool": call.name, "arguments": call.arguments})
                    observation = await execute_call(call)
                    step = MissionStepResult(
                        title=f"{call.name}({', '.join(f'{k}={str(v)[:40]}' for k, v in call.arguments.items())})",
                        status="completed" if observation.get("ok") else "failed",
                        attempts=1, output=observation, verified=bool(observation.get("ok")),
                        error=None if observation.get("ok") else str(observation.get("error"))[:300],
                    )
                    mission.completed.append(step)
                    if step.verified:
                        mission.last_verified_state = call.name
                        # Substantive output only: an empty or trivial result
                        # is not evidence that the goal was answered.
                        if len(str(observation.get("output", ""))) > 120:
                            grounded = True
                    await self._emit(
                        mission.mission_id,
                        EventType.TOOL_COMPLETED if step.verified else EventType.TOOL_FAILED,
                        f"{call.name} {'completed' if step.verified else 'failed'}",
                        {"tool": call.name, "summary": str(observation.get("output", observation.get("error")))[:300]},
                    )
                    # Feed the REAL result back so the next decision is
                    # made from observation, not assumption.
                    model_part: dict = {"functionCall": {"name": call.name, "args": call.arguments}}
                    if call.thought_signature:
                        model_part["thoughtSignature"] = call.thought_signature
                    history.append({"role": "model", "parts": [model_part]})
                    history.append({"role": "user", "parts": [
                        {"functionResponse": {"name": call.name, "response": {
                            "ok": bool(observation.get("ok")),
                            "result": str(observation.get("output", observation.get("error")))[:4000],
                        }}}]})
                await self._checkpoint(mission)

            verified = sum(1 for step in mission.completed if step.verified)
            mission.status = "completed" if (mission.completed and verified) or not require_tool_use else "failed"
            if not mission.completed and not require_tool_use:
                mission.status = "completed"
            await self._checkpoint(mission)
            await self._learn(mission, success=mission.status == "completed")
            # Operational detail goes in the payload for the canvas and the
            # logs; the human-readable message is never a tool counter.
            # No terminal event here - TaskRuntime verifies the goal and
            # emits the ONE terminal itself (see run()'s note).
            await self._emit(
                mission.mission_id,
                EventType.TASK_PROGRESS,
                (final_text.strip() or ("Done." if mission.status == "completed"
                                        else "I could not complete that."))[:400],
                {"mission_outcome": mission.status,
                 "tool_calls": len(mission.completed), "verified": verified,
                 "model_calls": mission.model_calls})
            mission.plan = [step.title for step in mission.completed]
            setattr(mission, "final_text", final_text)
            return mission
        finally:
            self._cancel_events.pop(mission.mission_id, None)

    #: A mission may re-enter the model only this many times. One initial
    #: plan plus a bounded number of genuine adaptations; beyond that the
    #: mission reports what it actually has rather than reasoning in
    #: circles at the provider's expense.
    MAX_REASONING_ENTRIES = 3

    @staticmethod
    def _needs_reasoning(mission: MissionState, grounded: bool) -> bool:
        """Does reality require a NEW decision, or is the next step already
        determined by what was just observed?"""
        last = mission.completed[-1]
        # A failure, or a result too thin to be evidence, is exactly when a
        # different approach has to be chosen - that is worth a model call.
        if not last.verified:
            return True
        if not grounded:
            return True
        # Beyond the bounded adaptation budget, stop reasoning and report.
        if mission.model_calls >= MissionLoop.MAX_REASONING_ENTRIES:
            return False
        # A successful, substantive tool result that answers the goal needs
        # no further deliberation.
        return False

    @staticmethod
    def _summarise_observations(mission: MissionState) -> str:
        """Report from what the tools actually returned, with no model call."""
        for step in reversed(mission.completed):
            if not step.verified:
                continue
            output = step.output.get("output")
            if output in (None, "", [], {}):
                continue
            if isinstance(output, str):
                return output[:1500]
            return humanise_observation(output)[:1500]
        return ""

    async def _plan(self, goal: str, context: dict) -> list[str]:
        """Plan via the existing planner contract when available; a
        deterministic goal decomposition otherwise (no model call)."""
        if self.planner is not None and hasattr(self.planner, "plan_mission"):
            return await self.planner.plan_mission(goal, context)
        # Deterministic goal-derived decomposition: a goal that already
        # enumerates its steps (comma/and separated) becomes the plan;
        # otherwise a safe generic decomposition is used. No model call.
        import re

        parts = [part.strip() for part in re.split(r",\s+|\s+and\s+", goal) if part.strip()]
        actionable = [part for part in parts if len(part) > 3]
        if len(actionable) >= 3:
            return [part[0].upper() + part[1:] for part in actionable]
        return [
            "Understand the task and constraints",
            "Gather the required inputs",
            "Execute the core work",
            "Verify the result against the goal",
            "Report the outcome with evidence",
        ]

    async def _execute_step(self, mission: MissionState, title: str, context: dict,
                            executor: StepExecutor, verifier: StepVerifier | None,
                            cancel: asyncio.Event) -> MissionStepResult:
        result = MissionStepResult(title=title, status="failed")
        for attempt in range(1, self.limits.max_retries_per_step + 2):  # initial + bounded retries
            if cancel.is_set():
                result.status = "skipped"
                return result
            self._check_limits(mission)
            await self._emit(mission.mission_id, EventType.TASK_PROGRESS, f"Executing: {title} (attempt {attempt})")
            step_context = {**context, "attempt": attempt, "mission_id": mission.mission_id}
            step_task = asyncio.create_task(executor(title, step_context))
            cancel_wait = asyncio.create_task(cancel.wait())
            done, _pending = await asyncio.wait(
                {step_task, cancel_wait}, return_when=asyncio.FIRST_COMPLETED)
            if cancel_wait in done and cancel.is_set():
                step_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await step_task
                cancel_wait.cancel()
                result.status = "skipped"
                return result
            cancel_wait.cancel()
            try:
                outcome = step_task.result()
            except Exception as error:
                outcome = {"ok": False, "error": str(error)}
            mission.tool_calls += 1
            result.attempts = attempt
            result.output = outcome
            if outcome.get("ok"):
                verified = True
                if verifier is not None:
                    await self._emit(mission.mission_id, EventType.TASK_VERIFYING if hasattr(EventType, "TASK_VERIFYING") else EventType.TASK_PROGRESS,
                                     f"Verifying: {title}")
                    verified = bool(await verifier(title, outcome))
                result.verified = verified
                result.status = "completed"
                if not verified:
                    result.output["verification"] = "unverified"
                await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                                 f"Step '{title}' {'verified' if verified else 'completed (unverified)'}")
                return result
            # Failure: inspect + retrieve relevant experience + adapt.
            await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                             f"Step '{title}' failed (attempt {attempt}); inspecting and adapting")
            context["last_failure"] = str(outcome.get("error", ""))[:200]
            if self.cognitive is not None:
                resolution = await self.cognitive.resolution.resolve(f"fix: {title} {context['last_failure']}")
                if resolution.resolved:
                    context["adaptation_hint"] = resolution.hits[0]
                    await self._emit(mission.mission_id, EventType.TASK_PROGRESS,
                                     f"Adapting using {resolution.source} from prior experience")
        result.error = str(result.output.get("error", "exhausted bounded retries"))
        return result

    # -- bounds -----------------------------------------------------------------

    def _check_limits(self, mission: MissionState) -> None:
        if mission.tool_calls >= self.limits.max_tool_calls:
            raise MissionLimitError(f"tool-call limit reached ({self.limits.max_tool_calls}); pausing honestly")
        if mission.model_calls >= self.limits.max_model_calls:
            raise MissionLimitError(f"model-call limit reached ({self.limits.max_model_calls})")
        if len(mission.completed) >= self.limits.max_steps:
            raise MissionLimitError(f"step limit reached ({self.limits.max_steps})")
        self._check_runtime(mission)

    def _check_runtime(self, mission: MissionState) -> None:
        elapsed = time.monotonic() - mission.started_at
        if elapsed > self.limits.max_runtime_seconds:
            raise MissionLimitError(f"runtime limit reached ({self.limits.max_runtime_seconds:.0f}s)")

    # -- checkpoint / learn --------------------------------------------------------

    async def _checkpoint(self, mission: MissionState) -> None:
        """Reuses the EXISTING checkpoint store — no new storage."""
        await self.checkpoints.save(TaskCheckpoint(
            task_id=mission.mission_id,
            task_state={"status": mission.status, "goal": mission.goal,
                        "current_step": mission.current_step, "plan": mission.plan,
                        "budget_used": mission.budget_used,
                        "pending_approval": mission.pending_approval,
                        "last_verified_state": mission.last_verified_state},
            current_plan_step=mission.plan[mission.current_step] if mission.current_step < len(mission.plan) else None,
            completed_steps=[step.title for step in mission.completed if step.status == "completed"],
            evidence=[f"{step.title}:{'verified' if step.verified else step.status}" for step in mission.completed],
        ))

    async def _learn(self, mission: MissionState, *, success: bool) -> None:
        """Feeds the real mission outcome into the Phase 14 learner."""
        if self.learner is None:
            return
        from app.adaptive import Experience
        from app.adaptive.experience_store import fingerprint

        await self.learner.store.record(Experience(
            task_type="mission", task_fingerprint=fingerprint(mission.goal),
            goal=mission.goal, domain="system",
            result_summary=f"mission {mission.status}: {len(mission.completed)} steps, "
                           f"{sum(1 for s in mission.completed if s.verified)} verified",
            success=success, verification_score=0.8 if success else 0.2,
            retries=sum(step.attempts for step in mission.completed),
            conditions={"mission": True},
        ))
        mission.experience_saved = True

    # -- control ----------------------------------------------------------------------

    def cancel(self, mission_id: str) -> bool:
        event = self._cancel_events.get(mission_id)
        if event is None:
            return False
        event.set()
        return True

    async def resume(self, mission_id: str, *, executor: StepExecutor,
                     verifier: StepVerifier | None = None,
                     step_permissions: dict[str, str] | None = None) -> MissionState | None:
        """Resume a paused/approval-gated mission from its checkpoint —
        never from zero."""
        checkpoint = await self.checkpoints.get(mission_id)
        if checkpoint is None:
            return None
        state = checkpoint.task_state
        return await self.run(
            state.get("goal", ""),
            executor=executor, verifier=verifier, step_permissions=step_permissions,
            mission_id=mission_id, start_step=state.get("current_step", 0),
        )


class MissionLimitError(Exception):
    pass

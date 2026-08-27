from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone

from app.persistence.model_performance_store import ModelPerformanceStore
from app.persistence.task_store import TaskStore
from app.providers.base import ProviderError, ProviderRegistry
from app.routing.model_registry import ModelRegistry
from app.routing.model_router import ModelRouter, NoModelAvailableError
from app.routing.provider_health import ProviderHealth
from app.routing.usage_tracker import UsageTracker
from app.schemas.approvals import ApprovalRequest, PermissionLevel
from app.schemas.events import BrainEvent, EventType
from app.schemas.routing import RoutingDecision
from app.schemas.tasks import ActionProvenance, Task, TaskCreate, TaskDomain, TaskStatus
from app.security.permission_engine import PermissionEngine
from app.execution.action_engine import ActionEngine
from app.execution.visibility import classify_visibility
from app.learning.intelligence_engine import IntelligenceEngine
from app.briefing.engine import BusinessEngine
from app.phase8.engine import Phase8Engine
from app.phase9.engine import Phase9Engine
from app.phase10.engine import Phase10Engine
from app.phase11.engine import Phase11Engine

from .event_bus import EventBus
from .executor import Executor
from .planner import Planner
from .task_classifier import TaskClassifier
from .verifier import Verifier


class TaskCancelled(Exception):
    pass


#: GoalVerifier.verify_goal() prefixes each clause with its internal check
#: name for task.metadata (diagnostic, machine-groupable - "search_performed:
#: the browser was opened but no search or navigation was observed"). That
#: prefix is jargon no user asked for; VYOM spoke/showed it verbatim because
#: nothing stripped it before it reached the response the user actually
#: reads or hears. This strips it for user-facing text only - the raw,
#: prefixed evidence still goes into task.metadata untouched.
_GOAL_EVIDENCE_PREFIX = re.compile(r"^[a-z][a-z0-9_]*:\s*")


def _humanize_goal_evidence(evidence: str) -> str:
    parts = [part.strip() for part in evidence.split(";") if part.strip()]
    return "; ".join(_GOAL_EVIDENCE_PREFIX.sub("", part) for part in parts)


class TaskRuntime:
    #: How many times a single request chain may self-heal-retry before
    #: VYOM stops and reports the failure as-is - a bound against ever
    #: looping forever on a target that never stabilizes, not a
    #: guarantee any given retry succeeds.
    RETRY_CHAIN_LIMIT = 2

    def __init__(
        self,
        *,
        task_store: TaskStore,
        performance_store: ModelPerformanceStore,
        event_bus: EventBus,
        model_registry: ModelRegistry,
        providers: ProviderRegistry,
        model_router: ModelRouter,
        provider_health: ProviderHealth,
        classifier: TaskClassifier,
        planner: Planner,
        executor: Executor,
        verifier: Verifier,
        permission_engine: PermissionEngine,
        usage_tracker: UsageTracker,
        action_engine: ActionEngine | None = None,
        intelligence_engine: IntelligenceEngine | None = None,
        business_engine: BusinessEngine | None = None,
        phase8_engine: Phase8Engine | None = None,
        phase9_engine: Phase9Engine | None = None,
        phase10_engine: Phase10Engine | None = None,
        phase11_engine: Phase11Engine | None = None,
        phase13_engine=None,
        cognitive_runtime=None,
        mission_loop=None,
    ) -> None:
        self.task_store = task_store
        self.performance_store = performance_store
        self.event_bus = event_bus
        self.model_registry = model_registry
        self.providers = providers
        self.model_router = model_router
        self.provider_health = provider_health
        self.classifier = classifier
        self.planner = planner
        self.executor = executor
        self.verifier = verifier
        self.permission_engine = permission_engine
        self.usage_tracker = usage_tracker
        self.action_engine = action_engine
        self.intelligence_engine = intelligence_engine
        self.business_engine = business_engine
        self.phase8_engine = phase8_engine
        self.phase9_engine = phase9_engine
        self.phase10_engine = phase10_engine
        self.phase11_engine = phase11_engine
        self.phase13_engine = phase13_engine
        self.cognitive_runtime = cognitive_runtime
        self.mission_loop = mission_loop
        self.general_planner = None  # attached post-construction in main.py, like cognitive_runtime/mission_loop
        self.multi_agent_orchestrator = None  # attached post-construction; splits a multi-domain goal across role agents
        self.progress_tracker = None  # attached post-construction; live per-task "which agent/step" board
        self.llm_triage = None  # attached post-construction; optional LLM intent gate for unrecognised text
        self.memory_retriever = None  # attached post-construction in main.py, same pattern
        self.memory_store = None  # attached post-construction in main.py, same pattern
        self.memory_manager = None  # attached post-construction in main.py, same pattern
        self.knowledge_service = None  # attached post-construction; the "khud ka Wikipedia" recall-first service
        self.automation_store = None  # attached post-construction; one durable scheduler/store
        self.conversation_store = None  # attached post-construction; raw turn-by-turn transcript (see app/persistence/conversation_store.py)
        self.plugin_registry = None  # attached post-construction; see app/plugins/registry.py
        self.mcp_connector = None  # attached post-construction; async callable(service_name) -> dict, the same lookup POST /api/mcp/connect uses
        self.learn_service = None  # attached post-construction; see app/skills/learn.py LearnService
        from .verifier import GoalVerifier, PostconditionVerifier
        self.postconditions = PostconditionVerifier()
        # The ONE authority that can promote a task to VERIFIED_COMPLETE.
        # Every completion path in this runtime funnels through
        # _finish_result, and _finish_result consults this before it is
        # allowed to write TaskStatus.COMPLETED.
        self.goal_verifier = GoalVerifier(self.postconditions)
        self.cost_tracker = None  # attached post-construction in main.py, like cognitive_runtime/mission_loop
        self.ownership_registry = None  # attached post-construction in main.py, same pattern
        self.active: dict[str, asyncio.Task[None]] = {}
        self.last_routing: RoutingDecision | None = None
        # ONE TASK -> ONE TERMINAL EVENT.
        #
        # task_completed was being published twice for the same task_id -
        # once by MissionLoop and again by _finish_result - so the UI
        # rendered the result twice and TTS spoke it twice. task_id is the
        # identity authority here; correlation_id is only tracing metadata.
        # Bounded so a long-lived Brain cannot grow this without limit.
        self._terminalized: OrderedDict[str, str] = OrderedDict()

    async def create_task(
        self, request: TaskCreate, *, provenance: ActionProvenance = ActionProvenance.USER_COMMAND
    ) -> Task:
        task = Task.from_create(request)
        # ACTION PROVENANCE. Every external app/window/browser action this
        # task can go on to trigger must trace back to why the task itself
        # was allowed to exist. Default is USER_COMMAND because every
        # normal entrypoint (voice/text via /api/tasks, /api/remote,
        # offline-queue replay) is a person's own request; callers that are
        # NOT a direct user command - the routine/automation step executor
        # - pass their own provenance explicitly. ActionEngine.execute()
        # is the one place this is actually enforced before anything runs.
        task.metadata["provenance"] = provenance.value
        task.metadata["command_source"] = task.source
        task.metadata["context_id"] = task.context_id
        if task.correlation_id:
            task.metadata["correlation_id"] = task.correlation_id

        # KERNEL INTERRUPT. Recognised before classification, routing,
        # planning, memory or any capability - STOP outranks every
        # mission, including the one that is mid-flight. It costs zero
        # model calls and touches no tool.
        from .task_classifier import is_interrupt_command

        if is_interrupt_command(task.user_request):
            return await self._handle_interrupt(task)

        if "model you chose" in task.user_request.lower() or "explain model" in task.user_request.lower():
            if self.last_routing:
                task.metadata["routing_to_explain"] = self.last_routing.model_dump(mode="json")
        await self.task_store.save(task)
        await self._emit(task, EventType.TASK_CREATED, "Task accepted and persisted")
        self._start(task.id)
        return task

    @staticmethod
    def _is_open_command(request: str) -> bool:
        """Is this an instruction to OPEN the thing being referred to?"""
        lowered = (request or "").lower()
        return any(
            verb in lowered for verb in
            ("open", "kholo", "khol do", "kholiye", "launch", "start", "dikhao",
             "show", "chalu", "ओपन", "खोलो", "दिखाओ", "चालू")
        )

    async def _handle_interrupt(self, task: Task) -> Task:
        """Stop everything that is running and say so. Nothing else.

        No planner, no model, no filesystem, no browser. The application
        stays alive; only the work stops."""
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord

        task.metadata["kernel_interrupt"] = True
        await self.task_store.save(task)
        await self._emit(task, EventType.TASK_CREATED, "Stop received")

        # 1. Silence speech immediately - this reaches the voice runtime
        #    ahead of any other event so a queued completion cannot talk
        #    over the acknowledgement.
        await self._emit(task, EventType.TASK_PROGRESS, "Stopping",
                         {"interrupt": True, "stop_speech": True})

        # 2. Cancel every in-flight mission. A superseded task must never
        #    later speak, publish a completion, or write memory.
        cancelled: list[str] = []
        for other_id in list(self.active.keys()):
            if other_id == task.id:
                continue
            try:
                await self.cancel(other_id)
                cancelled.append(other_id)
            except Exception:
                continue

        task.status = TaskStatus.COMPLETED
        task.progress = 1
        task.completed_at = datetime.now(timezone.utc)
        task.assigned_model = None
        response = "Stopped." if cancelled else "Nothing was running, but I've stopped."
        task.result = ExecutionResult(
            response=response,
            structured_data={"interrupt": True, "cancelled_tasks": cancelled},
            evidence=[f"cancelled {len(cancelled)} running task(s)"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )
        await self.task_store.save(task)
        await self._emit(task, EventType.TASK_COMPLETED, response,
                         {"response": response, "interrupt": True,
                          "task": task.model_dump(mode="json")})
        return task

    def _start(self, task_id: str) -> None:
        current = self.active.get(task_id)
        if current and not current.done():
            return
        background = asyncio.create_task(self._run_guarded(task_id), name=f"vyom-{task_id}")
        self.active[task_id] = background

    async def _run_guarded(self, task_id: str) -> None:
        try:
            await self.run(task_id)
        finally:
            self.active.pop(task_id, None)

    async def run(self, task_id: str) -> None:
        task = await self.task_store.get(task_id)
        if task is None or task.status in {TaskStatus.CANCELLED, TaskStatus.COMPLETED}:
            return
        started = time.perf_counter()
        retries = 0
        fallback_used = False

        try:
            task.started_at = task.started_at or datetime.now(timezone.utc)
            await self._transition(task, TaskStatus.UNDERSTANDING, EventType.TASK_UNDERSTANDING, "Understanding the request")
            profile = self.classifier.classify(task.user_request)
            # Per-task visibility: decide BEFORE execution whether VYOM
            # should run this in the BACKGROUND (headless/invisible) or
            # VISUALLY on the user's screen (real non-headless browser /
            # real OS mouse). The browser manager reads this to pick
            # headless vs headed; the frontend may also minimize itself.
            profile.visibility = classify_visibility(task.user_request).value
            task.profile = profile
            task.domain = profile.domain
            task.complexity = profile.complexity
            task.criticality = profile.criticality
            task.permission_level = self.permission_engine.raise_to_intent_floor(
                self.permission_engine.classify(task.user_request), profile.intent
            )
            # mcp_connect / learn_skill are read-only lookups against
            # VYOM's own reviewed catalog and local skill authoring
            # respectively - never a consequential external action, even
            # when the request text happens to contain a normally-L2+
            # trigger word (e.g. "deploy" inside a learned workflow's
            # description). Capped explicitly rather than relying on
            # INTENT_FLOOR, which only ever RAISES a level, never lowers
            # one.
            if profile.intent in ("mcp_connect", "learn_skill"):
                task.permission_level = PermissionLevel.L1
            if profile.intent == "run_taught_skill" and self.intelligence_engine is not None:
                from app.skills.teachable import parse_skill_command

                skill_id, _ = parse_skill_command(task.user_request)
                taught_skill = self.intelligence_engine.skill_registry.get(skill_id)
                if taught_skill is None:
                    raise RuntimeError(f"Unknown taught skill: {skill_id}")
                order = {PermissionLevel.L0: 0, PermissionLevel.L1: 1, PermissionLevel.L2: 2, PermissionLevel.L3: 3}
                if order[taught_skill.required_permissions] > order[task.permission_level]:
                    task.permission_level = taught_skill.required_permissions
            task.requires_approval = self.permission_engine.requires_approval(task.permission_level)
            task.requires_tools = "tools" in profile.needs
            # ACTION PROVENANCE. Every externally observable action this
            # task causes is attributable to THIS trigger: a current user
            # command. There is no other authorised way for a model, a
            # skill or a background tick to open an application - and the
            # desktop tool now refuses effects that arrive without one.
            task.metadata["action_provenance"] = {
                "trigger_type": "USER_COMMAND",
                "trigger_id": task.id,
                "mission_id": task.id,
                "requested_effect": task.user_request[:160],
                "permission_level": task.permission_level.value
                if hasattr(task.permission_level, "value") else str(task.permission_level),
            }
            await self.task_store.save(task)
            await self._check_control(task)
            await self._capture_conversational_facts(task)

            # Phase 16: cognitive runtime — resolve Memory -> Experience ->
            # Knowledge -> Skill -> Tool BEFORE planning, for every
            # meaningful task (live behavior, not a demo helper).
            if self.cognitive_runtime is not None:
                try:
                    await self.cognitive_runtime.prepare(task, profile)
                    await self.task_store.save(task)
                except Exception:
                    import logging

                    logging.getLogger("vyom.cognitive").exception(
                        "cognitive resolution failed for task %s", task.id
                    )  # logged, never blocking execution

                # A PRONOUN THAT NOW HAS A REFERENT IS AN ORDINARY COMMAND.
                #
                # "to open kijiye usko" names no target, so the classifier
                # could only call it "general" and hand it to the planner -
                # which picked an unrelated URL out of durable memory and
                # opened a Zoho workflow. Once ActiveContext has resolved
                # what "usko" points at, this IS a launch, and it takes the
                # deterministic path: zero model calls, real verification.
                referent = (task.metadata.get("cognitive") or {}).get("resolved_reference")
                if (
                    profile.intent == "general"
                    and isinstance(referent, str)
                    and referent.startswith(("http://", "https://"))
                    and self._is_open_command(task.user_request)
                ):
                    profile = profile.model_copy(update={
                        "intent": "app_launch", "domain": TaskDomain.SYSTEM,
                        "deterministic": True, "needs": set(profile.needs) | {"tools"},
                    })
                    task.profile = profile
                    task.domain = profile.domain
                    task.requires_tools = True
                    task.metadata["referent_routed"] = referent
                    await self.task_store.save(task)

            if task.requires_approval and not task.approval_granted:
                approval = ApprovalRequest(
                    task_id=task.id,
                    permission_level=task.permission_level,
                    action=task.user_request,
                    reason=f"{task.permission_level.value} actions require explicit approval",
                )
                task.approval_id = approval.id
                task.metadata["approval"] = approval.model_dump(mode="json")
                task.status = TaskStatus.NEEDS_APPROVAL
                await self.task_store.save(task)
                await self._emit(
                    task,
                    EventType.APPROVAL_REQUIRED,
                    "Approval is required before this task can continue",
                    {"approval": approval.model_dump(mode="json")},
                )
                return

            # Duplicate-execution guard: every consequential (L2/L3) task
            # passes through exactly this one point regardless of which
            # engine ultimately handles it (business/phaseN engine or the
            # generic executor below), after approval is confirmed. Reserve
            # a durable idempotency record keyed by this task's own id
            # before any consequential work happens. This is a second,
            # complementary layer to the crash-recovery ordering fix
            # (which stops a restart from blindly resuming a task that
            # already has evidence) - it also catches a concurrent second
            # run of the same task_id within one Brain lifetime, which
            # self.active only guards in-process and never across a
            # restart. Never re-executes a consequential action twice.
            if (
                task.permission_level in (PermissionLevel.L2, PermissionLevel.L3)
                and self.ownership_registry is not None
            ):
                action_key = f"task_exec:{task.id}"
                reserved = await self.ownership_registry.begin_consequential(task.id, "brain-local", action_key)
                if not reserved:
                    task.status = TaskStatus.PAUSED
                    task.metadata["duplicate_execution_prevented"] = True
                    await self.task_store.save(task)
                    await self._emit(
                        task,
                        EventType.TASK_PROGRESS,
                        "Duplicate consequential execution prevented; task paused for review",
                        {"action_key": action_key},
                    )
                    return

            # Compound goals ("inspect this project, run its tests and tell
            # me what's wrong") are executed by the MissionLoop: plan ->
            # execute step -> verify -> adapt on failure -> learn. Before
            # this, MissionLoop was constructed and attached but never
            # called from the user command path, so multi-step requests
            # collapsed into a single classifier match or a text answer.
            mission_steps = self._detect_mission(task.user_request)
            if mission_steps and self.mission_loop is not None and self.action_engine is not None:
                await self._run_mission(task, profile, mission_steps, started, retries, fallback_used)
                return

            if self.business_engine is not None and self.business_engine.supports(profile.intent):
                task.assigned_model = "workflow:business-v1"
                await self.task_store.save(task)
                await self._emit(
                    task, EventType.MODEL_SELECTED, "Running deterministic business workflow (no model call)",
                    {"routing": {"primary_model": "workflow:business-v1", "primary_provider": "local", "fallback_models": [], "reason_selected": "Structured integration/CRM/automation workflow; no paid model call required", "estimated_cost_tier": "free"}},
                )
                await self._transition(task, TaskStatus.PLANNING, EventType.TASK_PLANNING, "Creating a permission-aware operating plan")
                task.plan = self.planner.create_plan(task, profile)
                await self.task_store.save(task)
                await self._emit(task, EventType.PLAN_READY, f"Operating plan ready with {len(task.plan)} step(s)", {"plan": [step.model_dump(mode="json") for step in task.plan]})
                await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS, "Executing connected business workflow")

                async def emit_business(event_type: str, message: str, payload: dict) -> None:
                    await self._emit(task, EventType(event_type), message, payload)

                result = await self.business_engine.execute(task, profile, emit_business)
                await self._check_control(task)
                for index, step in enumerate(task.plan):
                    step.status = "complete"
                    task.current_step = index
                task.progress = 0.8
                await self.task_store.save(task)
                await self._finish_result(task, result, None, started, retries, fallback_used)
                return

            if self.phase8_engine is not None and self.phase8_engine.supports(profile.intent):
                task.assigned_model = "workflow:research-browser-v1"
                await self.task_store.save(task)
                await self._emit(
                    task, EventType.MODEL_SELECTED, "Running deterministic research workflow (no model call)",
                    {"routing": {"primary_model": "workflow:research-browser-v1", "primary_provider": "local", "fallback_models": [], "reason_selected": "Structured research/browser/discovery/booking/artifact workflow; no paid model call required for orchestration", "estimated_cost_tier": "free"}},
                )
                await self._transition(task, TaskStatus.PLANNING, EventType.TASK_PLANNING, "Creating a bounded research/artifact plan")
                task.plan = self.planner.create_plan(task, profile)
                await self.task_store.save(task)
                await self._emit(task, EventType.PLAN_READY, f"Plan ready with {len(task.plan)} step(s)", {"plan": [step.model_dump(mode="json") for step in task.plan]})
                await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS, "Executing Phase 8 workflow")

                async def emit_phase8(event_type: str, message: str, payload: dict) -> None:
                    await self._emit(task, EventType(event_type), message, payload)

                result = await self.phase8_engine.execute(task, profile, emit_phase8)
                await self._check_control(task)
                for index, step in enumerate(task.plan):
                    step.status = "complete"
                    task.current_step = index
                task.progress = 0.8
                await self.task_store.save(task)
                await self._finish_result(task, result, None, started, retries, fallback_used)
                return

            if self.phase13_engine is not None and self.phase13_engine.supports(profile.intent):
                task.assigned_model = "workflow:diagnostics-v1"
                await self.task_store.save(task)
                await self._emit(
                    task, EventType.MODEL_SELECTED, "Running deterministic diagnostics workflow (no model call)",
                    {"routing": {"primary_model": "workflow:diagnostics-v1", "primary_provider": "local", "fallback_models": [], "reason_selected": "Deterministic diagnostics/observability workflow; no paid model call required", "estimated_cost_tier": "free"}},
                )
                await self._transition(task, TaskStatus.PLANNING, EventType.TASK_PLANNING, "Preparing a production diagnostics plan")
                task.plan = self.planner.create_plan(task, profile)
                await self.task_store.save(task)
                await self._emit(task, EventType.PLAN_READY, f"Plan ready with {len(task.plan)} step(s)", {"plan": [step.model_dump(mode="json") for step in task.plan]})
                await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS, "Running production diagnostics workflow")

                async def emit_phase13(event_type: str, message: str, payload: dict) -> None:
                    await self._emit(task, EventType(event_type), message, payload)

                result = await self.phase13_engine.execute(task, profile, emit_phase13)
                await self._check_control(task)
                for index, step in enumerate(task.plan):
                    step.status = "complete"
                    task.current_step = index
                task.progress = 0.8
                await self.task_store.save(task)
                await self._finish_result(task, result, None, started, retries, fallback_used)
                return

            if self.phase9_engine is not None and self.phase9_engine.supports(profile.intent):
                task.assigned_model = "workflow:desktop-v1"
                await self.task_store.save(task)
                await self._emit(
                    task, EventType.MODEL_SELECTED, "Running deterministic desktop workflow (no model call)",
                    {"routing": {"primary_model": "workflow:desktop-v1", "primary_provider": "local", "fallback_models": [], "reason_selected": "Deterministic native desktop workflow; no paid model call required for orchestration", "estimated_cost_tier": "free"}},
                )
                await self._transition(task, TaskStatus.PLANNING, EventType.TASK_PLANNING, "Creating a bounded desktop action plan")
                task.plan = self.planner.create_plan(task, profile)
                await self.task_store.save(task)
                await self._emit(task, EventType.PLAN_READY, f"Plan ready with {len(task.plan)} step(s)", {"plan": [step.model_dump(mode="json") for step in task.plan]})
                await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS, "Executing native desktop workflow")

                async def emit_phase9(event_type: str, message: str, payload: dict) -> None:
                    await self._emit(task, EventType(event_type), message, payload)

                result = await self.phase9_engine.execute(task, profile, emit_phase9)
                await self._check_control(task)
                for index, step in enumerate(task.plan):
                    step.status = "complete"
                    task.current_step = index
                task.progress = 0.8
                await self.task_store.save(task)
                await self._finish_result(task, result, None, started, retries, fallback_used)
                return

            if self.phase10_engine is not None and self.phase10_engine.supports(profile.intent):
                task.assigned_model = "workflow:finance-v1"
                await self.task_store.save(task)
                await self._emit(
                    task, EventType.MODEL_SELECTED, "Running deterministic finance workflow (no model call)",
                    {"routing": {"primary_model": "workflow:finance-v1", "primary_provider": "local", "fallback_models": [], "reason_selected": "Structured market data/analysis/paper-trading/backtest workflow; no paid model call required for orchestration", "estimated_cost_tier": "free"}},
                )
                await self._transition(task, TaskStatus.PLANNING, EventType.TASK_PLANNING, "Creating a bounded market/trading plan")
                task.plan = self.planner.create_plan(task, profile)
                await self.task_store.save(task)
                await self._emit(task, EventType.PLAN_READY, f"Plan ready with {len(task.plan)} step(s)", {"plan": [step.model_dump(mode="json") for step in task.plan]})
                await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS, "Executing Phase 10 finance/trading workflow")

                async def emit_phase10(event_type: str, message: str, payload: dict) -> None:
                    await self._emit(task, EventType(event_type), message, payload)

                result = await self.phase10_engine.execute(task, profile, emit_phase10)
                await self._check_control(task)
                for index, step in enumerate(task.plan):
                    step.status = "complete"
                    task.current_step = index
                task.progress = 0.8
                await self.task_store.save(task)
                await self._finish_result(task, result, None, started, retries, fallback_used)
                return

            if self.phase11_engine is not None and self.phase11_engine.supports(profile.intent):
                task.assigned_model = "workflow:personal-os-v1"
                await self.task_store.save(task)
                await self._emit(
                    task, EventType.MODEL_SELECTED, "Selected deterministic Phase 11 personal-OS runtime",
                    {"routing": {"primary_model": "workflow:personal-os-v1", "primary_provider": "local", "fallback_models": [], "reason_selected": "Structured goal/habit/routine/chief-of-staff workflow; no paid model call required for orchestration", "estimated_cost_tier": "free"}},
                )
                await self._transition(task, TaskStatus.PLANNING, EventType.TASK_PLANNING, "Creating a bounded personal-OS plan")
                task.plan = self.planner.create_plan(task, profile)
                await self.task_store.save(task)
                await self._emit(task, EventType.PLAN_READY, f"Plan ready with {len(task.plan)} step(s)", {"plan": [step.model_dump(mode="json") for step in task.plan]})
                await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS, "Executing Phase 11 personal-OS workflow")

                async def emit_phase11(event_type: str, message: str, payload: dict) -> None:
                    await self._emit(task, EventType(event_type), message, payload)

                result = await self.phase11_engine.execute(task, profile, emit_phase11)
                await self._check_control(task)
                for index, step in enumerate(task.plan):
                    step.status = "complete"
                    task.current_step = index
                task.progress = 0.8
                await self.task_store.save(task)
                await self._finish_result(task, result, None, started, retries, fallback_used)
                return

            if task.requires_approval and task.approval_granted and not task.requires_tools:
                raise RuntimeError("No registered consequential workflow exists for this approved request")

            if self.intelligence_engine is not None and self.intelligence_engine.supports(profile.intent):
                task.assigned_model = "local-intelligence-v1"
                await self.task_store.save(task)
                await self._emit(
                    task,
                    EventType.MODEL_SELECTED,
                    "Selected deterministic local intelligence runtime",
                    {"routing": {"primary_model": "local-intelligence-v1", "primary_provider": "local", "fallback_models": [], "reason_selected": "Structured memory/skill/agent workflow; no paid model call required", "estimated_cost_tier": "free"}},
                )
                await self._transition(task, TaskStatus.PLANNING, EventType.TASK_PLANNING, "Creating a bounded intelligence plan")
                task.plan = self.planner.create_plan(task, profile)
                await self.task_store.save(task)
                await self._emit(task, EventType.PLAN_READY, f"Intelligence plan ready with {len(task.plan)} step(s)", {"plan": [step.model_dump(mode="json") for step in task.plan]})
                await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS, "Executing persistent intelligence workflow")

                async def emit_intelligence(event_type: str, message: str, payload: dict) -> None:
                    await self._emit(task, EventType(event_type), message, payload)

                result = await self.intelligence_engine.execute(task, profile, emit_intelligence)
                await self._check_control(task)
                for index, step in enumerate(task.plan):
                    step.status = "complete"
                    task.current_step = index
                task.progress = 0.8
                await self.task_store.save(task)
                await self._finish_result(task, result, None, started, retries, fallback_used)
                return

            if profile.intent == "mcp_connect":
                task.plan = self.planner.create_plan(task, profile)
                await self._connect_mcp_from_request(task, started)
                return

            if profile.intent == "learn_skill":
                task.plan = self.planner.create_plan(task, profile)
                await self._learn_skill_from_request(task, started)
                return

            if task.requires_tools:
                # M1 FAVOURITE RECALL: "mujhe X pasand hai" stores the
                # preference; "mera favourite song chala do" plays what was
                # stored instead of searching generic filler words. Maya's
                # demo moment, on VYOM's permanent memory.
                if profile.intent == "play_media":
                    override = await self._media_preference_query(task)
                    if override:
                        task.metadata["media_query_override"] = override
                if self.action_engine is None or not self.action_engine.supports(profile.intent):
                    raise RuntimeError("No registered action workflow can satisfy this tool request")
                task.assigned_model = "local-tool-planner-v1"
                await self.task_store.save(task)
                await self._emit(
                    task,
                    EventType.MODEL_SELECTED,
                    "Selected deterministic local tool planner",
                    {"routing": {"primary_model": "local-tool-planner-v1", "primary_provider": "local", "fallback_models": [], "reason_selected": "Known tool workflow; no paid model call required", "estimated_cost_tier": "free"}},
                )
                await self._transition(task, TaskStatus.PLANNING, EventType.TASK_PLANNING, "Creating a controlled tool plan")
                task.plan = self.planner.create_plan(task, profile)
                await self.task_store.save(task)
                await self._emit(
                    task,
                    EventType.PLAN_READY,
                    f"Tool plan ready with {len(task.plan)} step(s)",
                    {"plan": [step.model_dump(mode="json") for step in task.plan]},
                )
                await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS, "Executing registered tools")

                async def emit_tool(event_type: str, message: str, payload: dict) -> None:
                    await self._emit(task, EventType(event_type), message, payload)

                result = await self.action_engine.execute(task, profile, emit_tool)
                await self._check_control(task)
                for index, step in enumerate(task.plan):
                    step.status = "complete"
                    task.current_step = index
                task.progress = 0.8
                await self.task_store.save(task)
                await self._finish_result(task, result, None, started, retries, fallback_used)
                return

            if profile.intent in {"runtime_introspection", "user_feedback"}:
                task.plan = self.planner.create_plan(task, profile)
                await self._answer_runtime_introspection(
                    task, started, feedback=profile.intent == "user_feedback")
                return

            if profile.intent == "memory_history_recall":
                task.plan = self.planner.create_plan(task, profile)
                await self._answer_from_history(task, started)
                return

            if profile.intent == "schedule_command":
                task.plan = self.planner.create_plan(task, profile)
                await self._schedule_command(task, started)
                return

            if profile.intent in {"profile_recall", "profile_statement"}:
                task.plan = self.planner.create_plan(task, profile)
                await self._answer_from_profile(task, profile, started)
                return

            if profile.intent == "close_everything":
                task.plan = self.planner.create_plan(task, profile)
                await self._execute_and_finish(task, profile, None, None, started, retries, fallback_used)
                return

            # An intent the classifier did not recognise must NOT become a
            # text answer. It goes to the general tool-calling planner,
            # which decides real actions from the live tool registry and
            # observes their results. This is the difference between VYOM
            # advising the user and VYOM doing the work.
            if (
                profile.intent == "general"
                and self.general_planner is not None
                and self.mission_loop is not None
            ):
                from app.runtime.planner import is_conversational
                from app.runtime.task_classifier import looks_like_stt_noise

                # A transcript with no recognisable word in it is not a
                # request. This check comes FIRST because garbage is also
                # 'conversational' by every other test - no verb, short -
                # and 'guerra rua' sailed past the gate into a model call
                # and a confident invented answer about the user's
                # business. Say so plainly, at zero model cost.
                if looks_like_stt_noise(task.user_request):
                    from app.schemas.results import ExecutionResult
                    from app.schemas.routing import UsageRecord

                    task.metadata["stt_noise"] = True
                    task.assigned_model = "gate:stt-noise"
                    await self.task_store.save(task)
                    result = ExecutionResult(
                        response=(
                            "I didn't catch a complete request there - it didn't "
                            "parse into anything I can act on. Could you say it "
                            "again?"
                        ),
                        structured_data={"gate": "stt_noise"},
                        evidence=["utterance contained no recognisable request word"],
                        usage=UsageRecord(total_tokens=0, estimated_cost=0),
                    )
                    await self._finish_result(task, result, None, started, 0, False)
                    return

                # LLM TRIAGE (the soul fix): when both keyword layers
                # declined, one cheap model call decides ACTION vs
                # conversation - the word-count heuristic alone declared
                # "aaj ka kaam sambhalo" small talk and answered it from
                # memory with no tools. Triage only upgrades toward
                # ACTION; on any failure it is skipped entirely.
                triage = None
                if self.llm_triage is not None:
                    triage = await self.llm_triage.classify(task, profile, task.user_request)
                if triage is not None:
                    task.metadata["triage"] = triage
                    if triage.get("tone") not in (None, "neutral"):
                        # Emotion/tone capture: how the user said it is
                        # part of what they said.
                        task.metadata["user_tone"] = triage.get("tone")
                    await self.task_store.save(task)

                # Conversation is not a mission. Routing "good, what about
                # you?" through the planner made VYOM run a system-status
                # call and answer with a CPU card. Pure conversation takes
                # the plain reasoning path: one cheap call, zero tools.
                #
                # When LLM triage ran, it already decided action-vs-answer
                # with the Hinglish meaning in view - trust that over the
                # crude word-count heuristic. A non-actionable turn that
                # was forced into the tool-mission planner came back
                # answered from a raw memory/knowledge lookup: the fact's
                # TITLE ("India - is a") or a stack of "Completed: ..."
                # episodic rows, never an actual answer. Non-actionable ->
                # reasoning path (grounded by knowledge/memory, one call).
                from app.runtime.planner import needs_fresh_evidence

                # A freshness-dependent question ("what's new in n8n",
                # today's price) can never be answered from model memory -
                # it keeps the mission/research path regardless of triage.
                fresh_needed = needs_fresh_evidence(task.user_request)
                run_mission = (
                    (triage is not None and (triage.get("actionable") or fresh_needed))
                    or (triage is None and (fresh_needed or not is_conversational(task.user_request)))
                )
                if run_mission:
                    # A genuinely multi-domain goal ("research X, write it
                    # up and check it for security issues") is split across
                    # role agents - each scoped to only its own tools, so
                    # the work is divided and no sub-agent burns budget
                    # outside its job. A single-domain goal skips this and
                    # takes the cheaper single tool-calling planner.
                    if (
                        self.multi_agent_orchestrator is not None
                        and self.multi_agent_orchestrator.should_orchestrate(task.user_request)
                    ):
                        await self._run_multi_agent_mission(task, profile, started, retries, fallback_used)
                        return
                    await self._run_general_mission(task, profile, started, retries, fallback_used)
                    return

            # REMEMBER BROADLY, RETRIEVE NARROWLY. This block used to
            # attach EVERY profile fact to the prompt of any task that
            # reached the reasoning path - which is why "Sorry. This is
            # the clear first." and "You are not a perfect." were answered
            # with the user's name and business. Memory now enters only
            # with a recorded reason (exact slot / user-referenced /
            # semantically relevant / correction), and the selection is
            # logged so a bad answer is auditable.
            from app.runtime.task_classifier import memory_relevance_reason

            selection_reason = memory_relevance_reason(task.user_request)
            recalled: list[str] = []
            if selection_reason:
                recalled = await self._current_profile()
                for extra in await self._recall_for(task):
                    if extra not in recalled:
                        recalled.append(extra)
            task.metadata["memory_selection"] = {
                "memory_requested_for": task.user_request[:120],
                "selection_reason": selection_reason,
                "memory_records_selected": len(recalled),
            }
            if recalled:
                task.metadata["recalled_memory"] = recalled
                await self._emit(task, EventType.MEMORY_RETRIEVED,
                                 f"Recalled {len(recalled)} stored fact(s)", {"memory": recalled[:3]})
                await self.task_store.save(task)

            routing = await self.model_router.route(task, profile)
            task.routing = routing
            task.assigned_model = routing.primary_model
            task.fallback_models = routing.fallback_models
            self.last_routing = routing
            await self.task_store.save(task)
            await self._emit(
                task,
                EventType.MODEL_SELECTED,
                f"Selected {routing.primary_model}",
                {"routing": routing.model_dump(mode="json")},
            )

            await self._transition(task, TaskStatus.PLANNING, EventType.TASK_PLANNING, "Creating a structured plan")
            task.plan = self.planner.create_plan(task, profile)
            await self.task_store.save(task)
            await self._emit(
                task,
                EventType.PLAN_READY,
                f"Plan ready with {len(task.plan)} step(s)",
                {"plan": [step.model_dump(mode="json") for step in task.plan]},
            )

            models = [routing.primary_model, *routing.fallback_models]
            last_error: Exception | None = None
            for index, model_id in enumerate(models):
                definition = self.model_registry.get(model_id)
                if definition is None:
                    continue
                provider = self.providers.get(definition.provider)
                if provider is None or not provider.configured:
                    continue
                # Skip a target whose circuit is open. Spending a request
                # against a known rate-limited model cannot succeed and
                # only extends the cooldown. The check is per MODEL: free
                # tier quota is metered per model per day, so an exhausted
                # primary must fall through to its sibling rather than
                # taking the whole provider down with it.
                if self.provider_health.rate_limited(definition.provider, model_id):
                    continue
                if index > 0:
                    retries += 1
                    fallback_used = True
                    await self._emit(
                        task,
                        EventType.MODEL_FALLBACK,
                        f"Falling back to {model_id}",
                        {"from": models[index - 1], "to": model_id, "attempt": index + 1},
                    )
                attempt_routing = routing.model_copy(
                    update={"primary_model": model_id, "primary_provider": definition.provider}
                )
                task.assigned_model = model_id
                await self.task_store.save(task)
                try:
                    await self._execute_and_finish(
                        task, profile, provider, attempt_routing, started, retries, fallback_used
                    )
                    self.provider_health.record_success(definition.provider, model_id)
                    return
                except (ProviderError, RuntimeError) as error:
                    last_error = error
                    from app.providers.base import ProviderRateLimitError

                    if isinstance(error, ProviderRateLimitError):
                        # A rate limit is a "stop calling me", not a fault.
                        # Opening the circuit here is what lets the loop
                        # move straight to a DIFFERENT model instead of
                        # hammering the exhausted one.
                        until = self.provider_health.record_rate_limit(
                            definition.provider, model_id,
                            daily_quota=getattr(error, "daily_quota", False),
                        )
                        await self._emit(
                            task, EventType.MODEL_FALLBACK,
                            f"{model_id} has no remaining quota; switching model rather than retrying",
                            {"provider": definition.provider, "model": model_id,
                             "daily_quota": getattr(error, "daily_quota", False),
                             "cooldown_until": until.isoformat()},
                        )
                        # A daily per-model quota is not a fault of the
                        # provider: its other models may be perfectly
                        # usable, so the loop continues to the next one.
                        continue
                    else:
                        self.provider_health.record_failure(definition.provider)
                    if index == len(models) - 1:
                        raise
            if last_error:
                raise last_error
            raise NoModelAvailableError("No routed provider was available at execution time")

        except TaskCancelled:
            task = await self.task_store.get(task_id) or task
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now(timezone.utc)
            await self.task_store.save(task)
            await self._emit(task, EventType.TASK_CANCELLED, "Task cancelled")
        except Exception as error:
            task.status = TaskStatus.FAILED
            task.error = str(error)
            task.completed_at = datetime.now(timezone.utc)
            await self.task_store.save(task)
            if self.intelligence_engine is not None:
                try:
                    async def emit_learning(event_type: str, message: str, payload: dict) -> None:
                        await self._emit(task, EventType(event_type), message, payload)
                    await self.intelligence_engine.learn_failure(task, task.error, emit_learning)
                except Exception:
                    pass
            from .error_messages import humanize_error

            await self._emit(
                task, EventType.TASK_FAILED, "Task failed",
                {"error": humanize_error(task.error), "diagnostic": task.error},
            )

            # SELF-HEALING RETRY. A transient failure (the target existed
            # but was not yet in a usable state - see FailureAnalyzer's
            # retriable=True rules) gets ONE automatic fresh attempt as a
            # new linked task, not a blind loop: the same broken plan
            # re-run identically would just fail identically again, so
            # only failures FailureAnalyzer classifies as genuinely
            # transient are eligible, and RETRY_CHAIN_LIMIT bounds how
            # many times a request can retry itself even across several
            # transient failures in a row.
            await self._maybe_self_heal(task)

    async def _maybe_self_heal(self, failed_task: Task) -> None:
        if self.intelligence_engine is None or self.intelligence_engine.improvement is None:
            return
        analysis = self.intelligence_engine.improvement.failures.analyze(failed_task.error or "")
        if not analysis or not analysis.get("retriable"):
            return
        chain_depth = await self._retry_chain_depth(failed_task)
        if chain_depth >= self.RETRY_CHAIN_LIMIT:
            return
        retry_request = TaskCreate(
            user_request=failed_task.user_request, context_id=failed_task.context_id,
            source=failed_task.source, parent_task_id=failed_task.id,
        )
        retry_task = await self.create_task(retry_request, provenance=ActionProvenance.SELF_HEALING_RETRY)
        await self._emit(
            failed_task, EventType.TASK_RETRIED,
            f"Retrying automatically: {analysis['lesson']}",
            {"retry_task_id": retry_task.id, "reason": analysis["lesson"], "chain_depth": chain_depth + 1},
        )

    async def _retry_chain_depth(self, task: Task) -> int:
        """How many times THIS request has already retried itself,
        walking parent_task_id back through the chain - bounds
        RETRY_CHAIN_LIMIT even across several different transient
        failures in a row, not just one."""
        depth = 0
        current = task
        while current.parent_task_id and depth < self.RETRY_CHAIN_LIMIT + 1:
            parent = await self.task_store.get(current.parent_task_id)
            if parent is None:
                break
            depth += 1
            current = parent
        return depth






    async def _answer_runtime_introspection(
        self, task: Task, started: float, *, feedback: bool = False
    ) -> None:
        """Report what VYOM is ACTUALLY doing, read from the task store.

        This is a fact the runtime holds; routing it to a model produced an
        invented answer ("I was analysing your project files").

        `feedback` marks a complaint rather than a question. The user is
        told what actually happened - the same local facts - led by an
        acknowledgement, instead of a directory listing (which is what
        "You have also many mistake" produced) or a model-composed apology
        that referenced nothing real."""
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord

        active_states = {TaskStatus.QUEUED, TaskStatus.UNDERSTANDING, TaskStatus.PLANNING,
                         TaskStatus.EXECUTING, TaskStatus.VERIFYING, TaskStatus.WAITING}
        try:
            active = [item for item in await self.task_store.list_by_status(active_states)
                      if item.id != task.id]
        except Exception:
            active = []

        now = datetime.now(timezone.utc)

        # Provider health is part of "what is going on" - and it is the
        # answer to "why does this keep failing?". Reading it locally is
        # what stops VYOM from calling a rate-limited model in order to
        # explain that the model is rate limited.
        degraded: list[str] = []
        try:
            for model_key, until in dict(self.provider_health.rate_limited_until).items():
                remaining = max(0, int((until - now).total_seconds()))
                if remaining:
                    degraded.append(f"{model_key} has no quota left for another {remaining}s")
        except Exception:
            pass

        recent_failure = None
        try:
            recent = await self.task_store.list_by_status({TaskStatus.FAILED})
            ordered = sorted(recent, key=lambda item: item.completed_at or item.created_at, reverse=True)
            for item in ordered[:1]:
                recent_failure = f"{item.user_request[:60]} — {str(item.error)[:120]}"
        except Exception:
            pass

        # A retrospective question names the thing that failed (for
        # example, "why didn't you play the song?"). Answer from that
        # task's own status/evidence instead of reporting an unrelated
        # task that merely happens to be active now.
        retrospective = None
        request_lower = task.user_request.lower()
        topic_markers = {
            "media": ("song", "music", "gaana", "gana", "गाना", "संगीत"),
            "browser": ("chrome", "browser", "tab", "क्रोम", "टैब"),
            "app": ("app", "application", "calculator", "notepad"),
        }
        wanted_topic = next(
            (name for name, markers in topic_markers.items()
             if any(marker in request_lower for marker in markers)), None)
        asks_why_not = any(marker in request_lower for marker in (
            "why", "kyu", "kyun", "क्यों", "nahi", "नहीं", "didn't", "did not",
        ))
        if wanted_topic and asks_why_not:
            try:
                recent_tasks = await self.task_store.list(limit=40)
                markers = topic_markers[wanted_topic]
                retrospective = next(
                    (item for item in recent_tasks
                     if item.id != task.id
                     and any(marker in item.user_request.lower() for marker in markers)),
                    None,
                )
            except Exception:
                retrospective = None

        if retrospective is not None:
            goal_check = (retrospective.metadata or {}).get("goal_verification") or {}
            proof = (retrospective.result.structured_data or {}) if retrospective.result else {}
            if retrospective.status == TaskStatus.FAILED:
                reason = retrospective.error or goal_check.get("evidence") or "the action failed"
                summary = (
                    f"The earlier request '{retrospective.user_request[:70]}' failed: "
                    f"{str(reason)[:220]}. It was not completed.")
            elif wanted_topic == "media" and proof.get("playing") is not True:
                summary = (
                    "The earlier song request was incorrectly marked complete without any "
                    "playback evidence. It only observed the browser/windows; it did not prove "
                    "audio was playing. That is a routing and verification failure, not a real "
                    "completion.")
            elif retrospective.status == TaskStatus.CANCELLED:
                summary = (
                    f"The earlier request was cancelled before its effect was verified: "
                    f"'{retrospective.user_request[:80]}'.")
            else:
                summary = (
                    f"The earlier request is {retrospective.status.value}. Its recorded goal "
                    f"check says: {goal_check.get('evidence') or 'no real-world evidence recorded'}.")
            rows = [[retrospective.user_request[:50], retrospective.status.value,
                     str(goal_check.get("status") or "no proof")]]
            active = []

        if retrospective is not None:
            pass
        elif not active:
            if degraded:
                summary = ("Nothing is running. " + "; ".join(degraded[:2])
                           + ". Deterministic PC commands still work normally.")
            elif feedback and recent_failure:
                summary = (f"Understood - I'll take that. The last thing that went "
                           f"wrong was: {recent_failure}. Nothing is running now.")
            elif feedback:
                summary = ("Understood - I'll take that. Nothing is running right now, "
                           "so tell me what to fix and I'll do that one thing.")
            else:
                summary = "Right now I am idle - nothing is running. Ready for the next thing."
            rows = [[item, "rate limited", "-"] for item in degraded]
            if recent_failure:
                rows.append([recent_failure[:50], "last failure", "-"])
        else:
            lines = []
            rows = []
            for item in active[:5]:
                elapsed = int((now - (item.started_at or item.created_at)).total_seconds())
                stage = item.status.value.replace("_", " ")
                # If this task fanned out to role agents, say WHICH agent
                # is on it and at what step - the answer to "kaam kaha
                # pahuncha?" for a multi-agent run.
                detail = ""
                board = self.progress_tracker.get(item.id) if self.progress_tracker is not None else None
                if board is not None and board.agents:
                    detail = " — " + board.describe()
                lines.append(f"{item.user_request[:60]} - {stage}, {elapsed}s elapsed{detail}")
                rows.append([item.user_request[:50], stage, f"{elapsed}s"])
            summary = "I am working on: " + "; ".join(lines)
            if degraded:
                summary += ". " + "; ".join(degraded[:2])

        objects = [{
            "id": "runtime", "type": "comparison-table", "title": "What I am doing",
            "eyebrow": "Live runtime state",
            "headers": ["Goal", "Stage", "Elapsed"],
            "rows": rows or [["nothing running", "idle", "-"]],
            "frame": {"x": 20, "y": 20, "width": 56},
        }]
        composition = {
            "schemaVersion": 1, "id": f"runtime-{task.id[:10]}", "mode": "tool-execution",
            "label": "VYOM / Runtime", "summary": summary[:300],
            "generatedAt": now.astimezone().strftime("%H:%M"),
            "objects": objects,
            "sequence": [{"id": "s0", "label": "Runtime state", "atMs": 120,
                          "state": "Verifying", "objectIds": ["runtime"]}],
        }
        result = ExecutionResult(
            response=summary,
            structured_data={"active": [{"id": i.id, "request": i.user_request,
                                         "status": i.status.value} for i in active[:5]]},
            ui_composition=composition,
            evidence=[f"{len(active)} active task(s) read from the runtime"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )
        await self._finish_result(task, result, None, started, 0, False)

    async def _schedule_command(self, task: Task, started: float) -> None:
        from app.automation.natural_schedule import parse_schedule_request
        from app.automation.schemas import Automation
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord

        if self.automation_store is None:
            raise RuntimeError("The durable automation store is unavailable")
        request = parse_schedule_request(task.user_request)
        # The embedded command's real permission is authoritative; a user
        # cannot lower it by wording the outer schedule as harmless.
        embedded = str((request.condition or {}).get("command", ""))
        request.permission_level = self.permission_engine.classify(embedded).value
        automation = Automation.from_create(request)
        await self.automation_store.save(automation)
        persisted = await self.automation_store.get(automation.id)

        task.assigned_model = "local-scheduler-v1"
        await self.task_store.save(task)
        await self._emit(
            task, EventType.MODEL_SELECTED, "Created a durable schedule locally",
            {"routing": {"primary_model": "local-scheduler-v1", "primary_provider": "local",
                         "fallback_models": [], "estimated_cost_tier": "free",
                         "reason_selected": "Deterministic schedule parsing and SQLite persistence"}},
        )
        await self._emit(
            task, EventType.AUTOMATION_SCHEDULED,
            f"Scheduled {embedded[:100]}",
            {"automation_id": persisted.id, "next_run_at": persisted.next_run_at.isoformat() if persisted.next_run_at else None},
        )
        when = persisted.next_run_at.astimezone().strftime("%d %b %Y, %H:%M") if persisted.next_run_at else "when its condition matches"
        response = f"Scheduled '{embedded}' for {when}."
        result = ExecutionResult(
            response=response,
            structured_data={
                "automation_id": persisted.id,
                "persisted": True,
                "next_run_at": persisted.next_run_at.isoformat() if persisted.next_run_at else None,
                "cron_expression": persisted.cron_expression,
                "permission_level": persisted.permission_level,
            },
            evidence=[f"automation:{persisted.id}:persisted"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )
        await self._finish_result(task, result, None, started, 0, False)

    async def _answer_from_history(self, task: Task, started: float) -> None:
        """Recall what was actually said/stored at a past time, locally.

        Current-truth lookup excludes superseded entries. Historical
        lookup intentionally includes them and labels their state, so a
        correction preserves the audit trail without reviving an old fact
        as present truth.
        """
        from app.memory.history import USER_TIMEZONE, parse_historical_memory_request
        from app.memory.schemas import MemoryQuery
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord
        from app.security.redaction import redact_text

        parsed = parse_historical_memory_request(task.user_request)
        task.assigned_model = "local-history-v1"
        await self.task_store.save(task)
        await self._emit(
            task, EventType.MODEL_SELECTED, "Read VYOM's durable history locally",
            {"routing": {"primary_model": "local-history-v1", "primary_provider": "local",
                         "fallback_models": [], "estimated_cost_tier": "free",
                         "reason_selected": "Dated task and memory lookup; no model call required"}},
        )

        tasks = await self.task_store.search_history(
            created_after=parsed.created_after,
            created_before=parsed.created_before,
            text=parsed.subject,
            exclude_task_id=task.id,
            limit=12,
        )
        memories = []
        if self.memory_retriever is not None:
            try:
                memories = await self.memory_retriever.search(MemoryQuery(
                    text=parsed.subject,
                    created_after=parsed.created_after,
                    created_before=parsed.created_before,
                    include_superseded=True,
                    include_expired=True,
                    limit=12,
                ))
            except Exception:
                import logging

                logging.getLogger("vyom.memory").exception("historical memory lookup failed")

        records: list[dict] = []
        seen_task_ids: set[str] = set()
        for old_task in tasks:
            seen_task_ids.add(old_task.id)
            local_time = old_task.created_at.astimezone(USER_TIMEZONE)
            records.append({
                "kind": "user_statement",
                "id": old_task.id,
                "timestamp": local_time.isoformat(),
                "text": redact_text(old_task.user_request)[:1000],
                "state": "recorded",
            })
        for hit in memories:
            memory = hit.memory
            # A task-result memory tied to a task already shown is its
            # generated outcome, not another thing the user said.
            if memory.task_id and memory.task_id in seen_task_ids:
                continue
            local_time = memory.created_at.astimezone(USER_TIMEZONE)
            records.append({
                "kind": "trusted_memory",
                "id": memory.id,
                "timestamp": local_time.isoformat(),
                "text": redact_text(memory.summary or memory.content)[:1000],
                "title": memory.title,
                "state": memory.verification_state.value,
                "source": memory.source or memory.provenance[0].type.value,
            })
        records.sort(key=lambda item: item["timestamp"], reverse=True)
        records = records[:16]

        date_label = parsed.local_date.strftime("%d %b %Y") if parsed.local_date else "the matching history"
        subject_label = f" about {parsed.subject}" if parsed.subject else ""
        if not records:
            summary = f"I found no stored record for {date_label}{subject_label}."
        else:
            lines = []
            for record in records[:8]:
                stamp = datetime.fromisoformat(record["timestamp"]).strftime("%d %b %Y, %H:%M")
                label = "You said" if record["kind"] == "user_statement" else "Memory"
                state = f" [{record['state']}]" if record["kind"] == "trusted_memory" else ""
                lines.append(f"{stamp} — {label}{state}: {record['text']}")
            summary = (
                f"I found {len(records)} stored record(s) for {date_label}{subject_label}:\n"
                + "\n".join(lines)
            )

        result = ExecutionResult(
            response=summary,
            structured_data={
                "historical_records": records,
                "local_date": parsed.local_date.isoformat() if parsed.local_date else None,
                "subject": parsed.subject,
                "history_includes_superseded": True,
                "current_truth_includes_superseded": False,
            },
            evidence=[f"task:{item.id}" for item in tasks]
                     + [f"memory:{item.memory.id}" for item in memories],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )
        await self._finish_result(task, result, None, started, 0, False)

    async def _connect_mcp_from_request(self, task: Task, started: float) -> None:
        """Chat-native MCP self-service: 'connect to notion mcp' resolves
        against VYOM's own curated catalog (app/mcp/catalog.py) using the
        exact fuzzy-match logic POST /api/mcp/connect already applies -
        one lookup path, reached from either the API or plain language,
        never a second implementation that could drift from it."""
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord

        task.assigned_model = "local-mcp-connect-v1"
        await self.task_store.save(task)
        await self._emit(
            task, EventType.MODEL_SELECTED, "Matching against VYOM's reviewed MCP catalog locally",
            {"routing": {"primary_model": "local-mcp-connect-v1", "primary_provider": "local",
                         "fallback_models": [], "estimated_cost_tier": "free",
                         "reason_selected": "Catalog lookup; no model call required"}},
        )

        import re as _re
        match = _re.search(
            r"\b(?:connect(?:\s+(?:to|with))?|add)\s+(?:the\s+)?(.+?)\s+mcp(?:\s+server)?\b",
            task.user_request.strip().lower(),
        )
        service_name = match.group(1).strip() if match else task.user_request

        if self.mcp_connector is None:
            result = ExecutionResult(
                response="MCP connection support is not attached to this Brain instance.",
                usage=UsageRecord(total_tokens=0, estimated_cost=0),
            )
        else:
            outcome = await self.mcp_connector(service_name)
            status = outcome.get("status")
            if status == "connected":
                response = f"Connected to {outcome.get('name', service_name)} — {outcome.get('tool_count', 0)} tools now available."
            elif status == "unknown_service":
                response = outcome.get("detail", f"'{service_name}' is not in VYOM's reviewed MCP catalog yet.")
            else:
                response = outcome.get("detail", f"Could not connect to '{service_name}': {status}")
            result = ExecutionResult(
                response=response, structured_data=outcome,
                evidence=[f"mcp_connect:{service_name}:{status}"],
                usage=UsageRecord(total_tokens=0, estimated_cost=0),
            )
        await self._finish_result(task, result, None, started, 0, False)

    async def _learn_skill_from_request(self, task: Task, started: float) -> None:
        """Chat-native skill authoring: 'learn how to X: 1. ... 2. ...'
        resolves through the SAME LearnService.from_description path
        POST /api/learn/from-description already uses - always
        TESTING-status, never auto-activated (see app/skills/learn.py's
        safety rationale)."""
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord

        task.assigned_model = "local-learn-skill-v1"
        await self.task_store.save(task)
        await self._emit(
            task, EventType.MODEL_SELECTED, "Parsing the described workflow locally",
            {"routing": {"primary_model": "local-learn-skill-v1", "primary_provider": "local",
                         "fallback_models": [], "estimated_cost_tier": "free",
                         "reason_selected": "Deterministic step parsing; no model call required"}},
        )

        if self.learn_service is None:
            result = ExecutionResult(
                response="Skill-learning support is not attached to this Brain instance.",
                usage=UsageRecord(total_tokens=0, estimated_cost=0),
            )
        else:
            import re as _re

            body = task.user_request
            header_match = _re.search(r"\blearn\s+(?:how\s+to|to\s+do|this\s+workflow|the\s+following)\b\s*:?\s*", body, _re.I)
            description = body[header_match.end():].strip() if header_match else body
            name = (description.split("\n")[0] or "Learned skill")[:80]
            slug = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "learned-skill"
            skill_id = f"learned-{slug}"
            try:
                skill = self.learn_service.from_description(description, skill_id=skill_id, name=name)
                response = (
                    f"Learned a new skill: '{skill.name}' ({len(skill.steps)} steps, id={skill.id}). "
                    "It is TESTING-status and will not run automatically until reviewed and activated."
                )
                result = ExecutionResult(
                    response=response, structured_data={"skill_id": skill.id, "status": skill.status.value, "steps": len(skill.steps)},
                    evidence=[f"skill_learned:{skill.id}"],
                    usage=UsageRecord(total_tokens=0, estimated_cost=0),
                )
            except ValueError as error:
                result = ExecutionResult(
                    response=f"Could not learn a skill from that description: {error}",
                    usage=UsageRecord(total_tokens=0, estimated_cost=0),
                )
        await self._finish_result(task, result, None, started, 0, False)


    async def _answer_from_profile(self, task: Task, profile, started: float) -> None:
        """Answer from VYOM's OWN store, with zero model calls.

        "Mera naam kya hai?" is an indexed lookup, not a reasoning problem.
        Routing it to a model cost a paid call for a fact VYOM already
        held - and when the provider was rate limited, VYOM could not
        answer a question whose answer was sitting in its database. An
        empty store is a real answer ("I have not been told"), never a
        reason to guess."""
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord

        task.assigned_model = "local-memory-v1"
        await self.task_store.save(task)
        await self._emit(
            task, EventType.MODEL_SELECTED, "Answered from VYOM's own memory",
            {"routing": {"primary_model": "local-memory-v1", "primary_provider": "local",
                         "fallback_models": [], "estimated_cost_tier": "free",
                         "reason_selected": "Exact lookup in VYOM's own store; no model call required"}},
        )

        facts = await self._current_profile()
        if profile.intent == "profile_statement":
            # The write already happened in _capture_conversational_facts,
            # before any routing decision. This only reports it.
            stored = task.metadata.get("stored_facts") or []
            summary = (
                "Noted: " + "; ".join(stored)
                if stored else
                "I heard that, but nothing in it was a durable fact I should store."
            )
        elif not facts:
            summary = "I have not been told anything about you yet."
        else:
            lowered = task.user_request.lower()
            wanted = None
            # The SUBJECT is checked before the generic word for "name":
            # "mere business ka naam kya hai?" contains "naam", and
            # matching on that first answered a question about the
            # business with the user's own name.
            if "business" in lowered or "company" in lowered or "बिजनेस" in lowered:
                wanted = "User business"
            elif "website" in lowered or "site" in lowered:
                wanted = "User website"
            elif "naam" in lowered or "nam " in lowered or "name" in lowered or "नाम" in lowered:
                wanted = "User name"
            match = next((fact for fact in facts if wanted and fact.startswith(wanted)), None)
            if match:
                summary = match.split(":", 1)[1].strip()
                summary = f"{wanted.replace('User ', 'Your ')} is {summary}."
            elif wanted:
                summary = f"I have not been told your {wanted.replace('User ', '').lower()}."
            else:
                summary = "Here is what I have on record: " + "; ".join(facts)

        objects = [{
            "id": "profile", "type": "verified-result", "title": "From memory",
            "eyebrow": "VYOM's own store · no model call", "tone": "verified",
            "statement": summary,
            "evidence": facts or ["nothing stored yet"],
            "timestamp": datetime.now().astimezone().strftime("%H:%M"),
            "frame": {"x": 28, "y": 26, "width": 40},
        }]
        result = ExecutionResult(
            response=summary,
            structured_data={"profile": facts},
            ui_composition={
                "schemaVersion": 1, "id": f"profile-{task.id[:10]}", "mode": "brain-context",
                "label": "VYOM / Memory", "summary": summary[:300],
                "generatedAt": datetime.now().astimezone().strftime("%H:%M"),
                "objects": objects,
                "sequence": [{"id": "s0", "label": "Memory lookup", "atMs": 120,
                              "state": "Verifying", "objectIds": ["profile"]}],
            },
            evidence=facts or ["no stored facts"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )
        await self._finish_result(task, result, None, started, 0, False)

    async def _recall_for(self, task: Task) -> list[str]:
        """Retrieve stored facts relevant to this request.

        Runs before the reasoning path so a question like "what is my
        name?" is answered from VYOM's own memory instead of a refusal."""
        if self.memory_retriever is None:
            return []
        from app.memory.schemas import MemoryQuery

        from app.memory.schemas import MemoryType

        recalled: list[str] = []
        seen: set[str] = set()

        async def collect(query: MemoryQuery) -> None:
            try:
                hits = await self.memory_retriever.search(query)
            except Exception:
                return
            for hit in hits:
                summary = (hit.memory.summary or hit.memory.content or "").strip()
                if summary and summary not in seen:
                    seen.add(summary)
                    recalled.append(summary[:200])

        # Recall is restricted to DURABLE FACT types - PERSON/CLIENT/
        # PREFERENCE/SEMANTIC/DECISION - never EPISODIC or WORKING memory.
        # An unfiltered query previously pulled in past task summaries,
        # which include the model's OWN prior answers. A wrong answer
        # ("your business is Alphacorp Widgets") had been consolidated
        # into an episodic record, and the next question recalled that
        # record as if it were a verified fact - a self-reinforcing
        # hallucination loop where one mistake became permanent "memory".
        # Only what extract_durable_facts / a verified task explicitly
        # wrote as a fact-type entry counts as something VYOM "knows".
        durable_types = [MemoryType.PERSON, MemoryType.CLIENT, MemoryType.PREFERENCE,
                         MemoryType.SEMANTIC, MemoryType.DECISION]

        # The user's core profile is ALWAYS in context, independent of the
        # query's wording or language. Similarity search alone failed
        # "What is my name?" because the stored fact was written in Hindi;
        # these few facts are small enough to carry every time.
        await collect(MemoryQuery(text="", types=durable_types, limit=12))
        await collect(MemoryQuery(text=task.user_request, types=durable_types, limit=6))
        return recalled[:10]

    async def _current_profile(self) -> list[str]:
        """The user's profile as ONE current value per fact.

        A profile slot ("User business") holds exactly one truth at a
        time. Recall previously returned every non-superseded entry, so a
        business fact and a website fact - both stored as CLIENT - arrived
        together and the model reported them as two separate businesses
        the user owned. Newest entry per title wins; everything older is
        history, not context."""
        if self.memory_retriever is None:
            return []
        from app.memory.schemas import MemoryQuery, MemoryType

        durable_types = [MemoryType.PERSON, MemoryType.CLIENT, MemoryType.PREFERENCE]
        try:
            hits = await self.memory_retriever.search(
                MemoryQuery(text="", types=durable_types, limit=40))
        except Exception:
            return []
        latest: dict[str, object] = {}
        for hit in hits:
            title = hit.memory.title
            current = latest.get(title)
            if current is None or hit.memory.created_at > current.created_at:  # type: ignore[union-attr]
                latest[title] = hit.memory
        return [
            f"{memory.title}: {(memory.summary or memory.content).split(':', 1)[-1].strip()}"
            for memory in sorted(latest.values(), key=lambda item: item.created_at)  # type: ignore[attr-defined]
        ]

    #: "mujhe <X> gaana/song pasand hai" — X BEFORE the keyword.
    _MUSIC_PREF_BEFORE = re.compile(
        r"(?:mujhe|mera|meri|main|hum)\s+(.{2,70}?)\s+(?:gaana|gana|song|music|artist)"
        r"\s+(?:pasand|favourite|favorite)", re.I)
    #: "favourite song <X> (hai/set karo)" — X AFTER the keyword.
    _MUSIC_PREF_AFTER = re.compile(
        r"(?:favourite|favorite|pasandida)\s+(?:song|gaana|gana|music|artist)\s+"
        r"(?:hai\s*)?(?:set\s*)?(?:karo\s*)?(.{2,70}?)(?:\s+(?:hai|set|karo|batao))?\s*[.!?।]*$", re.I)
    #: Recall only when the utterance asks to PLAY, not when merely stating.
    _MEDIA_PLAY_VERB = re.compile(
        r"chalao|chala|bajao|baja|lagao|laga|play|sunao|sunana|lagwa", re.I)

    async def _media_preference_query(self, task: Task) -> str | None:
        """Store or recall the Boss's favourite music for play_media.

        Returns the YouTube search query to use, or None (normal flow)."""
        text = (task.user_request or "").strip()
        if not text:
            return None
        from app.memory.schemas import MemoryEntry, MemoryProvenance, MemoryQuery, MemoryType

        for pattern in (self._MUSIC_PREF_BEFORE, self._MUSIC_PREF_AFTER):
            match = pattern.search(text)
            if match and self.memory_store is not None:
                favourite = match.group(1).strip(" .,!?:;।\"'")
                # "favourite song chala do" is a PLAY request, not a stored
                # name - never save command words as the favourite itself.
                if not favourite or self._MEDIA_PLAY_VERB.match(favourite) or re.match(
                        r"^(?:hai|karo|kar|do|set|batao)\b", favourite, re.I):
                    continue
                await self.memory_manager.remember(MemoryEntry(
                    type=MemoryType.PREFERENCE,
                    title=f"Boss ka favourite music: {favourite}",
                    content=favourite,
                    summary=f"Favourite song/artist: {favourite}",
                    entities=["music"],
                    provenance=[MemoryProvenance(type="user_statement", reference="voice")],
                ))
                task.metadata["preference_saved"] = favourite
                return None  # statement saved; playing happens on command

        if self._MEDIA_PLAY_VERB.search(text) and self.memory_retriever is not None:
            results = await self.memory_retriever.search(MemoryQuery(
                types={MemoryType.PREFERENCE}, text="favourite favorite pasand song gaana music artist", limit=5))
            for result in results:
                memory = result.memory
                if re.search(r"gaana|gana|song|music|artist|favourite|favorite",
                             f"{memory.title} {memory.content}", re.I):
                    query = memory.content.strip()
                    if memory.title == "Boss favourite music" and ":" in query:
                        query = query.split(":", 1)[1].strip()
                    task.metadata["preference_recalled"] = query
                    if getattr(self, "event_bus", None) is not None:
                        await self._emit(task, EventType.MEMORY_RETRIEVED,
                                         "Boss ka favourite yaad rakha hai — wahi chala raha hoon",
                                         {"memory_id": memory.id})
                    return query
        return None

    async def _capture_conversational_facts(self, task: Task) -> list[str]:
        """Write durable facts the user STATED into memory.

        Nothing said in conversation was ever persisted, so VYOM forgot the
        user's name 75 seconds after being told it. Extraction is
        deterministic - no model call - and only fires on statements, never
        on questions or commands."""
        if self.memory_store is None:
            return []
        from app.memory.consolidation import extract_durable_facts
        from app.memory.schemas import MemoryEntry, MemoryProvenance, MemoryQuery, MemoryType

        facts = extract_durable_facts(task.user_request)
        if not facts:
            return []
        kind_to_type = {
            "identity": MemoryType.PERSON,
            "business": MemoryType.CLIENT,
            "preference": MemoryType.PREFERENCE,
        }
        stored: list[str] = []
        for fact in facts:
            entry = MemoryEntry(
                type=kind_to_type.get(fact["kind"], MemoryType.SEMANTIC),
                title=fact["title"],
                content=f"{fact['title']}: {fact['value']}",
                summary=f"{fact['title']}: {fact['value']}",
                entities=[fact["value"]],
                tags=["conversation", fact["kind"]],
                source="user_statement",
                provenance=[MemoryProvenance(type="user_statement", reference=fact["said"][:200],
                                             task_id=task.id)],
                importance=0.9,
                confidence=0.95,
            )
            try:
                # A correction must SUPERSEDE the prior fact of the same
                # title, not sit beside it. Without this, "wrong X, Y hai"
                # added a new record while the old, contradicting one
                # stayed equally weighted - later recall could still
                # surface the wrong value, or the model could claim an
                # update happened when nothing was actually replaced.
                prior_id = None
                # A profile slot holds ONE current value. Stating a new
                # name, business or website replaces the previous one
                # whether or not the user framed it as a correction -
                # "my business is Beta" after "my business is Alpha" is a
                # change of fact, not a second business. Without this,
                # both stayed live and equally weighted, and recall
                # reported them as two businesses the user owned.
                if self.memory_manager is not None and self.memory_retriever is not None:
                    try:
                        existing = await self.memory_retriever.search(
                            MemoryQuery(text="", types=[entry.type], limit=40))
                    except Exception:
                        existing = []
                    same_slot = [
                        hit.memory for hit in existing
                        if hit.memory.title == fact["title"]
                        and (hit.memory.summary or "") != entry.summary
                    ]
                    if same_slot:
                        prior_id = max(same_slot, key=lambda item: item.created_at).id
                if fact.get("correction") and self.memory_manager is not None and prior_id is None:
                    # Match by KIND, not exact title: "wrong X, Y hai"
                    # corrected a prior "User business" fact with a "User
                    # website" fact - same real-world thing (the user's
                    # business identity), different extractor title. An
                    # exact-title match missed this and the wrong fact
                    # stayed live alongside the new one, so recall later
                    # reported BOTH as if the user had two businesses.
                    # An EMPTY text query returns every entry of this type
                    # unfiltered. Querying by the NEW value instead ("wrong
                    # alphacorp, betaworks.space hai" -> query "betaworks.
                    # space") found nothing, because the retriever drops
                    # zero-keyword-overlap results - the OLD wrong entry
                    # ("Alphacorp Widgets") shares no token with the new
                    # value, so it never appeared as a supersession
                    # candidate and both facts ended up live together.
                    hits = await self.memory_retriever.search(
                        MemoryQuery(text="", types=[entry.type], limit=20))
                    exact = next((hit.memory.id for hit in hits if hit.memory.title == fact["title"]), None)
                    same_kind_hits = sorted(
                        (hit for hit in hits if fact["kind"] in hit.memory.tags),
                        key=lambda hit: hit.memory.created_at, reverse=True,
                    )
                    same_kind = same_kind_hits[0].memory.id if same_kind_hits else None
                    prior_id = exact or same_kind
                if prior_id and self.memory_manager is not None:
                    await self.memory_manager.correct(prior_id, entry)
                else:
                    await self.memory_store.save(entry)
                stored.append(f"{fact['title']}: {fact['value']}")
            except Exception:
                import logging

                logging.getLogger("vyom.memory").exception("failed to store conversational fact")
        if stored:
            # Recorded on the task so the deterministic acknowledgement can
            # report what was ACTUALLY written, rather than a model
            # composing a claim that a save happened.
            task.metadata["stored_facts"] = stored
            await self.task_store.save(task)
            await self._emit(task, EventType.MEMORY_CREATED,
                             f"Remembered: {'; '.join(stored)[:120]}", {"facts": stored})
        return stored

    @staticmethod
    def _postcondition_for(call_name: str, inputs: dict, output) -> tuple[str | None, dict]:
        """Map a completed capability call to the real-world check that
        proves it actually did what was asked."""
        if call_name == "desktop_launch":
            return "app_launch", {"app_id": inputs.get("app_id", "")}
        if call_name == "desktop_close":
            return "app_close", {"app_id": inputs.get("app_id", "")}
        if call_name == "browser_open_profile":
            data = output if isinstance(output, dict) else {}
            profile = data.get("profile") or {"directory": "", "name": inputs.get("profile", "")}
            return "profile_open", {"profile": profile,
                                    "window": data.get("window_title") or "chrome"}
        if call_name == "browser_close_tab":
            data = output if isinstance(output, dict) else {}
            return "tab_closed", {
                "page": inputs.get("target", ""),
                "remaining": data.get("remaining"),
                "tabs_before": data.get("tabs_before"),
                "tabs_after": data.get("tabs_after"),
                "browser_still_running": data.get("browser_still_running"),
            }
        if call_name == "terminal_execute":
            exit_code = (output or {}).get("exit_code") if isinstance(output, dict) else None
            return "command", {"exit_code": exit_code}
        if call_name in {"filesystem_write", "filesystem_create"}:
            return "file_write", {"path": inputs.get("path", ""), "expect_content": True}
        if call_name == "browser_read":
            text = (output or {}).get("text", "") if isinstance(output, dict) else ""
            return "research", {"sources": [], "characters": len(text)}
        if call_name in {"desktop_status", "system_processes"}:
            return "system_query", {"measurement": output}
        return None, {}

    # -- general-knowledge memory/reasoning helpers --------------------------

    @staticmethod
    def _is_general_knowledge_query(text: str) -> bool:
        """True when the utterance asks about an EXTERNAL-world subject
        ('what is X', 'who is X', 'define X', 'find out about X and remember
        it') that only the knowledge base can answer, as opposed to a question
        about VYOM's own stored memory ('what do you remember about my client').
        Only the former should trigger a live research call; the latter is
        satisfied by raw memory recall."""
        from app.runtime.task_classifier import is_general_knowledge_query

        return is_general_knowledge_query(text)

    @staticmethod
    def _normalize_knowledge_subject(query: str) -> str:
        """Strip the question framing off a general-knowledge query so the
        knowledge base is queried/researched on the REAL topic, not the whole
        sentence the planner happened to hand over.

        'What is Python programming language?' -> 'Python programming language'
        'find out about the solar system and remember it' -> 'the solar system'
        'Who is Guido van Rossum?' -> 'Guido van Rossum'
        """
        leadings = (
            "what is ", "what's ", "what are ", "what was ", "who is ", "who was ",
            "what does ", "define ", "definition of ", "explain ", "tell me about ",
            "find out about ", "learn about ", "meaning of ",
        )
        trailings = ("and remember it", "in detail", "please")
        s = (query or "").strip().strip("?.!").strip()
        low = s.lower()
        for lead in leadings:
            if low.startswith(lead):
                s = s[len(lead):].strip()
                low = low[len(lead):].strip()
                break
        for trail in trailings:
            if low.endswith(trail):
                s = s[: -len(trail)].strip()
                low = low[: -len(trail)].strip()
        # Hinglish/Devanagari "kya hai / kaun hai" style: "python kya hai" -> "python".
        for marker in (" kya hai", " kya hota hai", " kaun hai", " kaun tha", " क्या है", " कौन है"):
            idx = low.find(marker)
            if idx > 0:
                s = s[:idx].strip()
                break
        return s or (query or "").strip()

    def _knowledge_research_fn(self, subject: str):
        """Build the async callable that ask_or_research() invokes when the
        knowledge base does not already know `subject` (or knows it stale):
        run the REAL research pipeline (DeepResearchTask over the live browser
        + Defuddle reads), which records what it learns into the same
        knowledge base, then signal that a re-recall is warranted.

        ask_or_research() only uses the return value as a 'did research run'
        flag and re-recalls to surface the newly recorded facts - so even a
        research run that pulled no new claims still returns a truthy marker
        here, and a run that could not happen (no pipeline wired, or the
        research errored) returns False to preserve whatever recall already had.
        """
        async def _research() -> bool:
            research_task = getattr(self.phase8_engine, "research_task", None)
            if research_task is None:
                return False  # no research pipeline; keep what recall already had
            try:
                from app.research.schemas import ResearchDepth
                result = await research_task.run(subject, depth=ResearchDepth.STANDARD)
                return result is not None
            except Exception:
                return False

        return _research

    async def _answer_memory_query(self, call_name: str, query: str, collected: list,
                                   general_knowledge: bool | None = None) -> dict:
        """The memory_search tool body shared by the general mission.

        Knowledge-base-first-then-research for general-knowledge questions
        ('what is X', 'find out about X and remember it'): recall what VYOM
        already knows, and when a world subject is unknown or stale, run the
        real research pipeline (which records the facts) instead of falling
        through to raw memory. Internal-memory questions ('what do you
        remember about my client') are answered by raw memory recall only -
        a research call is never made for them.

        `general_knowledge` is normally derived from the ORIGINAL task request
        (not just the subject the planner extracted, which often drops the
        'what is / find out about' framing - e.g. query='solar system'). Callers
        that already know pass it in; omitting it falls back to checking the
        query text itself."""
        if general_knowledge is None:
            general_knowledge = self._is_general_knowledge_query(query)

        def _found_from_facts(facts) -> list[dict]:
            # The rendered answer is the fact SENTENCE, never the
            # "{subject} - {predicate}" label. That label leaked out as a
            # user answer once ("India - is a") because the observation
            # humaniser reads `title` first; the sentence carries the
            # actual information, so it is the title here and the label is
            # kept separately for callers that want it.
            return [{
                "title": fact.as_sentence(),
                "label": f"{fact.subject} — {fact.predicate}",
                "summary": fact.as_sentence(),
                "source_url": fact.source_url,
                "confidence": fact.confidence,
                "created_at": str(fact.last_confirmed_at),
                "knowledge": True,
            } for fact in facts]

        if self.knowledge_service is not None:
            try:
                if general_knowledge:
                    # Ask the KB first; when unknown or stale, research + record.
                    # Use a normalized subject so 'What is X' researches 'X', not
                    # the whole sentence the planner handed over.
                    subject = self._normalize_knowledge_subject(query)
                    knowledge = await self.knowledge_service.ask_or_research(
                        subject, self._knowledge_research_fn(subject))
                else:
                    subject = query
                    knowledge = await self.knowledge_service.recall(subject)
            except Exception as error:
                knowledge = None
                self.knowledge_recall_error = str(error)[:300]
            if knowledge is not None and knowledge.facts:
                found = _found_from_facts(knowledge.facts)
                collected.append({"call": call_name, "inputs": {"query": query},
                                  "ok": True, "output": found, "error": None})
                return {"ok": True, "output": found,
                        "stale": knowledge.stale,
                        "note": "answered from VYOM's knowledge base" if not knowledge.stale
                                else "facts known but stale; a refresh is recommended"}
            # A world-knowledge question with nothing stored AND no research
            # result. Raw memory stores nothing about the world and would answer
            # "no stored memory" - never fall through to it for a GK query.
            if general_knowledge:
                collected.append({"call": call_name, "inputs": {"query": query},
                                  "ok": True, "output": [], "error": None})
                return {"ok": True, "output":
                        f"VYOM could not find reliable information about '{query}'. No "
                        "knowledge is stored and research was unavailable or came back empty. "
                        "Say so plainly; do not guess."}

        if self.memory_retriever is None:
            return {"ok": False, "error": "memory retrieval is not available in this runtime"}
        from app.memory.schemas import MemoryQuery

        try:
            hits = await self.memory_retriever.search(MemoryQuery(text=query, limit=8))
        except Exception as error:
            return {"ok": False, "error": f"memory search failed: {error}"[:300]}
        # "Completed: <goal>" rows are operational sediment - a log that a
        # task ran, not knowledge. They were being stitched into answers
        # ("Completed: ...; Completed: ...") because they match on shared
        # words. They never answer a user question, so they are dropped
        # from what a memory lookup reports.
        hits = [
            hit for hit in hits
            if not (hit.memory.title or "").strip().lower().startswith("completed:")
        ]
        found = [{
            "title": hit.memory.title,
            "summary": hit.memory.summary or hit.memory.content[:300],
            "created_at": str(hit.memory.created_at),
            "confidence": hit.memory.confidence,
        } for hit in hits]
        collected.append({"call": call_name, "inputs": {"query": query},
                          "ok": True, "output": found, "error": None})
        if not found:
            return {"ok": True, "output":
                    f"VYOM has no stored memory matching '{query}'. Nothing has been "
                    "recorded about this. Say so plainly; do not guess."}
        return {"ok": True, "output": found}

    # -- general tool-calling mission --------------------------------------

    async def _run_general_mission(
        self, task: Task, profile, started: float, retries: int, fallback_used: bool
    ) -> None:
        """Execute an unrecognised goal by letting the planner choose real
        tools, observe their results, and iterate until the goal is met.

        Every action runs through the SAME registered tool layer and the
        same permission engine as a deterministic intent - the planner
        chooses what to do, it does not gain new powers."""
        from app.runtime.planner import TOOL_CONTRACTS, needs_fresh_evidence
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord

        task.assigned_model = "vyom-general-planner"
        await self.task_store.save(task)
        await self._emit(
            task, EventType.MODEL_SELECTED, "Selected the general tool-calling planner",
            {"routing": {"primary_model": "vyom-general-planner", "primary_provider": "local",
                         "fallback_models": [], "estimated_cost_tier": "low",
                         "reason_selected": "Goal has no deterministic route; planning over live capabilities"}},
        )
        await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS,
                               "Choosing capabilities for this goal")

        async def emit_tool(event_type: str, message: str, payload: dict) -> None:
            await self._emit(task, EventType(event_type), message, payload)

        context = self.action_engine.context_factory.create(task.id, task.permission_level, emit_tool, visibility=getattr(task.profile, "visibility", None))
        collected: list[dict] = []

        async def execute_call(call) -> dict:
            contract = TOOL_CONTRACTS.get(call.name)
            if contract is None:
                return {"ok": False, "error": f"'{call.name}' is not a registered capability"}
            # VYOM's own memory is not a Tool Registry tool; it is answered
            # from the existing MemoryRetriever. An empty result is a REAL
            # answer ("nothing is stored"), never grounds for guessing.
            if contract["tool"] == "__memory__":
                query = str(call.arguments.get("query", "")).strip()
                # VYOM's own memory is not a Tool Registry tool; it is answered
                # by the knowledge base first. A general-knowledge question
                # ('what is X', 'find out about X and remember it') recalls what
                # the KB already knows and, when a world subject is unknown or
                # stale, performs real research and records the facts; an
                # internal-memory question ('what do you remember about my
                # client') is answered by raw memory recall only. The GK decision
                # comes from the ORIGINAL task request, because the planner
                # often hands over just the subject (e.g. 'solar system') with
                # the 'what is / find out' framing dropped.
                general_knowledge = (
                    self._is_general_knowledge_query(task.user_request)
                    or self._is_general_knowledge_query(query)
                )
                return await self._answer_memory_query(
                    call.name, query, collected, general_knowledge=general_knowledge)
            inputs = {**contract.get("fixed", {}), **dict(call.arguments)}
            # Sensible, safe defaults so a partially specified call still
            # targets the user's own project rather than failing.
            if contract["tool"] == "filesystem" and not inputs.get("path"):
                inputs["path"] = str(self.action_engine.project_root)
            if contract["tool"] == "terminal":
                inputs.setdefault("cwd", str(self.action_engine.project_root))
                inputs.setdefault("timeout", 180)
            if contract["tool"] == "git":
                inputs.setdefault("cwd", str(self.action_engine.project_root))
            try:
                result = await self.action_engine.executor.invoke(contract["tool"], inputs, context)
            except Exception as error:
                return {"ok": False, "error": str(error)[:400]}
            payload = result.structured_output if result.success else None
            # POSTCONDITION. A tool reporting success is not proof the
            # requested effect happened - a mission that "launched" an app
            # which never appeared was still reported COMPLETE. The check
            # reads real state, and its verdict is fed back to the planner
            # so it can adapt rather than assume.
            if result.success:
                kind, check_context = self._postcondition_for(call.name, inputs, payload)
                if kind:
                    satisfied, detail = self.postconditions.check(kind=kind, context=check_context)
                    if not satisfied:
                        collected.append({"call": call.name, "inputs": inputs, "ok": False,
                                          "output": payload, "error": f"postcondition failed: {detail}"})
                        await emit_tool(
                            "verification_failed",
                            f"{call.name} reported success but the effect was not observed: {detail}",
                            {"tool": call.name, "postcondition": kind},
                        )
                        return {"ok": False, "error":
                                f"The tool reported success but the effect was not observed: {detail}"}
                    await emit_tool("verification_evidence", f"{call.name} verified: {detail}",
                                    {"tool": call.name, "postcondition": kind})
            collected.append({"call": call.name, "inputs": inputs, "ok": result.success,
                              "output": payload, "error": result.error})
            if not result.success:
                return {"ok": False, "error": result.error or "the tool reported failure"}
            return {"ok": True, "output": payload}

        try:
            mission = await self.mission_loop.run_adaptive(
                task.user_request,
                planner=self.general_planner,
                execute_call=execute_call,
                # PROSE IS NEVER THE FINAL ANSWER. When this was left off
                # for "simple" goals, a garbled transcript ("guerra rua")
                # was answered with a confident, entirely invented business
                # pitch from memory - no tool had run, nothing was real.
                # Pure conversation never reaches this path (it is filtered
                # before _run_general_mission), so every goal here must
                # ground itself in at least one real observation.
                require_tool_use=True,
                mission_id=task.id,
            )
        finally:
            self.action_engine.context_factory.release(task.id)

        await self._check_control(task)
        verified = sum(1 for step in mission.completed if step.verified)
        final_text = getattr(mission, "final_text", "") or ""
        # GOAL-level completion. A mission is not complete because some
        # tools succeeded - the planner must have produced an actual
        # answer. Counting verified tool calls is telemetry, not proof.
        summary = final_text.strip()
        if not summary:
            summary = ("I carried out the steps but produced no result to report."
                       if mission.status == "completed"
                       else "I could not complete that request.")
            if mission.status == "completed":
                mission.status = "failed"  # no answer means the goal was not met

        objects: list[dict] = [{
            "id": "mission", "type": "task-mission", "title": "Autonomous mission",
            "eyebrow": "General planner", "tone": "intelligence",
            "mission": task.user_request[:120],
            "status": "complete" if mission.status == "completed" else "failed",
            "details": [step.title[:70] for step in mission.completed][:6],
            "frame": {"x": 2, "y": 4, "width": 31},
        }]
        for index, item in enumerate(collected[:4]):
            objects.append({
                "id": f"obs-{index}", "type": "terminal-output",
                "title": item["call"], "eyebrow": "Real tool result",
                "command": ", ".join(f"{k}={str(v)[:50]}" for k, v in item["inputs"].items())[:160],
                "exitCode": 0 if item["ok"] else 1,
                "output": str(item["output"] if item["ok"] else item["error"])[:2200],
                "frame": {"x": 36 + (index % 2) * 32, "y": 4 + (index // 2) * 34, "width": 30},
            })
        objects.append({
            "id": "verified", "type": "verified-result", "title": "Mission result",
            "eyebrow": "Evidence", "tone": "verified" if mission.status == "completed" else "attention",
            "statement": summary[:400],
            "evidence": [f"{step.title[:80]}: {'verified' if step.verified else 'failed'}"
                         for step in mission.completed][:6] or ["No capability call was required"],
            "timestamp": datetime.now().astimezone().strftime("%H:%M \u00b7 General planner"),
            "frame": {"x": 30, "y": 74, "width": 40, "layer": 2},
        })
        composition = {
            "schemaVersion": 1, "id": f"general-{task.id[:12]}", "mode": "tool-execution",
            "label": "VYOM / Autonomous", "summary": summary[:400],
            "generatedAt": datetime.now().astimezone().strftime("%H:%M \u00b7 General planner"),
            "objects": objects,
            "sequence": [
                {"id": f"s{i}", "label": (o.get("title") or "Activity")[:40], "atMs": 150 + i * 280,
                 "state": "Verifying" if i == len(objects) - 1 else "Executing", "objectIds": [o["id"]]}
                for i, o in enumerate(objects)
            ],
        }

        task.metadata["general_mission"] = {
            "status": mission.status, "tool_calls": len(mission.completed),
            "verified": verified, "model_calls": mission.model_calls,
        }
        for index, step in enumerate(task.plan):
            step.status = "complete"
            task.current_step = index
        task.progress = 0.8
        await self.task_store.save(task)

        if mission.status != "completed":
            raise RuntimeError(summary)

        result = ExecutionResult(
            response=summary,
            structured_data={"mission": task.metadata["general_mission"], "observations": collected},
            ui_composition=composition,
            evidence=[f"{step.title[:90]}" for step in mission.completed] or [summary],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )
        await self._finish_result(task, result, None, started, retries, fallback_used)

    # -- multi-agent mission ----------------------------------------------

    async def _run_multi_agent_mission(
        self, task: Task, profile, started: float, retries: int, fallback_used: bool
    ) -> None:
        """Split a genuinely multi-domain goal across the role agents and
        run them in parallel through the existing MultiAgentOrchestrator.

        Each role agent is delegated through AgentRuntime -> the bounded
        autonomous worker, which only exposes that agent's own scoped
        `tools`. The runtime does not gain new powers: every sub-agent
        call goes through the SAME ToolExecutor and permission engine as
        a single-agent mission.
        """
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord

        orchestrator = self.multi_agent_orchestrator
        task.assigned_model = "local-multi-agent-v1"
        await self.task_store.save(task)
        await self._emit(
            task, EventType.MODEL_SELECTED, "Selected the multi-agent orchestrator",
            {"routing": {"primary_model": "local-multi-agent-v1", "primary_provider": "local",
                         "fallback_models": [], "estimated_cost_tier": "low",
                         "reason_selected": "Multi-domain goal; split across role agents with scoped tools"}},
        )
        await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS,
                               "Delegating to role agents")

        async def emit(event_type: str, message: str, payload: dict) -> None:
            try:
                await self._emit(task, EventType(event_type), message, payload)
            except ValueError:
                await self._emit(task, EventType.TASK_PROGRESS, message, payload)

        try:
            # Sequential (max_parallel=1): on the free tier a single model
            # meters ~12 requests/minute, so four agents firing ReAct
            # calls at once just rate-limit each other. One at a time,
            # each role agent gets the full window and the goal is still
            # divided across scoped tools.
            outcome = await orchestrator.execute(
                task.user_request, task, emit, max_parallel=1, timeout_seconds=600,
            )
        except Exception as error:  # pragma: no cover - defensive
            # An orchestration failure falls back to the single-agent
            # planner rather than failing the whole request.
            await self._emit(task, EventType.TASK_PROGRESS,
                             f"Multi-agent path failed ({str(error)[:160]}); using the single planner",
                             {})
            await self._run_general_mission(task, profile, started, retries, fallback_used)
            return

        # A sub-task only counts as real work when it produced a
        # non-empty answer that is not itself a "hit the limit" message.
        # "Stopped after reaching the 8-step bound" is a failure to
        # report, not a result.
        _NON_ANSWERS = ("stopped after reaching", "pacing window full",
                        "no configured model", "step bound", "budget exhausted",
                        "verification failed")

        def _real_answer(st) -> str:
            text = str((st.result or {}).get("response", "")).strip()
            if not text or any(marker in text.lower() for marker in _NON_ANSWERS):
                return ""
            return text

        completed = [st for st in outcome.sub_tasks if st.status == "completed" and _real_answer(st)]
        quota_blocked = sum(
            1 for st in outcome.sub_tasks
            if any(m in str(st.error or (st.result or {}).get("response", "")).lower()
                   for m in ("pacing window full", "no configured model", "remaining quota"))
        )
        lines: list[str] = []
        for st in outcome.sub_tasks:
            role = st.agent_id or "unassigned"
            answer = _real_answer(st)
            if answer:
                lines.append(f"[{role}] {answer[:400]}")
            elif st.status == "skipped":
                lines.append(f"[{role}] skipped: {st.error or 'no matching agent'}")
            else:
                detail = str(st.error or (st.result or {}).get("response") or st.status).strip()
                lines.append(f"[{role}] could not finish: {detail[:200]}")
        summary = "\n".join(lines).strip() or "No role agent produced a result."
        if quota_blocked:
            summary += (
                f"\n\n({quota_blocked} of {len(outcome.sub_tasks)} agents could not run - "
                "the free model's per-minute quota was exhausted. Try again in a minute, "
                "or narrow the request to one domain.)"
            )

        objects: list[dict] = [{
            "id": "mission", "type": "task-mission", "title": "Multi-agent mission",
            "eyebrow": "Orchestrator", "tone": "intelligence",
            "mission": task.user_request[:120],
            "status": "complete" if outcome.status == "completed" else (
                "partial" if outcome.status == "partial" else "failed"),
            "details": [f"{st.agent_id}: {st.status}" for st in outcome.sub_tasks][:8],
            "frame": {"x": 2, "y": 4, "width": 32},
        }]
        for index, st in enumerate(outcome.sub_tasks[:6]):
            objects.append({
                "id": f"sub-{index}", "type": "terminal-output",
                "title": st.agent_id or "unassigned", "eyebrow": "Role agent",
                "command": st.goal[:160],
                "exitCode": 0 if st.status == "completed" else 1,
                "output": str((st.result or {}).get("response") if st.result else st.error)[:2000],
                "frame": {"x": 36 + (index % 2) * 32, "y": 4 + (index // 2) * 30, "width": 30},
            })
        objects.append({
            "id": "verified", "type": "verified-result", "title": "Combined result",
            "eyebrow": "Evidence",
            "tone": "verified" if outcome.status == "completed" else "attention",
            "statement": summary[:400],
            "evidence": [f"{st.agent_id}: {st.status}" for st in outcome.sub_tasks][:8] or ["no sub-tasks"],
            "timestamp": datetime.now().astimezone().strftime("%H:%M · Orchestrator"),
            "frame": {"x": 30, "y": 70, "width": 42, "layer": 2},
        })
        composition = {
            "schemaVersion": 1, "id": f"multiagent-{task.id[:12]}", "mode": "tool-execution",
            "label": "VYOM / Multi-agent", "summary": summary[:400],
            "generatedAt": datetime.now().astimezone().strftime("%H:%M · Orchestrator"),
            "objects": objects,
            "sequence": [
                {"id": f"s{i}", "label": (o.get("title") or "Activity")[:40], "atMs": 150 + i * 260,
                 "state": "Verifying" if i == len(objects) - 1 else "Executing", "objectIds": [o["id"]]}
                for i, o in enumerate(objects)
            ],
        }

        task.metadata["multi_agent_mission"] = {
            "status": outcome.status,
            "sub_tasks": len(outcome.sub_tasks),
            "completed": len(completed),
            "agents_used": outcome.agents_used,
            "total_time_ms": round(outcome.total_time_ms, 1),
        }
        for index, step in enumerate(task.plan):
            step.status = "complete"
            task.current_step = index
        task.progress = 0.8
        await self.task_store.save(task)

        if outcome.status == "failed" or not completed:
            raise RuntimeError(summary)

        result = ExecutionResult(
            response=summary,
            structured_data={
                "multi_agent": task.metadata["multi_agent_mission"],
                "sub_tasks": [
                    {"agent": st.agent_id, "status": st.status,
                     "response": (st.result or {}).get("response") if st.result else None,
                     "error": st.error, "evidence": st.evidence}
                    for st in outcome.sub_tasks
                ],
            },
            ui_composition=composition,
            evidence=[f"{st.agent_id}: {st.status}" for st in outcome.sub_tasks] or [summary],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )
        await self._finish_result(task, result, None, started, retries, fallback_used)

    # -- multi-step missions ------------------------------------------------

    def _detect_mission(self, request: str) -> list[str]:
        """Split a compound request into clauses and keep it only if at
        least two clauses independently resolve to a real tool action.

        Conservative on purpose: a single-action request keeps its
        existing direct path, and a purely conversational sentence is
        never turned into a mission."""
        import re

        if self.action_engine is None:
            return []
        # A fallback-instruction connector ("if that fails, instead ...",
        # "otherwise ...") separates two REAL steps just as much as "and"
        # or "then" does, but was not recognised here — "Try X. If that
        # fails, instead do Y." never split, so the whole sentence stayed
        # one clause, degraded to a single-intent execution with no
        # fallback path, and a request that raised an exception on X had
        # no chance to ever attempt Y. Normalize these connectors to a
        # sentence boundary before the existing clause split.
        normalized = re.sub(
            r"\s*(?:if that fails|if it fails|if unsuccessful|if not|otherwise)\s*,?\s*(?:instead\s+)?",
            ". ", request, flags=re.IGNORECASE,
        )
        parts = [
            part.strip(" .")
            for part in re.split(
                r",\s*(?:and\s+)?|\s+and\s+then\s+|\s+then\s+|\s+and\s+|;\s*|(?<=[.!?])\s+",
                normalized,
            )
            if part.strip(" .")
        ]
        # A leading wake word is address, not a step.
        parts = [part for part in parts if part.strip(" .,!").lower() not in {"vyom", "hey vyom", "ok vyom"}]
        if len(parts) < 2:
            return []
        # Require two DISTINCT actionable intents. Clause count alone is not
        # enough: "Open a browser and search the web for X" splits into two
        # clauses that are both `web_browse` - one action described twice,
        # not a two-step mission. Splitting it produced a first step
        # ("Open a browser") with no resolvable target, which failed the
        # whole request. Distinct intents ("inspect this project" +
        # "run its tests") are a genuine mission.
        intents: set[str] = set()
        for part in parts:
            try:
                intent = self.classifier.classify(part).intent
            except Exception:
                continue
            if self.action_engine.supports(intent):
                intents.add(intent)
        # Two clauses that resolve to the same tool intent (e.g.
        # "open Chrome" + "search YouTube" both → web_browse) still
        # form a genuine mission: the user expects TWO actions.
        # The old check (len(intents) >= 2) required two DISTINCT
        # intents, which silently dropped compound browser goals.
        return parts if len(parts) >= 2 and intents else []

    async def _run_mission(
        self,
        task: Task,
        profile,
        steps: list[str],
        started: float,
        retries: int,
        fallback_used: bool,
    ) -> None:
        """Execute a compound goal through the existing MissionLoop, with
        every step performed by the existing ActionEngine (real tools),
        and merge the per-step UI compositions into one composition so the
        canvas assembles itself as the mission progresses."""
        from app.schemas.results import ExecutionResult
        from app.schemas.routing import UsageRecord

        task.assigned_model = "local-mission-loop-v1"
        await self.task_store.save(task)
        await self._emit(
            task, EventType.MODEL_SELECTED, "Selected the autonomous mission loop",
            {"routing": {"primary_model": "local-mission-loop-v1", "primary_provider": "local",
                         "fallback_models": [], "estimated_cost_tier": "free",
                         "reason_selected": f"Compound goal with {len(steps)} actionable clauses; "
                                            "executed step-by-step through registered tools"}},
        )
        await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS,
                               f"Running a {len(steps)}-step mission through registered tools")

        async def emit_step(event_type: str, message: str, payload: dict) -> None:
            await self._emit(task, EventType(event_type), message, payload)

        collected: list[ExecutionResult] = []

        async def step_executor(title: str, context: dict) -> dict:
            step_profile = self.classifier.classify(title)
            if not self.action_engine.supports(step_profile.intent):
                lowered = title.lower()
                if any(
                    phrase in lowered
                    for phrase in ("tell me", "report", "what's wrong", "whats wrong",
                                   "summarise", "summarize", "let me know", "explain what")
                ):
                    # A reporting clause is answered from what the mission
                    # actually observed - never from model speculation.
                    findings = [item.response for item in collected]
                    problems = [
                        line for item in collected for line in (item.evidence or [])
                        if any(word in line.lower() for word in ("fail", "error", "unavailable", "missing", "not a "))
                    ]
                    report = " ".join(findings)[:500] or "No step produced an observation."
                    if problems:
                        report += " Issues found: " + "; ".join(problems[:5])
                    else:
                        report += " No failures were observed in the executed steps."
                    return {"ok": True, "output": report, "evidence": problems}
                # Honest skip: no registered capability performs this step.
                return {"ok": True, "skipped": True,
                        "output": f"No registered tool performs '{title}'; step recorded as not executed."}
            # Each step is granted exactly what its OWN intent requires,
            # never more than the mission itself was granted.
            step_level = self.permission_engine.raise_to_intent_floor(
                task.permission_level, step_profile.intent
            )
            if self.permission_engine.requires_approval(step_level) and not task.approval_granted:
                return {"ok": False,
                        "error": f"'{title}' requires {step_level.value} approval, which this mission does not hold."}
            step_task = task.model_copy(update={"user_request": title, "permission_level": step_level})
            try:
                result = await self.action_engine.execute(step_task, step_profile, emit_step)
            except Exception as error:
                # A step handler that RAISES (a missing file, an
                # unreachable host, a bad selector, ...) must become a
                # {"ok": False, "error": ...} observation, not an
                # uncaught exception that crashes the whole mission past
                # every remaining clause. MissionLoop._execute_step already
                # retries a failed step with an adaptation hint pulled from
                # prior experience (see its "inspecting and adapting"
                # branch) — that logic never ran before this fix because a
                # raised exception here propagated straight out of run(),
                # so a single failing clause (e.g. "read this nonexistent
                # file") could abort a compound goal before its OWN later
                # clause ("...then list the directory instead") ever
                # executed.
                return {"ok": False, "error": str(error)[:300]}
            collected.append(result)
            return {"ok": True, "output": result.response, "evidence": result.evidence}

        async def step_verifier(title: str, outcome: dict) -> bool:
            return bool(outcome.get("ok")) and not outcome.get("skipped", False)

        # Consequential steps pause the mission at a checkpoint instead of
        # executing unapproved, using the MissionLoop's existing gate.
        step_permissions: dict[str, str] = {}
        for title in steps:
            try:
                level = self.permission_engine.minimum_for_intent(self.classifier.classify(title).intent)
            except Exception:
                level = None
            if level is not None and self.permission_engine.requires_approval(level):
                step_permissions[title] = level.value

        mission = await self.mission_loop.run(
            task.user_request,
            executor=step_executor,
            verifier=step_verifier,
            step_permissions=step_permissions,
            mission_id=task.id,
            plan=steps,
        )
        await self._check_control(task)

        verified = sum(1 for step in mission.completed if step.verified)
        lines = [f"{step.title}: {step.status}" for step in mission.completed]
        # Describe what was ACHIEVED, not how many calls were made. A tool
        # counter is telemetry; presenting it as the answer is what made
        # VYOM sound finished when the user's goal had not been reached.
        if collected:
            summary = " ".join(item.response for item in collected)[:600]
        elif verified:
            summary = "; ".join(step.title for step in mission.completed if step.verified)[:400]
        else:
            summary = "No step produced a verified result."

        objects: list[dict] = [{
            "id": "mission", "type": "task-mission", "title": "Mission",
            "eyebrow": "Autonomous mission loop", "tone": "intelligence",
            "mission": task.user_request[:120],
            "status": "complete" if mission.status == "completed" else "failed",
            "details": lines[:6], "frame": {"x": 2, "y": 3, "width": 30},
        }]
        # Lay the per-step objects out on a deterministic grid. Reusing each
        # sub-composition's own frame stacked several cards on the same
        # coordinates, because every single-intent composition is authored
        # to sit alone on the canvas.
        slots = [
            (36, 3), (69, 3), (2, 34), (36, 34), (69, 34),
            (2, 64), (36, 64), (69, 64), (18, 48), (52, 48),
        ]
        slot_index = 0
        for index, item in enumerate(collected):
            for obj in (item.ui_composition or {}).get("objects", []):
                if obj.get("type") == "task-mission":
                    continue
                clone = dict(obj)
                clone["id"] = f"s{index}-{obj['id']}"
                x, y = slots[slot_index % len(slots)]
                slot_index += 1
                width = min(int((clone.get("frame") or {}).get("width", 29)), 100 - x)
                clone["frame"] = {"x": x, "y": y, "width": width,
                                  "layer": (clone.get("frame") or {}).get("layer", 1)}
                objects.append(clone)

        composition = {
            "schemaVersion": 1, "id": f"mission-{task.id[:12]}", "mode": "tool-execution",
            "label": "VYOM / Mission", "summary": summary[:400],
            "generatedAt": datetime.now().astimezone().strftime("%H:%M · Mission loop"),
            "objects": objects,
            "sequence": [
                {"id": f"step-{index}", "label": (obj.get("title") or "Mission activity")[:40],
                 "atMs": 160 + index * 300,
                 "state": "Verifying" if index == len(objects) - 1 else "Executing",
                 "objectIds": [obj["id"]]}
                for index, obj in enumerate(objects)
            ],
        }

        for index, step in enumerate(task.plan):
            step.status = "complete"
            task.current_step = index
        task.progress = 0.8
        task.metadata["mission"] = {
            "status": mission.status, "steps": lines,
            "verified": verified, "experience_saved": mission.experience_saved,
        }
        await self.task_store.save(task)

        # A mission whose steps were all skipped is not a success. Requiring
        # at least one VERIFIED step means "mission completed" can never be
        # reported for work no tool actually performed.
        if mission.status != "completed" or verified == 0:
            raise RuntimeError(
                summary
                if mission.status != "completed"
                else f"{summary} No step was verified by a real tool execution; "
                     "the mission is reported as failed rather than as a completion."
            )

        result = ExecutionResult(
            response=summary,
            structured_data={"mission": task.metadata["mission"],
                             # The verifier reads 'observations' but the mission
                             # loop writes 'steps'. Both keys carry the same
                             # per-step data so either reader finds it.
                             "steps": [item.structured_data for item in collected],
                             "observations": [item.structured_data for item in collected]},
            ui_composition=composition,
            evidence=[evidence for item in collected for evidence in (item.evidence or [])] or lines,
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )
        await self._finish_result(task, result, None, started, retries, fallback_used)

    async def _execute_and_finish(
        self,
        task: Task,
        profile,
        provider,
        routing,
        started: float,
        retries: int,
        fallback_used: bool,
    ) -> None:
        await self._check_control(task)
        await self._transition(task, TaskStatus.EXECUTING, EventType.TASK_PROGRESS, "Executing non-tool reasoning steps")
        for index, step in enumerate(task.plan):
            await self._check_control(task)
            step.status = "complete"
            task.current_step = index
            task.progress = min(0.75, (index + 1) / max(len(task.plan), 1) * 0.75)
            await self.task_store.save(task)

        result = await self.executor.execute(task, profile, provider, routing)
        await self._check_control(task)
        await self._finish_result(task, result, routing, started, retries, fallback_used)

    async def _finish_result(
        self,
        task: Task,
        result,
        routing,
        started: float,
        retries: int,
        fallback_used: bool,
    ) -> None:
        # THE USER-FACING BOUNDARY. Every completion path in the runtime
        # funnels through here, so this is where "no raw dict, no pid, no
        # internal path in speech" becomes a structural guarantee rather
        # than a per-engine convention. Diagnostics keep the original in
        # structured_data, evidence and the logs.
        from .error_messages import sanitise_user_response

        if result.response:
            result.response = sanitise_user_response(result.response)
        task.result = result
        if routing:
            self.usage_tracker.record(routing.primary_model, result.usage)
        await self._transition(task, TaskStatus.VERIFYING, EventType.VERIFICATION_STARTED, "Verifying the result")
        verification = await self.verifier.verify(task, result)
        task.verification = verification
        await self.task_store.save(task)
        if not verification.passed:
            await self._emit(
                task,
                EventType.VERIFICATION_FAILED,
                verification.summary,
                {"verification": verification.model_dump(mode="json")},
            )
            raise RuntimeError(verification.summary)

        # GOAL VERIFICATION. Structural verification above only proves the
        # result is well-formed. This is the single authority that decides
        # whether the thing the USER asked for actually happened, read from
        # the real world - the process table, the window list, the
        # filesystem, the application's own display.
        #
        # Nothing below may reach COMPLETED without passing here. A task
        # that did not achieve its goal is reported as failed, never as a
        # completion with a caveat.
        intent = task.profile.intent if task.profile else "general"
        goal_status, goal_evidence = self.goal_verifier.verify(intent=intent, result=result)

        # WHOLE-GOAL VERIFICATION.
        #
        # The intent map above only covers goals the classifier recognised
        # deterministically. Anything routed to the general planner arrived
        # here with intent "general", which is absent from the map, so it
        # returned NOT_APPLICABLE and the task completed on the STRUCTURAL
        # verifier alone - whose passing evidence is "Non-empty response".
        #
        # That is how "Stop. Stop. Stop." completed at score 1.0 after
        # listing a directory, how a Google CAPTCHA page passed as a
        # completed search, and how "open Chrome AND search X" was reported
        # done with nothing searched.
        #
        # Every task now also states its goal as a set of required effects
        # and must satisfy ALL of them against real observations.
        from .verifier import derive_goal_frame

        goal_frame = derive_goal_frame(task.user_request)
        if goal_frame:
            observations = (result.structured_data or {}).get("observations") or []
            frame_status, frame_evidence = self.goal_verifier.verify_goal(
                goal_frame=goal_frame, observations=observations, result=result,
            )
            task.metadata["goal_frame"] = {
                "required": [effect["kind"] for effect in goal_frame.effects],
                "status": frame_status,
                "evidence": frame_evidence,
            }
            # The stricter of the two verdicts wins. A goal is complete only
            # when nothing that was asked for is missing.
            if frame_status in {"FAILED", "PARTIAL"}:
                goal_status, goal_evidence = frame_status, frame_evidence
            elif frame_status == "VERIFIED_COMPLETE" and goal_status == "NOT_APPLICABLE":
                goal_status, goal_evidence = frame_status, frame_evidence

        # The metadata record keeps the raw, check-name-prefixed evidence
        # (diagnostic, machine-groupable); every string the user actually
        # reads or hears below uses the stripped version instead.
        task.metadata["goal_verification"] = {"status": goal_status, "evidence": goal_evidence}
        await self.task_store.save(task)
        if goal_status in {"FAILED", "PARTIAL"}:
            readable_evidence = _humanize_goal_evidence(goal_evidence)
            await self._emit(
                task,
                EventType.VERIFICATION_FAILED,
                f"The goal was not achieved: {readable_evidence}",
                {"goal_verification": task.metadata["goal_verification"]},
            )
            raise RuntimeError(
                f"{result.response.strip()[:200]} "
                f"However, this was NOT verified in the real world: {readable_evidence}"
                if goal_status == "PARTIAL"
                else f"The goal was not achieved: {readable_evidence}"
            )
        if goal_status == "VERIFIED_COMPLETE":
            readable_evidence = _humanize_goal_evidence(goal_evidence)
            await self._emit(
                task,
                EventType.VERIFICATION_EVIDENCE,
                f"Goal verified: {readable_evidence}",
                {"goal_verification": task.metadata["goal_verification"]},
            )
            verification.evidence.append(f"goal postcondition: {readable_evidence}")

        await self._emit(
            task,
            EventType.VERIFICATION_PASSED,
            verification.summary,
            {"verification": verification.model_dump(mode="json")},
        )
        if result.ui_composition:
            await self._emit(
                task,
                EventType.VISUALIZATION_REQUESTED,
                "Composing the relevant visual workspace",
                {"layout": "contextual", "composition": result.ui_composition},
            )

        if self.intelligence_engine is not None:
            async def emit_memory(event_type: str, message: str, payload: dict) -> None:
                await self._emit(task, EventType(event_type), message, payload)
            await self.intelligence_engine.consolidate_task(task, emit_memory)

        task.status = TaskStatus.COMPLETED
        task.progress = 1
        task.completed_at = datetime.now(timezone.utc)
        await self.task_store.save(task)

        # RAW TRANSCRIPT. Distinct from the structured task row above and
        # from any summarized memory below: this is the exact user request
        # and exact response, so a later session can literally full-text
        # search "what did I say about X" (see ConversationStore.search),
        # the way a real chat-history search works, not just "what tasks
        # touched X". Best-effort - a transcript write failure must never
        # break the user-facing response that already succeeded.
        if self.conversation_store is not None:
            try:
                await self.conversation_store.record_exchange(
                    context_id=task.context_id, task_id=task.id,
                    user_message=task.user_request, assistant_response=result.response or "",
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning("Failed to record conversation turn for task %s", task.id, exc_info=True)

        # PLUGIN HOOK. Fires after every real completion, same boundary
        # as conversation recording above - see app/plugins/registry.py.
        # A broken plugin callback is isolated by invoke_hook and can
        # never break the response that already succeeded.
        if self.plugin_registry is not None and self.plugin_registry.has_hook("post_task_complete"):
            await self.plugin_registry.invoke_hook("post_task_complete", task=task, result=result)

        # ACTIVE CONTEXT. Record what this task actually DID - the URL that
        # opened, the profile attached to, the windows read - so the next
        # "usko" / "ye kya hai?" resolves against what just happened
        # instead of against whatever ranked highest in durable memory.
        if self.cognitive_runtime is not None:
            try:
                self.cognitive_runtime.record_observation(task=task, result=result)
            except Exception:
                import logging

                logging.getLogger("vyom.cognitive").exception(
                    "failed to record active context for task %s", task.id
                )  # never blocks a completion

        await self._emit(
            task,
            EventType.TASK_COMPLETED,
            result.response,
            {"response": result.response, "task": task.model_dump(mode="json")},
        )
        if routing:
            await self.performance_store.record(
                task=task,
                model=routing.primary_model,
                provider=routing.primary_provider,
                success=True,
                latency_ms=(time.perf_counter() - started) * 1000,
                retries=retries,
                fallback_used=fallback_used,
            )
            if self.cost_tracker is not None:
                usage = result.usage
                self.cost_tracker.record_call(
                    routing.primary_provider, routing.primary_model,
                    input_tokens=usage.input_tokens or 0, output_tokens=usage.output_tokens or 0,
                    cost=usage.estimated_cost or 0.0, failed=False, retried=retries > 0 or fallback_used,
                )

    async def pause(self, task_id: str) -> Task:
        task = await self._require_task(task_id)
        if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            task.status = TaskStatus.PAUSED
            await self.task_store.save(task)
        return task

    async def resume(self, task_id: str) -> Task:
        task = await self._require_task(task_id)
        if task.status == TaskStatus.PAUSED:
            # A resumed mission's further actions are authorised as
            # continuation of the SAME already-approved goal, not as a new
            # user command arriving out of nowhere.
            task.metadata["provenance"] = ActionProvenance.CURRENT_GOAL_RECOVERY.value
            task.status = TaskStatus.QUEUED
            await self.task_store.save(task)
            self._start(task.id)
        return task

    async def cancel(self, task_id: str) -> Task:
        task = await self._require_task(task_id)
        if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            if self.action_engine is not None:
                await self.action_engine.cancel(task_id)
            # Propagate into the MISSION as well. Missions are keyed by the
            # task id, but cancelling the task only stopped the tool
            # context - the mission kept looping and could still spend a
            # model call and emit a final answer for an utterance the user
            # had already replaced. A superseded task must never speak.
            if self.mission_loop is not None:
                try:
                    self.mission_loop.cancel(task_id)
                except Exception:
                    pass
            background = self.active.get(task_id)
            if background is not None and not background.done():
                background.cancel()
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now(timezone.utc)
            await self.task_store.save(task)
            await self._emit(task, EventType.TASK_CANCELLED, "Task cancelled")
        return task

    async def decide_approval(self, task_id: str, approved: bool) -> Task:
        task = await self._require_task(task_id)
        if task.status != TaskStatus.NEEDS_APPROVAL:
            raise ValueError("Task is not waiting for approval")
        approval_data = task.metadata.get("approval")
        if approval_data and datetime.fromisoformat(str(approval_data["expires_at"])) < datetime.now(timezone.utc):
            task.status = TaskStatus.CANCELLED
            task.error = "Approval expired"
            task.completed_at = datetime.now(timezone.utc)
            await self.task_store.save(task)
            await self._emit(task, EventType.TASK_CANCELLED, "Approval expired; task cancelled")
            return task
        if not approved:
            task.status = TaskStatus.CANCELLED
            task.error = "Approval rejected"
            task.completed_at = datetime.now(timezone.utc)
            await self.task_store.save(task)
            await self._emit(task, EventType.TASK_CANCELLED, "Approval rejected; task cancelled")
            return task
        task.approval_granted = True
        task.status = TaskStatus.QUEUED
        await self.task_store.save(task)
        self._start(task.id)
        return task

    async def resume_incomplete_tasks(self, *, skip_ids: set[str] | None = None) -> int:
        """Restarts tasks left active by an unclean shutdown/restart.

        `skip_ids` are tasks a prior recovery decision already found unsafe
        to blindly re-execute (consequential work with evidence of a
        partial external action, or owned by another node) - those are
        parked as PAUSED instead of restarted, so a restart can never
        silently repeat a consequential action a second time."""
        resumable = await self.task_store.list_by_status(
            {
                TaskStatus.QUEUED,
                TaskStatus.UNDERSTANDING,
                TaskStatus.PLANNING,
                TaskStatus.WAITING,
                TaskStatus.EXECUTING,
                TaskStatus.VERIFYING,
            }
        )
        skip_ids = skip_ids or set()
        resumed = 0
        for task in resumable:
            if task.id in skip_ids:
                task.status = TaskStatus.PAUSED
                await self.task_store.save(task)
                continue
            task.status = TaskStatus.QUEUED
            await self.task_store.save(task)
            self._start(task.id)
            resumed += 1
        return resumed

    async def _check_control(self, task: Task) -> None:
        stored = await self.task_store.get(task.id)
        if stored and stored.status == TaskStatus.CANCELLED:
            raise TaskCancelled
        while stored and stored.status == TaskStatus.PAUSED:
            await asyncio.sleep(0.05)
            stored = await self.task_store.get(task.id)
            if stored and stored.status == TaskStatus.CANCELLED:
                raise TaskCancelled

    async def _transition(
        self,
        task: Task,
        status: TaskStatus,
        event_type: EventType,
        message: str,
    ) -> None:
        task.status = status
        await self.task_store.save(task)
        await self._emit(task, event_type, message, {"status": status.value, "progress": task.progress})

    #: A task may enter a terminal state exactly once. APPROVAL_REQUIRED is
    #: deliberately absent - a task waits there and then resumes, so it is
    #: not an end state.
    _TERMINAL_EVENTS = frozenset({
        EventType.TASK_COMPLETED, EventType.TASK_FAILED, EventType.TASK_CANCELLED,
    })

    async def _emit(
        self,
        task: Task,
        event_type: EventType,
        message: str,
        payload: dict | None = None,
    ) -> None:
        # IDEMPOTENT TERMINALIZATION. Every completion path in this runtime
        # funnels through here, so this is the one place that can guarantee
        # a task terminalises once. A second attempt is dropped and logged -
        # never spoken, never rendered, never written to memory.
        if event_type in self._TERMINAL_EVENTS:
            previous = self._terminalized.get(task.id)
            if previous is not None:
                import logging

                logging.getLogger("vyom.runtime").warning(
                    "duplicate terminal event suppressed: task=%s already %s, attempted %s",
                    task.id, previous, event_type.value,
                )
                return
            self._terminalized[task.id] = event_type.value
            while len(self._terminalized) > 512:
                self._terminalized.popitem(last=False)

        # Per-task visibility is surfaced on EVERY event so the frontend can
        # react the moment it is known: a 'background' task (profile.visibility)
        # tells VYOM's own window to minimize itself and work invisibly; a
        # 'visual' task keeps the window up (the browser itself opens headed).
        # Mirrored from app/execution/visibility.classify_visibility at task
        # classify time; absent for events emitted before profile is set.
        event_payload = dict(payload or {})
        visibility = getattr(getattr(task, "profile", None), "visibility", None)
        if visibility:
            event_payload["window_visibility"] = visibility

        await self.event_bus.publish(
            BrainEvent(
                task_id=task.id,
                type=event_type,
                human_readable_message=message,
                structured_payload=event_payload,
            )
        )

    async def _require_task(self, task_id: str) -> Task:
        task = await self.task_store.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.events import BrainEvent, EventType
from app.runtime.event_bus import EventBus

from .registry import AgentRegistry
from .runtime import AgentRuntime
from .schemas import AgentSpec, AgentStatus


@dataclass
class SubTask:
    """A piece of work delegated to one agent."""
    id: str
    goal: str
    agent_id: str | None = None
    status: str = "pending"  # pending | running | completed | failed | skipped
    result: dict | None = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class OrchestratorPlan:
    """How the orchestrator will split a complex goal into sub-tasks."""
    goal: str
    sub_tasks: list[SubTask]
    strategy: str = "parallel"  # parallel | sequential | pipeline
    created_at: float = field(default_factory=time.perf_counter)


@dataclass
class OrchestratorResult:
    """Final result of a multi-agent mission."""
    goal: str
    status: str  # completed | partial | failed
    sub_tasks: list[SubTask]
    summary: str
    total_time_ms: float
    agents_used: list[str]
    total_tool_calls: int = 0
    total_model_calls: int = 0


# Built-in agent roles for the 10-agent system
BUILTIN_AGENTS = [
    {
        "id": "researcher",
        "name": "Research Agent",
        "role": "Research and information gathering",
        "capabilities": ["web_browse", "memory_search", "browser_read"],
        "description": "Searches the web, reads pages, and gathers information from any source.",
    },
    {
        "id": "coder",
        "name": "Coding Agent",
        "role": "Write, edit, and review code",
        "capabilities": ["fs_read", "fs_list", "fs_search", "create_project_file", "run_command"],
        "description": "Writes code, runs tests, fixes bugs, and manages project files.",
    },
    {
        "id": "analyst",
        "name": "Analysis Agent",
        "role": "Data analysis and reporting",
        "capabilities": ["memory_search", "fs_read", "system_query"],
        "description": "Analyzes data, generates reports, and provides insights.",
    },
    {
        "id": "desktop-operator",
        "name": "Desktop Operator",
        "role": "Control desktop applications",
        "capabilities": ["app_launch", "app_close", "screen_observe", "ui_interact"],
        "description": "Opens apps, clicks buttons, types text, and controls the desktop.",
    },
    {
        "id": "browser-operator",
        "name": "Browser Operator",
        "role": "Web browsing and interaction",
        "capabilities": ["browser_tab_open", "browser_page_type", "browser_page_click",
                         "browser_page_read", "browser_first_result", "browser_page_scroll"],
        "description": "Navigates websites, fills forms, clicks links, and extracts content.",
    },
    {
        "id": "file-manager",
        "name": "File Manager",
        "role": "File system operations",
        "capabilities": ["fs_list", "fs_read", "fs_search", "create_project_file", "delete_project_file"],
        "description": "Manages files, directories, and project structure.",
    },
    {
        "id": "communicator",
        "name": "Communication Agent",
        "role": "Email and messaging",
        "capabilities": ["send_email"],
        "description": "Drafts and sends emails, manages communications.",
    },
    {
        "id": "monitor",
        "name": "Monitor Agent",
        "role": "System monitoring and health",
        "capabilities": ["system_query", "screen_observe"],
        "description": "Monitors system health, CPU, memory, and running processes.",
    },
    {
        "id": "planner",
        "name": "Planning Agent",
        "role": "Task planning and scheduling",
        "capabilities": ["memory_search"],
        "description": "Creates plans, breaks down goals, and schedules work.",
    },
    {
        "id": "verifier",
        "name": "Verification Agent",
        "role": "Quality assurance and verification",
        "capabilities": ["fs_read", "system_query", "screen_observe"],
        "description": "Verifies results, checks quality, and confirms completion.",
    },
]


class MultiAgentOrchestrator:
    """Coordinates multiple agents working in parallel on complex goals.

    This is the core of VYOM's multi-agent capability. When a goal is too
    complex for a single agent, the orchestrator:
    1. Decomposes the goal into sub-tasks
    2. Assigns each sub-task to the best-fit agent
    3. Runs agents in parallel (with dependency ordering)
    4. Collects and merges results
    5. Verifies the combined outcome

    Maximum parallelism: 10 agents (configurable via AgentBudget).
    """

    MAX_PARALLEL = 10

    def __init__(
        self,
        agent_registry: AgentRegistry,
        agent_runtime: AgentRuntime,
        event_bus: EventBus | None = None,
        task_runtime=None,
    ):
        self.registry = agent_registry
        self.runtime = agent_runtime
        self.event_bus = event_bus
        self.task_runtime = task_runtime
        self._active_missions: dict[str, OrchestratorPlan] = {}

    async def _emit(self, task_id: str, event_type: EventType, message: str, payload: dict) -> None:
        if self.event_bus is not None:
            await self.event_bus.publish(BrainEvent(
                task_id=task_id, type=event_type,
                human_readable_message=message, structured_payload=payload,
            ))

    def _find_best_agent(self, sub_task: SubTask, available: set[str]) -> AgentSpec | None:
        """Match a sub-task to the best available agent by capability overlap."""
        best_agent = None
        best_score = 0
        for agent_id in available:
            agent = self.registry.get(agent_id)
            if agent is None or agent.status not in {AgentStatus.READY, AgentStatus.TESTING}:
                continue
            # Score = number of matching capabilities
            score = len(set(agent.capabilities) & set(sub_task.goal.lower().split()))
            # Bonus for role relevance
            role_words = set(agent.role.lower().split())
            goal_words = set(sub_task.goal.lower().split())
            score += len(role_words & goal_words)
            if score > best_score:
                best_score = score
                best_agent = agent
        return best_agent

    def decompose(self, goal: str) -> OrchestratorPlan:
        """Break a complex goal into parallelizable sub-tasks.

        Uses keyword heuristics to identify which agents are needed.
        Falls back to a single sub-task if decomposition isn't possible.
        """
        lowered = goal.lower()
        sub_tasks = []

        # Research component
        if any(w in lowered for w in ("research", "find", "search", "look up", "investigate",
                                       "khoj", "dhoondho", "pata karo", "padho")):
            sub_tasks.append(SubTask(
                id=f"sub_{uuid4().hex[:8]}",
                goal=f"Research: {goal}",
                agent_id="researcher",
            ))

        # Coding component
        if any(w in lowered for w in ("code", "write", "create file", "fix bug", "implement",
                                       "banao", "likho", "code karo")):
            sub_tasks.append(SubTask(
                id=f"sub_{uuid4().hex[:8]}",
                goal=f"Code: {goal}",
                agent_id="coder",
            ))

        # Desktop action component
        if any(w in lowered for w in ("open", "close", "launch", "click", "type",
                                       "kholo", "band", "chalao", "dikhao")):
            sub_tasks.append(SubTask(
                id=f"sub_{uuid4().hex[:8]}",
                goal=f"Desktop action: {goal}",
                agent_id="desktop-operator",
            ))

        # Browser component
        if any(w in lowered for w in ("browse", "website", "page", "tab", "url",
                                       "browser", "internet", "site")):
            sub_tasks.append(SubTask(
                id=f"sub_{uuid4().hex[:8]}",
                goal=f"Browser: {goal}",
                agent_id="browser-operator",
            ))

        # File management component
        if any(w in lowered for w in ("file", "folder", "directory", "list files",
                                       "project files", "dikha")):
            sub_tasks.append(SubTask(
                id=f"sub_{uuid4().hex[:8]}",
                goal=f"Files: {goal}",
                agent_id="file-manager",
            ))

        # Email/communication component
        if any(w in lowered for w in ("email", "mail", "send", "message",
                                       "bhej", "bhejo")):
            sub_tasks.append(SubTask(
                id=f"sub_{uuid4().hex[:8]}",
                goal=f"Communication: {goal}",
                agent_id="communicator",
            ))

        # System monitoring component
        if any(w in lowered for w in ("status", "health", "cpu", "memory", "performance",
                                       "slow", "kaunsa")):
            sub_tasks.append(SubTask(
                id=f"sub_{uuid4().hex[:8]}",
                goal=f"Monitor: {goal}",
                agent_id="monitor",
            ))

        # Analysis component
        if any(w in lowered for w in ("analyze", "analyse", "report", "compare",
                                       "summarize", "summarise", "batao")):
            sub_tasks.append(SubTask(
                id=f"sub_{uuid4().hex[:8]}",
                goal=f"Analysis: {goal}",
                agent_id="analyst",
            ))

        # If no specific components matched, create a single general sub-task
        if not sub_tasks:
            sub_tasks.append(SubTask(
                id=f"sub_{uuid4().hex[:8]}",
                goal=goal,
            ))

        return OrchestratorPlan(goal=goal, sub_tasks=sub_tasks)

    async def execute(
        self,
        goal: str,
        parent_task,
        emit,
        *,
        max_parallel: int = MAX_PARALLEL,
        timeout_seconds: float = 300,
    ) -> OrchestratorResult:
        """Execute a complex goal using multiple agents in parallel.

        1. Decompose the goal
        2. Assign agents
        3. Run in parallel with timeout
        4. Collect results
        """
        started = time.perf_counter()
        plan = self.decompose(goal)
        self._active_missions[plan.goal] = plan

        await self._emit(parent_task.id, EventType.TASK_PROGRESS,
                         f"Orchestrating {len(plan.sub_tasks)} parallel agent(s)",
                         {"goal": goal, "sub_tasks": len(plan.sub_tasks)})

        # Assign agents to sub-tasks
        available_agents = {a.id for a in self.registry.list()
                           if a.status in {AgentStatus.READY, AgentStatus.TESTING}}
        for sub_task in plan.sub_tasks:
            if sub_task.agent_id and sub_task.agent_id in available_agents:
                continue  # already assigned
            agent = self._find_best_agent(sub_task, available_agents)
            if agent:
                sub_task.agent_id = agent.id
                available_agents.discard(agent.id)

        # Run sub-tasks in parallel
        async def run_sub_task(st: SubTask) -> SubTask:
            if not st.agent_id:
                st.status = "skipped"
                st.error = "No matching agent found"
                return st
            st.status = "running"
            st.started_at = time.perf_counter()
            try:
                result, mission = await self.runtime.delegate(
                    parent_task, st.agent_id, st.goal, emit, depth=1,
                )
                st.status = "completed"
                st.completed_at = time.perf_counter()
                st.result = {
                    "response": result.response,
                    "evidence": result.evidence,
                }
                st.evidence = result.evidence or []
            except Exception as exc:
                st.status = "failed"
                st.completed_at = time.perf_counter()
                st.error = str(exc)[:300]
            return st

        # Limit parallelism
        semaphore = asyncio.Semaphore(min(max_parallel, len(plan.sub_tasks)))

        async def limited_run(st: SubTask) -> SubTask:
            async with semaphore:
                return await run_sub_task(st)

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[limited_run(st) for st in plan.sub_tasks]),
                timeout=timeout_seconds,
            )
            plan.sub_tasks = list(results)
        except asyncio.TimeoutError:
            for st in plan.sub_tasks:
                if st.status == "running":
                    st.status = "failed"
                    st.error = "Timed out"

        # Compute final status
        completed = sum(1 for st in plan.sub_tasks if st.status == "completed")
        failed = sum(1 for st in plan.sub_tasks if st.status == "failed")
        total = len(plan.sub_tasks)

        if completed == total:
            status = "completed"
        elif completed > 0:
            status = "partial"
        else:
            status = "failed"

        # Build summary
        summaries = []
        for st in plan.sub_tasks:
            if st.status == "completed" and st.result:
                summaries.append(f"[{st.agent_id}] {st.result.get('response', '')[:200]}")
            elif st.status == "failed":
                summaries.append(f"[{st.agent_id}] FAILED: {st.error[:100]}")

        summary = f"Goal: {goal}\n{'─' * 40}\n" + "\n".join(summaries)

        elapsed_ms = (time.perf_counter() - started) * 1000
        agents_used = [st.agent_id for st in plan.sub_tasks if st.agent_id]

        await self._emit(parent_task.id, EventType.TASK_COMPLETED,
                         f"Multi-agent mission {status}: {completed}/{total} succeeded",
                         {"status": status, "completed": completed, "total": total})

        self._active_missions.pop(plan.goal, None)

        return OrchestratorResult(
            goal=goal,
            status=status,
            sub_tasks=plan.sub_tasks,
            summary=summary,
            total_time_ms=elapsed_ms,
            agents_used=agents_used,
        )

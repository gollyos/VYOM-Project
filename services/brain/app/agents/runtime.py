from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.tasks import Task
from app.skills.executor import SkillExecutor

from .lifecycle import AgentLifecycle
from .registry import AgentRegistry
from .schemas import AgentMission, AgentStatus


class AgentRuntime:
    def __init__(self, registry: AgentRegistry, lifecycle: AgentLifecycle, skills: SkillExecutor):
        self.registry = registry
        self.lifecycle = lifecycle
        self.skills = skills

    async def delegate(self, parent: Task, agent_id: str, goal: str, emit, *, depth: int = 1):
        agent = self.registry.get(agent_id)
        if not agent:
            raise KeyError(agent_id)
        if depth > agent.budget.max_depth:
            raise RuntimeError("Agent delegation depth limit exceeded")
        if agent.status not in {AgentStatus.READY, AgentStatus.TESTING}:
            raise RuntimeError(f"Agent cannot start from status {agent.status.value}")
        mission = AgentMission(id=f"mission_{uuid4().hex}", parent_task_id=parent.id, agent_id=agent_id, goal=goal, depth=depth, status="working")
        agent.status = AgentStatus.WORKING
        agent.current_mission = goal
        self.registry.save(agent)
        await emit("agent_started", f"{agent.name} started a bounded mission", {"agent": agent.model_dump(mode="json"), "mission": mission.model_dump(mode="json")})
        started = time.perf_counter()
        try:
            if not agent.skills:
                raise RuntimeError("Agent has no executable skill")
            result = await self.skills.execute(agent.skills[0], parent, emit)
            passed = bool(result.structured_data.get("verification", {}).get("passed", True))
            if not passed:
                raise RuntimeError("Delegated mission verification failed")
            mission.status = "completed"
            mission.completed_at = datetime.now(timezone.utc)
            mission.evidence = list(result.evidence)
            agent.status = AgentStatus.READY
            agent.performance.missions += 1
            agent.performance.successes += 1
            agent.performance.success_rate = agent.performance.successes / agent.performance.missions
            agent.performance.verification_score = 1
            agent.performance.average_latency_ms = (
                agent.performance.average_latency_ms * (agent.performance.missions - 1) + (time.perf_counter() - started) * 1000
            ) / agent.performance.missions
            agent.current_mission = None
            self.registry.save(agent)
            await emit("agent_completed", f"{agent.name} completed and verified its mission", {"mission": mission.model_dump(mode="json")})
            return result, mission
        except Exception:
            agent.status = AgentStatus.FAILED
            agent.performance.missions += 1
            agent.performance.failures += 1
            agent.performance.success_rate = agent.performance.successes / agent.performance.missions
            self.registry.save(agent)
            raise

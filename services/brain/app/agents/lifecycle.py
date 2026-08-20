from __future__ import annotations

from .registry import AgentRegistry
from .schemas import AgentSpec, AgentStatus


class AgentLifecycle:
    ALLOWED = {
        AgentStatus.CREATED: {AgentStatus.TESTING, AgentStatus.DISABLED, AgentStatus.ARCHIVED},
        AgentStatus.TESTING: {AgentStatus.READY, AgentStatus.FAILED, AgentStatus.DISABLED},
        AgentStatus.READY: {AgentStatus.WORKING, AgentStatus.PAUSED, AgentStatus.DISABLED, AgentStatus.ARCHIVED},
        AgentStatus.WORKING: {AgentStatus.READY, AgentStatus.WAITING, AgentStatus.PAUSED, AgentStatus.FAILED},
        AgentStatus.WAITING: {AgentStatus.WORKING, AgentStatus.PAUSED, AgentStatus.FAILED},
        AgentStatus.PAUSED: {AgentStatus.READY, AgentStatus.DISABLED, AgentStatus.ARCHIVED},
        AgentStatus.FAILED: {AgentStatus.TESTING, AgentStatus.DISABLED, AgentStatus.ARCHIVED},
        AgentStatus.DISABLED: {AgentStatus.TESTING, AgentStatus.ARCHIVED},
        AgentStatus.ARCHIVED: set(),
    }

    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def transition(self, agent_id: str, status: AgentStatus) -> AgentSpec:
        agent = self.registry.get(agent_id)
        if not agent:
            raise KeyError(agent_id)
        if status not in self.ALLOWED[agent.status]:
            raise ValueError(f"Invalid agent lifecycle transition: {agent.status.value} -> {status.value}")
        agent.status = status
        return self.registry.save(agent)

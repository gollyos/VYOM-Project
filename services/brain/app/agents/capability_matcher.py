from __future__ import annotations

from app.capabilities.registry import CapabilityRegistry


class AgentCapabilityMatcher:
    def __init__(self, capabilities: CapabilityRegistry):
        self.capabilities = capabilities

    def missing(self, requested: list[str]) -> list[str]:
        return [capability for capability in requested if not self.capabilities.supports([capability])]

    def suggest(self, goal: str) -> list[str]:
        return [record.capability_id for record in self.capabilities.search(goal, limit=8)]

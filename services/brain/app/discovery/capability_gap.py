from __future__ import annotations

from dataclasses import dataclass, field

from app.capabilities.registry import CapabilityRegistry
from app.capabilities.schemas import CapabilityRecord, CapabilityStatus


@dataclass
class CapabilityGapReport:
    goal: str
    has_existing_capability: bool
    matched: list[CapabilityRecord] = field(default_factory=list)
    reason: str = ""


class CapabilityGapDetector:
    """Goal -> Capability Registry -> existing tool/skill/agent/model?
    VYOM does not immediately reach for a new integration when a reliable
    existing capability already covers the goal."""

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def check(self, goal: str) -> CapabilityGapReport:
        matches = [record for record in self.registry.search(goal) if record.status == CapabilityStatus.AVAILABLE]
        if matches:
            return CapabilityGapReport(goal, True, matches, "An existing available capability already covers this goal.")
        return CapabilityGapReport(goal, False, [], "No existing available capability covers this goal; discovery is required.")

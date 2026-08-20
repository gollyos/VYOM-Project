from __future__ import annotations

import re

from app.schemas.approvals import PermissionLevel

from .registry import SkillRegistry
from .schemas import SkillSpec, SkillStatus


class SkillMatcher:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def match(self, goal: str, limit: int = 5) -> list[SkillSpec]:
        tokens = set(re.findall(r"[a-z0-9]+", goal.lower()))
        ranked: list[tuple[float, SkillSpec]] = []
        for skill in self.registry.list():
            if skill.status not in {SkillStatus.APPROVED, SkillStatus.ACTIVE}:
                continue
            haystack = f"{skill.id} {skill.name} {skill.description} {skill.category}".lower()
            overlap = sum(1 for token in tokens if token in haystack)
            permission_penalty = {
                PermissionLevel.L0: 0.0,
                PermissionLevel.L1: 0.05,
                PermissionLevel.L2: 0.4,
                PermissionLevel.L3: 0.8,
            }[skill.required_permissions]
            total_runs = max(skill.metrics.executions, 1)
            failure_penalty = skill.metrics.failures / total_runs
            cost_penalty = min(skill.budget.max_cost / 10, 1)
            score = (
                overlap * 2
                + skill.success_rate
                + (0.2 if skill.last_used else 0)
                - permission_penalty
                - failure_penalty * 0.5
                - cost_penalty * 0.25
            )
            if overlap:
                ranked.append((score, skill))
        return [skill for _, skill in sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]]

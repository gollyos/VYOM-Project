from __future__ import annotations

from app.schemas.routing import ModelDefinition
from app.schemas.tasks import Task, TaskProfile


COST_SCORE = {"free": 0, "low": 1, "medium": 2, "high": 4, "configurable": 3}
SPEED_SCORE = {"instant": 0, "fast": 1, "balanced": 2, "slow": 4, "configurable": 3}
QUALITY_SCORE = {"basic": 0, "balanced": 1, "high": 2, "premium": 3, "configurable": 1}


class RoutingPolicy:
    def compatible(self, model: ModelDefinition, task: Task, profile: TaskProfile) -> bool:
        if profile.privacy == "highly_sensitive" and model.privacy_policy != "local_only":
            return False
        if not profile.needs.issubset(model.capabilities):
            return False
        if task.requires_tools and not model.supports_tools:
            return False
        return True

    def base_score(self, model: ModelDefinition, task: Task, profile: TaskProfile) -> float:
        score = COST_SCORE.get(model.cost_tier, 3) * 10
        score += SPEED_SCORE.get(model.speed_tier, 3) * (6 if profile.latency_priority == "high" else 2)
        desired_quality = 2 if profile.complexity >= 4 else 1
        quality = QUALITY_SCORE.get(model.quality_tier, 1)
        if quality < desired_quality:
            score += (desired_quality - quality) * 18
        score -= model.priority / 20
        return score


from __future__ import annotations

from app.persistence.model_performance_store import ModelPerformanceStore
from app.providers.base import ProviderRegistry
from app.schemas.routing import RoutingDecision
from app.schemas.tasks import Task, TaskProfile

from .model_registry import ModelRegistry
from .provider_health import ProviderHealth
from .routing_policy import RoutingPolicy


class NoModelAvailableError(RuntimeError):
    pass


class ModelRouter:
    def __init__(
        self,
        registry: ModelRegistry,
        providers: ProviderRegistry,
        performance: ModelPerformanceStore,
        health: ProviderHealth,
        policy: RoutingPolicy | None = None,
    ):
        self.registry = registry
        self.providers = providers
        self.performance = performance
        self.health = health
        self.policy = policy or RoutingPolicy()

    async def route(self, task: Task, profile: TaskProfile) -> RoutingDecision:
        candidates: list[tuple[float, object]] = []
        # Phase 16: historical context-specific performance evidence
        # (learned router). Optional; adds evidence to the existing
        # scoring - it never replaces this router.
        learned_performance = None
        learned_reasons: list[str] = []
        if getattr(self, "learned_router", None) is not None:
            try:
                learned_performance = await self.learned_router.learner.model_performance()
            except Exception:
                learned_performance = None
        for model in self.registry.enabled():
            provider = self.providers.get(model.provider)
            if provider is None or not provider.configured or not self.health.available(model.provider):
                continue
            if not self.policy.compatible(model, task, profile):
                continue
            # Quota spreading: a model that already burned today's
            # free-tier allowance is skipped entirely, and near-exhausted
            # models score worse so traffic fans out across siblings
            # whose allowances are metered separately. Without this every
            # call funneled into the primary until it 429'd, then into
            # the fallback, and the day was over by noon.
            budgeter = getattr(self, "budgeter", None)
            if budgeter is not None:
                if budgeter.exhausted(model.provider, model.model_id):
                    continue
            score = self.policy.base_score(model, task, profile)
            if budgeter is not None:
                score += budgeter.usage_ratio(model.provider, model.model_id) * 15
            statistics = await self.performance.statistics(model.model_id, profile.domain.value)
            if statistics["samples"] >= 3:
                score += (1 - statistics["success_rate"]) * 30
                score += (1 - statistics["verification_score"]) * 12
            if learned_performance is not None:
                bias, bias_reason = self.learned_router.model_bias(
                    model.model_id, profile.domain.value, learned_performance)
                # LearnedRouter.model_bias returns POSITIVE for a
                # historically strong model+domain pair and NEGATIVE for a
                # failure-prone one (see its docstring). This score is a
                # "badness" score where LOWER wins (RoutingPolicy.base_score
                # above), so a good bias must SUBTRACT and a bad bias must
                # ADD — `score += bias` had this inverted, silently
                # rewarding failure-prone models and penalising proven
                # ones, which made the learned-evidence layer actively
                # harmful instead of merely inert.
            role = task.metadata.get("role") or profile.domain.value
            role_model = self.registry.get_for_role(role)
            if role_model is not None and role_model.model_id == model.model_id:
                score -= 60
                learned_reasons.append(f"role-override for '{role}'")

            candidates.append((score, model))

        if not candidates:
            raise NoModelAvailableError(
                f"No configured model can satisfy capabilities: {sorted(profile.needs)}"
            )

        candidates.sort(key=lambda item: (item[0], -item[1].priority))
        primary = candidates[0][1]
        fallbacks = [model.model_id for _, model in candidates[1 : 1 + task.budget.max_fallbacks]]
        verifier = None
        if (profile.complexity >= 4 or profile.criticality in {"high", "critical"}) and len(candidates) > 1:
            verifier = candidates[1][1].model_id

        reason = (
            f"Selected {primary.model_id} because it is the lowest-cost available model "
            f"meeting the {profile.domain.value} task capabilities at complexity {profile.complexity}."
        )
        if learned_reasons:
            suffix = " ".join(learned_reasons[:2])
            reason = reason + " " + suffix
        return RoutingDecision(
            primary_model=primary.model_id,
            primary_provider=primary.provider,
            fallback_models=fallbacks,
            optional_verifier=verifier,
            reason_selected=reason,
            estimated_cost_tier=primary.cost_tier,
            considered_models=[model.model_id for _, model in candidates],
        )


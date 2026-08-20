from __future__ import annotations

import re
from typing import Any

from .schemas import Freshness, ResearchBudget, ResearchDepth, ResearchPlan, SourceType


class QueryPlanner:
    """Deterministic goal -> ResearchPlan decomposition. One search query is
    never treated as equivalent to research; every plan expands a goal into
    multiple bounded questions before any source is fetched."""

    def __init__(
        self,
        budgets: dict[ResearchDepth, ResearchBudget] | None = None,
        default_depth: ResearchDepth = ResearchDepth.STANDARD,
        default_source_diversity: int = 2,
    ):
        self.budgets = budgets or {depth: ResearchBudget() for depth in ResearchDepth}
        self.default_depth = default_depth
        self.default_source_diversity = default_source_diversity

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "QueryPlanner":
        depths = config.get("depths", {})
        budgets: dict[ResearchDepth, ResearchBudget] = {}
        for depth in ResearchDepth:
            values = depths.get(depth.value, {})
            budgets[depth] = ResearchBudget(**values) if values else ResearchBudget()
        default_depth = ResearchDepth(config.get("default_depth", ResearchDepth.STANDARD.value))
        diversity = int(config.get("default_source_diversity", 2))
        return cls(budgets, default_depth, diversity)

    def build_plan(
        self,
        goal: str,
        *,
        depth: ResearchDepth | None = None,
        required_facts: list[str] | None = None,
        preferred_sources: list[SourceType] | None = None,
        freshness_requirement: Freshness = Freshness.UNKNOWN,
    ) -> ResearchPlan:
        resolved_depth = depth or self.default_depth
        if resolved_depth == ResearchDepth.EXHAUSTIVE and not required_facts:
            # Exhaustive research is reserved for explicitly high-value goals;
            # an unscoped goal is downgraded to deep rather than silently
            # burning the largest budget.
            resolved_depth = ResearchDepth.DEEP
        budget = self.budgets.get(resolved_depth, ResearchBudget())
        facts = list(required_facts or [])
        questions = self._decompose(goal, facts)
        return ResearchPlan(
            goal=goal,
            questions=questions,
            required_facts=facts,
            preferred_sources=list(preferred_sources or []),
            source_diversity=self.default_source_diversity,
            freshness_requirement=freshness_requirement,
            depth=resolved_depth,
            budget=budget,
            stop_conditions=[
                f"at least {self.default_source_diversity} independent sources per required fact",
                f"no more than {budget.max_queries} search queries",
                f"no more than {budget.max_sources} sources read",
            ],
        )

    def generate_queries(self, plan: ResearchPlan) -> list[str]:
        return plan.questions[: max(1, plan.budget.max_queries)]

    @staticmethod
    def _decompose(goal: str, required_facts: list[str]) -> list[str]:
        goal_clean = re.sub(r"\s+", " ", goal).strip().rstrip("?.")
        questions = [f"What is the current, authoritative answer to: {goal_clean}?"]
        for fact in required_facts:
            questions.append(f"What is the {fact} relevant to: {goal_clean}?")
        questions.append(f"What do independent sources say that could contradict the primary answer to: {goal_clean}?")
        return questions

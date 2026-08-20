from __future__ import annotations

import random

from .schemas import ExperimentRecord


class SelfEvaluator:
    """Lightweight post-task evaluation (rule 13): deterministic,
    operational questions only — never an LLM call per trivial task.
    Only meaningful tasks (failed, retried, corrected, or novel) are
    flagged for deeper learning."""

    @staticmethod
    def should_evaluate(experience) -> bool:
        if not experience.success:
            return True
        if experience.retries > 0:
            return True
        if experience.user_correction:
            return True
        if experience.verification_score >= 0.5:
            return False  # clean verified success — nothing to learn
        return experience.cost > 0 or experience.latency_ms > 30_000

    @staticmethod
    def evaluate(experience) -> dict:
        questions = {
            "completed": experience.success,
            "verified": experience.verification_score >= 0.5,
            "retries": experience.retries,
            "needed_another_strategy": experience.retries >= 2,
            "corrected_by_user": bool(experience.user_correction),
            "cost": experience.cost,
            "latency_ms": round(experience.latency_ms, 1),
            "tool_or_model_failed": bool(experience.failure_signature),
            "reusable_lesson": bool(experience.failure_signature) or bool(experience.user_correction),
        }
        improvement = None
        if experience.failure_signature:
            improvement = f"apply lesson for failure '{experience.failure_signature}' before similar work"
        elif experience.retries >= 2:
            improvement = "candidate for an alternative strategy experiment"
        elif experience.user_correction:
            improvement = "user correction stored with top learning priority"
        return {"questions": questions, "improvement_hint": improvement}


class ExperimentationBudget:
    """Bounded exploration (rules 28-29): a small configurable
    exploration rate on LOW-RISK choices only (models/tools/
    strategies), capped per day. Consequential L3 actions are never
    experimented with."""

    def __init__(self, *, exploration_rate: float = 0.1, max_experiments: int = 3,
                 rng: random.Random | None = None):
        self.exploration_rate = exploration_rate
        self.max_experiments = max_experiments
        self.rng = rng or random.Random()
        self._today_count = 0

    def should_explore(self, candidates: list[str], *, risk: str = "low") -> str | None:
        if risk in ("high", "l3", "consequential"):
            return None  # never experiment with consequential actions
        if self._today_count >= self.max_experiments or len(candidates) < 2:
            return None
        if self.rng.random() >= self.exploration_rate:
            return None
        self._today_count += 1
        return self.rng.choice(candidates)

    def record(self, experiment: ExperimentRecord) -> ExperimentRecord:
        experiment.active = False
        return experiment


class ImprovementMetrics:
    """Phase 17: measures whether VYOM is ACTUALLY improving — computed
    from real recorded experiences only, never invented. Addresses the
    Phase 17 measurement goals: clarification avoidance via memory
    reuse, tool-selection accuracy, fallback frequency, retries,
    verification success, cost/latency, reuse-vs-adapt decisions, and
    user-correction recurrence."""

    def __init__(self, experience_store, strategy_engine=None):
        self.store = experience_store
        self.strategies = strategy_engine

    async def snapshot(self) -> dict:
        experiences = await self.store._all()
        total = len(experiences)
        if not total:
            return {"total_experiences": 0, "note": "no experiences recorded yet"}

        corrections = [e for e in experiences if e.user_correction]
        correction_texts = [c.user_correction for c in corrections]
        repeated_corrections = len(correction_texts) - len(set(correction_texts))

        extractions = [e for e in experiences if e.task_type == "web_extract"]
        by_tool: dict[str, dict] = {}
        for e in extractions:
            tool = e.tools_used[0] if e.tools_used else "unknown"
            entry = by_tool.setdefault(tool, {"uses": 0, "wins": 0})
            entry["uses"] += 1
            entry["wins"] += 1 if e.success else 0
        tool_accuracy = {
            tool: round(entry["wins"] / entry["uses"], 3) for tool, entry in by_tool.items()
        } if extractions else {}

        missions = [e for e in experiences if e.task_type == "mission"]
        reuse_decisions = {}
        if self.strategies is not None:
            for record in await self.strategies.list("coding") or []:
                reuse_decisions[record.strategy_id] = {
                    "outcomes": len(record.outcomes),
                    "status": record.status.value,
                }

        return {
            "total_experiences": total,
            "success_rate": round(sum(1 for e in experiences if e.success) / total, 3),
            "avg_verification": round(sum(e.verification_score for e in experiences) / total, 3),
            "avg_latency_ms": round(sum(e.latency_ms for e in experiences) / total, 1),
            "total_cost": round(sum(e.cost for e in experiences), 6),
            "avg_retries": round(sum(e.retries for e in experiences) / total, 2),
            "user_corrections": len(corrections),
            "repeated_user_corrections": repeated_corrections,  # recurrence should DECREASE
            "extraction_outcomes": {tool: entry for tool, entry in by_tool.items()},
            "tool_success_by_backend": tool_accuracy,
            "mission_outcomes": {
                "count": len(missions),
                "success_rate": round(sum(1 for m in missions if m.success) / len(missions), 3) if missions else None,
            },
            "strategy_state": reuse_decisions,
            "memory_reuse_experiences": sum(
                1 for e in experiences if e.source == "user_instruction" and e.success
            ),
        }

    @staticmethod
    def delta(before: dict, after: dict) -> dict:
        """Improvement between two snapshots (positive = better)."""
        def rate(snapshot):
            return snapshot.get("success_rate") or 0
        def corrections(snapshot):
            return snapshot.get("repeated_user_corrections") or 0
        return {
            "success_rate_change": round(rate(after) - rate(before), 3),
            "repeated_correction_change": corrections(before) - corrections(after),
            "experience_growth": (after.get("total_experiences") or 0) - (before.get("total_experiences") or 0),
        }

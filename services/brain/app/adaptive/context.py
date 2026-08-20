from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .experience_store import ExperienceStore, similarity
from .schemas import ExperienceContext, ReuseAction


def resolve_reference(text: str, recent_goals: list[str]) -> str | None:
    """Context continuity: 'make a presentation from that' resolves
    'that' to the most recent relevant item when sufficiently
    unambiguous; consequential ambiguity is the caller's decision."""
    lowered = text.lower()
    if "that" not in lowered and "it" not in lowered:
        return None
    return recent_goals[-1] if recent_goals else None


class AdaptiveContextService:
    """World state (rule 23) and continuity (24/25) built by AGGREGATING
    references from existing stores — no new world-model database."""

    def __init__(self, store: ExperienceStore, *, task_store=None, goal_store=None,
                 automation_store=None, device_registry=None):
        self.store = store
        self.task_store = task_store
        self.goal_store = goal_store
        self.automation_store = automation_store
        self.device_registry = device_registry

    async def current_state(self) -> dict:
        state: dict = {"as_of": datetime.now(timezone.utc).isoformat(), "references": {}}
        if self.task_store is not None:
            from app.schemas.tasks import TaskStatus

            recent = await self.task_store.list(limit=50)
            state["references"]["active_tasks"] = [
                {"id": task.id, "goal": task.goal, "status": task.status.value}
                for task in recent if task.status in (TaskStatus.EXECUTING, TaskStatus.QUEUED, TaskStatus.NEEDS_APPROVAL)
            ][:10]
        if self.goal_store is not None:
            goals = await self.goal_store.list()
            state["references"]["goals"] = [goal.title if hasattr(goal, "title") else str(goal) for goal in goals[:10]]
        if self.device_registry is not None:
            state["references"]["devices"] = [
                {"name": node.name, "online": node.online.value} for node in self.device_registry.list()
            ]
        return state

    async def build_experience_context(
        self, goal: str, domain: str, environment: dict[str, str], current_conditions: dict,
        strategy_engine=None,
    ) -> ExperienceContext:
        """The compact planner context: small ranked sets + routing
        hints — never raw history dumps."""
        similar = await self.store.retrieve_similar(goal, domain=domain, environment=environment)
        failures = await self.store.retrieve_failures(goal, domain=domain)
        context = ExperienceContext(
            similar_experiences=[
                {"goal": e.goal[:120], "success": e.success, "verification": e.verification_score,
                 "strategy": e.strategy_used, "models": e.models_used, "tools": e.tools_used,
                 "similarity": score}
                for e, score in similar[:3]
            ],
            relevant_failures=[
                {"goal": e.goal[:120], "signature": e.failure_signature, "reason": (e.failure_reason or "")[:160]}
                for e, _score in failures[:3]
            ],
        )
        if strategy_engine is not None:
            context.reuse_decision = await strategy_engine.decide_reuse(
                goal, domain, environment, current_conditions, self.store,
            )
            if context.reuse_decision and context.reuse_decision.action != ReuseAction.REUSE:
                context.cautions.append("conditions differ from proven runs — adapt, do not replay")
        return context

    async def continue_from_previous_session(self) -> dict:
        """Cross-session continuity: 'continue the work from yesterday'
        retrieves the newest unfinished-looking work and its last
        verified step; continuation itself stays permission-gated."""
        since = datetime.now(timezone.utc) - timedelta(days=2)
        candidates = [e for e in await self.store._all() if e.created_at >= since]
        unfinished = [e for e in candidates if not e.success]
        latest_unfinished = unfinished[0] if unfinished else None
        latest_verified = next((e for e in candidates if e.success and e.verification_score >= 0.5), None)
        return {
            "unfinished": {"goal": latest_unfinished.goal, "failure": latest_unfinished.failure_signature}
            if latest_unfinished else None,
            "last_verified": {"goal": latest_verified.goal, "verification": latest_verified.verification_score}
            if latest_verified else None,
            "can_continue": bool(latest_verified),
            "note": "continuation runs through the normal permission path",
        }

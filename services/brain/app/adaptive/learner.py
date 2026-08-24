from __future__ import annotations

import asyncio
import re

from app.devices.schemas import utc_now
from app.schemas.events import EventType
from app.schemas.tasks import Task, TaskStatus

from .experience_store import ExperienceStore, fingerprint, normalize_failure_signature
from .schemas import EnvironmentChange, Experience, SOURCE_PRIORITY

# Rule 14: event-driven triggers — bounded, no continuous self-thinking loop.
LEARNING_TRIGGERS = {
    EventType.TASK_COMPLETED, EventType.TASK_FAILED, EventType.TASK_CANCELLED,
    EventType.AUTOMATION_COMPLETED, EventType.AUTOMATION_FAILED,
}


class AdaptiveLearner:
    """Turns real outcomes into Experience records, failure signatures,
    user corrections, and routing signals. Deterministic — no LLM call
    ever runs inside learning itself."""

    def __init__(self, store: ExperienceStore, strategy_engine, *, improvement_engine=None):
        self.store = store
        self.strategies = strategy_engine
        self.improvement = improvement_engine  # existing Phase 6 lesson engine

    async def learn_from_task(
        self, task: Task, *, environment: dict[str, str] | None = None,
        conditions: dict | None = None, user_correction: str | None = None,
        satisfaction: str | None = None,
    ) -> Experience:
        success = task.status == TaskStatus.COMPLETED
        verification = task.verification.score if task.verification else 0.0
        error = task.error or ""
        failure_signature = normalize_failure_signature(error) if (not success and error) else None

        experience = Experience(
            task_id=task.id,
            task_type=(task.profile.intent if task.profile else None) or "general",
            task_fingerprint=fingerprint(f"{task.goal} {task.user_request}"),
            context_fingerprint=fingerprint(" ".join(sorted(environment or {})) + " " + task.domain.value),
            goal=task.goal,
            domain=task.domain.value,
            environment=environment or {},
            models_used=[task.assigned_model] if task.assigned_model else [],
            tools_used=list(task.metadata.get("tools_used", []) or []),
            skills_used=list(task.metadata.get("skills_used", []) or []),
            agents_used=list(task.metadata.get("agents_used", []) or []),
            plan_summary=[step.title for step in task.plan[:6]],
            result_summary=(task.result.response[:400] if task.result else error[:400]),
            success=success,
            verification_score=verification,
            latency_ms=((task.completed_at - task.started_at).total_seconds() * 1000)
            if (task.completed_at and task.started_at) else 0.0,
            retries=int(task.metadata.get("retries", 0) or 0),
            failure_type=task.metadata.get("failure_type") if not success else None,
            failure_signature=failure_signature,
            failure_reason=error[:300] if not success else None,
            user_correction=user_correction,
            user_satisfaction_signal=satisfaction,
            conditions=conditions or {},
            confidence=min(0.5 + 0.5 * verification, 1.0) if success else 0.4,
        )
        await self.store.record(experience)
        return experience

    async def record_user_correction(self, *, goal: str, domain: str, correction: str,
                                     affected_strategy: str | None = None) -> Experience:
        """User corrections have the highest learning weight and
        supersede inferred assumptions (rule 11/12)."""
        experience = Experience(
            task_type="user_correction",
            task_fingerprint=fingerprint(goal),
            goal=goal,
            domain=domain,
            user_correction=correction,
            source="user_instruction",
            confidence=1.0,  # explicit statement outranks inference
            result_summary=f"User corrected: {correction}",
        )
        await self.store.record(experience)
        if affected_strategy and self.strategies is not None:
            record = await self.strategies.get(affected_strategy)
            if record is not None:
                record.outcomes.append({"at": utc_now().isoformat(),
                                        "success": False, "correction": correction})
                await self.strategies.save(record)
        return experience

    async def detect_environment_change(self, dimension: str, old_value: str, new_value: str,
                                        impact_domains: list[str] | None = None) -> EnvironmentChange:
        """Register a change (framework version, API, layout, provider,
        market volatility, preferences) — retrieval scoring then decays
        old experience confidence automatically via recency+env match."""
        change = EnvironmentChange(dimension=dimension, old_value=old_value,
                                   new_value=new_value, impact_domains=impact_domains or [])
        connection = self.store.database.require_connection()
        await connection.execute(
            "INSERT INTO environment_changes (change_id, dimension, old_value, new_value, detected_at, change_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (change.change_id, dimension, old_value, new_value, change.detected_at.isoformat(), change.model_dump_json()),
        )
        await connection.commit()
        return change

    # -- routing learning -------------------------------------------------

    async def model_performance(self, days: int = 30) -> dict[str, dict]:
        """Per-model performance by domain/complexity from the existing
        model_performance store — feeds Omni Router context-aware
        preferences instead of one global score."""
        from datetime import datetime, timedelta, timezone

        connection = self.store.database.require_connection()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cursor = await connection.execute(
            "SELECT model, provider, task_domain, complexity, success, verification_score, latency_ms, retries, fallback_used, estimated_cost "
            "FROM model_performance WHERE created_at >= ?",
            (since,),
        )
        rows = await cursor.fetchall()
        aggregate: dict[str, dict] = {}
        for row in rows:
            key = row["model"]
            entry = aggregate.setdefault(key, {"provider": row["provider"], "calls": 0, "wins": 0,
                                               "verification": 0.0, "latency_ms": 0.0, "cost": 0.0,
                                               "retries": 0, "fallbacks": 0, "domains": {}})
            entry["calls"] += 1
            entry["wins"] += int(row["success"])
            entry["verification"] += row["verification_score"]
            entry["latency_ms"] += row["latency_ms"]
            entry["cost"] += float(row["estimated_cost"] or 0.0)
            entry["retries"] += row["retries"]
            entry["fallbacks"] += int(row["fallback_used"])
            domain = entry["domains"].setdefault(row["task_domain"], {"calls": 0, "wins": 0})
            domain["calls"] += 1
            domain["wins"] += int(row["success"])
        for entry in aggregate.values():
            calls = max(entry["calls"], 1)
            entry["success_rate"] = round(entry["wins"] / calls, 3)
            entry["avg_verification"] = round(entry["verification"] / calls, 3)
            entry["avg_latency_ms"] = round(entry["latency_ms"] / calls, 1)
            entry["avg_cost"] = round(entry["cost"] / calls, 6)
            for domain in entry["domains"].values():
                domain["rate"] = round(domain["wins"] / max(domain["calls"], 1), 3)
        return aggregate

    async def tool_performance(self) -> dict[str, dict]:
        """Per-tool success under recorded conditions from experiences
        (e.g. Defuddle vs Playwright by site type)."""
        by_tool: dict[str, dict] = {}
        for experience in await self.store._all():
            site_type = str(experience.conditions.get("site_type", "default"))
            for tool in experience.tools_used:
                entry = by_tool.setdefault(tool, {"uses": 0, "wins": 0, "by_condition": {}})
                entry["uses"] += 1
                entry["wins"] += 1 if experience.success else 0
                bucket = entry["by_condition"].setdefault(site_type, {"uses": 0, "wins": 0})
                bucket["uses"] += 1
                bucket["wins"] += 1 if experience.success else 0
        for entry in by_tool.values():
            entry["rate"] = round(entry["wins"] / max(entry["uses"], 1), 3)
            for bucket in entry["by_condition"].values():
                bucket["rate"] = round(bucket["wins"] / max(bucket["uses"], 1), 3)
        return by_tool

    async def preferred_tool(self, candidates: list[str], conditions: dict) -> tuple[str | None, str]:
        """Evidence-based tool routing: prefer the candidate with the
        best recorded performance under matching conditions."""
        performance = await self.tool_performance()
        condition_key = str(conditions.get("site_type", "default"))
        best, best_rate, evidence = None, None, ""
        for candidate in candidates:
            stats = performance.get(candidate)
            if not stats:
                continue
            bucket = stats["by_condition"].get(condition_key)
            rate, sample = (bucket["rate"], bucket["uses"]) if bucket else (stats["rate"], stats["uses"])
            if sample < 2:
                continue  # don't conclude from a single run
            if best_rate is None or rate > best_rate:
                best, best_rate, evidence = candidate, rate, (
                    f"{candidate}: {rate:.0%} over {sample} recorded uses for {condition_key} content"
                )
        return best, evidence


class AdaptiveLearningBridge:
    """Event-driven learning triggers (rule 14): subscribes to the Brain
    event bus and records experiences after task completion/failure.
    Bounded and failure-safe — learning never takes the runtime down and
    never runs a continuous self-thinking loop.

    This is also the ONE place a real task outcome closes the loop into
    automatic skill promotion: every TASK_COMPLETED experience is
    checked against the auto-promoter (optional; None keeps every
    existing construction path unchanged), and a new taught skill is
    recorded — never auto-activated — the moment the SAME deterministic
    tool sequence for the SAME kind of goal has proven itself enough
    times. SKILL_CREATED is only ever emitted from a REAL SkillSpec the
    registry actually persisted, never from a log line alone."""

    def __init__(self, event_bus, learner: AdaptiveLearner, task_store, *, auto_promoter=None):
        self.event_bus = event_bus
        self.learner = learner
        self.task_store = task_store
        self.auto_promoter = auto_promoter  # SkillAutoPromoter | None, attached post-construction like learned_router
        self._task = None

    def start(self) -> None:
        import asyncio

        self._task = asyncio.create_task(self._loop(), name="vyom-adaptive-learner")

    async def stop(self) -> None:
        import asyncio

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        import asyncio

        subscriber = self.event_bus.subscribe()
        try:
            async for event in subscriber:
                if event.type not in LEARNING_TRIGGERS:
                    continue
                try:
                    task = await self.task_store.get(event.task_id)
                    if task is None:
                        continue
                    experience = await self.learner.learn_from_task(
                        task,
                        environment=task.metadata.get("environment") or {},
                        conditions=task.metadata.get("conditions") or {},
                    )
                    if self.auto_promoter is not None and experience.success:
                        await self._consider_auto_promotion(task, experience)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue  # learning failures are logged nowhere sensitive and never propagate
        except asyncio.CancelledError:
            raise

    async def _consider_auto_promotion(self, task, experience) -> None:
        """Closes ExperienceStore -> SkillBuilder into a real event. Every
        failure here is swallowed by the caller's except — this can never
        take a completed task down."""
        from app.schemas.events import BrainEvent, EventType

        skill = await self.auto_promoter.consider(
            task_type=experience.task_type,
            domain=experience.domain,
            tools_used=experience.tools_used,
        )
        if skill is None:
            return
        await self.event_bus.publish(BrainEvent(
            task_id=task.id,
            type=EventType.SKILL_CREATED,
            human_readable_message=(
                f"Auto-taught a new skill '{skill.name}' after repeated verified successes"
            ),
            structured_payload={"skill_id": skill.id, "version": skill.version, "category": skill.category},
        ))

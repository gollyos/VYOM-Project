from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.tasks import Task, TaskStatus


@dataclass
class PerformanceSnapshot:
    """A point-in-time view of VYOM's health."""
    timestamp: str
    total_tasks: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    avg_tokens_per_task: float = 0.0
    total_cost: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    hallucination_detections: int = 0
    correction_count: int = 0
    top_failure_reasons: list[dict] = field(default_factory=list)
    top_slow_intents: list[dict] = field(default_factory=list)
    health_score: float = 0.0  # 0-100


@dataclass
class ImprovementArea:
    """A specific area where VYOM can improve."""
    category: str  # performance | reliability | accuracy | coverage
    area: str
    description: str
    severity: str  # low | medium | high | critical
    suggestion: str
    evidence: str = ""


@dataclass
class HealthReport:
    """Complete self-assessment of VYOM's current state."""
    snapshot: PerformanceSnapshot
    improvements: list[ImprovementArea]
    recent_failures: list[dict]
    recommendations: list[str]
    self_awareness_notes: list[str]  # What VYOM knows about its own limitations


class SelfMonitor:
    """Tracks VYOM's own performance and identifies improvement areas.

    This is VYOM's self-awareness layer — it knows what it's good at,
    what it struggles with, and what needs improvement. Unlike external
    monitoring, this runs inside VYOM's own runtime and can influence
    future behavior.
    """

    def __init__(self, task_store=None, experience_store=None, data_dir: Path | None = None):
        self.task_store = task_store
        self.experience_store = experience_store
        self.data_dir = data_dir or Path("data/monitoring")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._correction_log: list[dict] = []
        self._hallucination_log: list[dict] = []

    def record_correction(self, task_id: str, correction: str, original_answer: str) -> None:
        """Log when a user corrects VYOM's answer — the primary signal for improvement."""
        self._correction_log.append({
            "task_id": task_id,
            "correction": correction,
            "original": original_answer[:200],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def record_hallucination(self, task_id: str, description: str, evidence: str) -> None:
        """Log when VYOM detects it may have hallucinated (invented facts)."""
        self._hallucination_log.append({
            "task_id": task_id,
            "description": description,
            "evidence": evidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def get_snapshot(self, hours: int = 24) -> PerformanceSnapshot:
        """Compute a performance snapshot from recent tasks."""
        snapshot = PerformanceSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if self.task_store is None:
            return snapshot

        try:
            recent = await self.task_store.list_recent(limit=200)
        except Exception:
            return snapshot

        if not recent:
            return snapshot

        snapshot.total_tasks = len(recent)
        latencies = []
        tokens = []

        failure_reasons: dict[str, int] = {}
        intent_latencies: dict[str, list[float]] = {}

        for task in recent:
            status = task.status
            if status == TaskStatus.COMPLETED:
                snapshot.completed += 1
            elif status == TaskStatus.FAILED:
                snapshot.failed += 1
                reason = (task.error or "unknown")[:100]
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            elif status == TaskStatus.CANCELLED:
                snapshot.cancelled += 1

            # Latency
            if task.started_at and task.completed_at:
                latency = (task.completed_at - task.started_at).total_seconds() * 1000
                latencies.append(latency)
                intent = task.profile.intent if task.profile else "unknown"
                intent_latencies.setdefault(intent, []).append(latency)

            # Tokens
            if task.result and task.result.usage:
                tokens.append(task.result.usage.total_tokens or 0)

        if snapshot.total_tasks > 0:
            snapshot.success_rate = snapshot.completed / snapshot.total_tasks

        if latencies:
            snapshot.avg_latency_ms = sum(latencies) / len(latencies)

        if tokens:
            snapshot.avg_tokens_per_task = sum(tokens) / len(tokens)

        # Top failure reasons
        snapshot.top_failure_reasons = [
            {"reason": reason, "count": count}
            for reason, count in sorted(failure_reasons.items(), key=lambda x: -x[1])[:5]
        ]

        # Top slow intents
        snapshot.top_slow_intents = [
            {"intent": intent, "avg_ms": sum(lats) / len(lats), "count": len(lats)}
            for intent, lats in sorted(intent_latencies.items(), key=lambda x: -sum(x[1]) / len(x[1]))[:5]
        ]

        # Hallucination and correction counts
        snapshot.hallucination_detections = len(self._hallucination_log)
        snapshot.correction_count = len(self._correction_log)

        # Health score (0-100)
        snapshot.health_score = self._compute_health_score(snapshot)

        return snapshot

    def _compute_health_score(self, snap: PerformanceSnapshot) -> float:
        """Compute a 0-100 health score from metrics."""
        score = 100.0

        # Penalize low success rate
        if snap.total_tasks > 0:
            if snap.success_rate < 0.5:
                score -= 30
            elif snap.success_rate < 0.8:
                score -= 15
            elif snap.success_rate < 0.95:
                score -= 5

        # Penalize high latency
        if snap.avg_latency_ms > 10000:
            score -= 20
        elif snap.avg_latency_ms > 5000:
            score -= 10
        elif snap.avg_latency_ms > 2000:
            score -= 5

        # Penalize hallucinations
        score -= min(20, snap.hallucination_detections * 5)

        # Penalize corrections
        score -= min(15, snap.correction_count * 3)

        return max(0, min(100, score))

    async def identify_improvements(self, snapshot: PerformanceSnapshot | None = None) -> list[ImprovementArea]:
        """Analyze performance and suggest specific improvements."""
        if snapshot is None:
            snapshot = await self.get_snapshot()

        improvements = []

        # Check success rate
        if snapshot.success_rate < 0.8 and snapshot.total_tasks > 5:
            improvements.append(ImprovementArea(
                category="reliability",
                area="Task completion rate",
                description=f"Only {snapshot.success_rate:.0%} of tasks complete successfully",
                severity="high",
                suggestion="Review top failure reasons and add missing tool capabilities or fix classifier gaps",
                evidence=f"{snapshot.failed}/{snapshot.total_tasks} tasks failed",
            ))

        # Check latency
        if snapshot.avg_latency_ms > 5000:
            improvements.append(ImprovementArea(
                category="performance",
                area="Response latency",
                description=f"Average response time is {snapshot.avg_latency_ms:.0f}ms",
                severity="medium",
                suggestion="Consider caching deterministic results, reducing model calls, or parallelizing independent steps",
                evidence=f"Average: {snapshot.avg_latency_ms:.0f}ms",
            ))

        # Check hallucinations
        if snapshot.hallucination_detections > 0:
            improvements.append(ImprovementArea(
                category="accuracy",
                area="Hallucination rate",
                description=f"{snapshot.hallucination_detections} potential hallucination(s) detected",
                severity="critical",
                suggestion="Strengthen grounding: require tool evidence before responding, add fact-checking step",
                evidence=f"{snapshot.hallucination_detections} detections",
            ))

        # Check corrections
        if snapshot.correction_count > 3:
            improvements.append(ImprovementArea(
                category="accuracy",
                area="User correction frequency",
                description=f"Users corrected VYOM {snapshot.correction_count} times recently",
                severity="high",
                suggestion="Analyze correction patterns to find systematic knowledge gaps or classifier errors",
                evidence=f"{snapshot.correction_count} corrections",
            ))

        # Check top failure reasons for patterns
        for failure in snapshot.top_failure_reasons[:3]:
            if failure["count"] >= 3:
                improvements.append(ImprovementArea(
                    category="reliability",
                    area=f"Repeated failure: {failure['reason'][:50]}",
                    description=f"This failure occurred {failure['count']} times",
                    severity="medium",
                    suggestion="Investigate root cause and add specific handling for this failure mode",
                    evidence=failure["reason"],
                ))

        # Self-awareness: note known limitations
        if not improvements:
            improvements.append(ImprovementArea(
                category="coverage",
                area="General improvement",
                description="No critical issues detected",
                severity="low",
                suggestion="Continue monitoring; consider expanding tool coverage or adding new agent capabilities",
            ))

        return improvements

    async def get_health_report(self) -> HealthReport:
        """Full self-assessment including what VYOM knows about its own limits."""
        snapshot = await self.get_snapshot()
        improvements = await self.identify_improvements(snapshot)

        # Recent failures
        recent_failures = []
        if self.task_store:
            try:
                tasks = await self.task_store.list_recent(limit=50)
                for t in tasks:
                    if t.status == TaskStatus.FAILED:
                        recent_failures.append({
                            "task_id": t.id,
                            "goal": t.goal[:100],
                            "error": (t.error or "unknown")[:200],
                            "timestamp": t.created_at.isoformat() if t.created_at else "",
                        })
            except Exception:
                pass

        # Self-awareness notes
        self_notes = [
            "I am best at tasks that use my registered tools (desktop, browser, files, memory).",
            "I struggle with tasks that require real-time external data I don't have access to.",
            "Compound goals (X and Y) work best when each part maps to a distinct tool.",
            "I learn from user corrections — telling me I was wrong helps me improve.",
            "My memory can sometimes surface stale information; I try to use the most recent fact.",
        ]

        recommendations = [
            imp.suggestion for imp in improvements[:5]
        ]

        return HealthReport(
            snapshot=snapshot,
            improvements=improvements,
            recent_failures=recent_failures,
            recommendations=recommendations,
            self_awareness_notes=self_notes,
        )

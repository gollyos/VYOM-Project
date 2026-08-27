from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.diagnostics.doctor import VYOMDoctor
from app.diagnostics.security_audit import SecurityAudit
from app.observability.cost_metrics import CostTracker
from app.schemas.results import ExecutionResult
from app.schemas.tasks import Task, TaskProfile

EventEmitter = Callable[[str, str, dict], Awaitable[None]]


def _frame(x: float, y: float, width: float, layer: int | None = None) -> dict:
    frame = {"x": x, "y": y, "width": width}
    if layer:
        frame["layer"] = layer
    return frame


def _composition(identifier: str, mode: str, label: str, summary: str, objects: list[dict]) -> dict:
    states = ["Executing", "Verifying", "Completed"]
    sequence = [
        {"id": f"reveal-{index}", "label": obj.get("eyebrow", obj["title"]), "atMs": index * 280,
         "state": states[min(index, len(states) - 1)], "objectIds": [obj["id"]]}
        for index, obj in enumerate(objects)
    ]
    return {
        "schemaVersion": 1, "id": identifier, "mode": mode, "label": label,
        "summary": summary, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "objects": objects, "sequence": sequence,
    }


class Phase13Engine:
    """Production-hardening deterministic delegate: "VYOM, run
    diagnostics", "run security audit", "How much did VYOM cost
    today?", and "Why isn't VYOM working?" — answered from real
    diagnostics/observability state with summoned Composer surfaces,
    never a dashboard."""

    INTENTS = {"run_diagnostics", "security_audit", "cost_query", "troubleshoot", "explain_decision"}

    def __init__(self, doctor: VYOMDoctor, security_audit: SecurityAudit, cost_tracker: CostTracker,
                 health_aggregator=None, experience_store=None, policy_engine=None):
        self.doctor = doctor
        self.security_audit = security_audit
        self.cost_tracker = cost_tracker
        self.health_aggregator = health_aggregator
        self.experience_store = experience_store
        self.policy_engine = policy_engine

    def supports(self, intent: str) -> bool:
        return intent in self.INTENTS

    async def execute(self, task: Task, profile: TaskProfile, emit: EventEmitter) -> ExecutionResult:
        intent = profile.intent
        if intent == "run_diagnostics":
            return await self._diagnostics(task)
        if intent == "security_audit":
            return self._security_audit(task)
        if intent == "cost_query":
            return await self._cost(task)
        if intent == "troubleshoot":
            return await self._troubleshoot(task)
        if intent == "explain_decision":
            return await self._explain_decision(task)
        raise RuntimeError(f"Unsupported Phase 13 intent: {intent}")

    async def _diagnostics(self, task: Task) -> ExecutionResult:
        report = await self.doctor.run()
        rows = [[check["name"], check["status"], check["explanation"][:80]] for check in report["checks"][:12]]
        tone = "verified" if report["overall"] == "PASS" else "attention"
        statement = (
            f"Diagnostics {report['overall']}: {report['counts']['PASS']} pass, "
            f"{report['counts']['WARNING']} warning, {report['counts']['FAIL']} fail."
        )
        objects = [
            {
                "id": "doctor-summary", "type": "verified-result", "title": "VYOM Doctor",
                "eyebrow": "Diagnostics", "tone": tone, "frame": _frame(15, 12, 40), "statement": statement,
                "evidence": [f"duration:{report['duration_ms']}ms"], "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": "doctor-checks", "type": "comparison-table", "title": "Check results",
                "eyebrow": f"{len(report['checks'])} checks", "frame": _frame(58, 16, 34, 2),
                "headers": ["Check", "Status", "Result"],
                "rows": rows,
            },
        ]
        if report["recommendations"]:
            objects.append({
                "id": "doctor-repairs", "type": "evidence-card-group", "title": "Recommended repairs",
                "eyebrow": f"{len(report['recommendations'])} recommendation(s)", "frame": _frame(15, 62, 46, 3),
                "cards": [
                    {"statement": f"{item['action'].replace('_', ' ').title()}: {item['explanation']}", "confidence": 0.9, "sources": [item["check"]]}
                    for item in report["recommendations"][:4]
                ],
            })
        return ExecutionResult(
            response=statement, structured_data={"overall": report["overall"], "counts": report["counts"]},
            ui_composition=_composition(f"doctor-{task.id}", "brain-context", "Diagnostics", statement, objects),
            evidence=[f"doctor:{report['overall']}"],
        )

    def _security_audit(self, task: Task) -> ExecutionResult:
        report = self.security_audit.run()
        statement = (
            f"Security audit {report['overall']}: "
            + ", ".join(f"{count} {severity}" for severity, count in report["counts"].items() if count)
            + "."
        )
        objects = [
            {
                "id": "audit-summary", "type": "verified-result", "title": "Security audit",
                "eyebrow": "Posture", "tone": "verified" if report["overall"] in ("informational", "low") else "attention",
                "frame": _frame(15, 12, 40), "statement": statement,
                "evidence": [f"{f['severity']}:{f['area']}" for f in report["findings"][:5]],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": "audit-findings", "type": "evidence-card-group", "title": "Findings",
                "eyebrow": f"{len(report['findings'])} finding(s)", "frame": _frame(58, 16, 34, 2),
                "cards": [
                    {"statement": f"{finding['severity'].upper()} - {finding['area']}: {finding['evidence']}", "confidence": 0.9, "sources": ["security-audit"]}
                    for finding in report["findings"][:5]
                ],
            },
        ]
        return ExecutionResult(
            response=statement, structured_data={"overall": report["overall"], "counts": report["counts"]},
            ui_composition=_composition(f"audit-{task.id}", "brain-context", "Security audit", statement, objects),
            evidence=[f"audit:{report['overall']}"],
        )

    async def _cost(self, task: Task) -> ExecutionResult:
        summary = await self.cost_tracker.summary(days=1)
        live = summary["live"]
        cost_value = round(live["cost"] + summary.get("persisted_estimated_cost", 0.0), 4)
        if cost_value == 0:
            statement = "No model cost has been tracked today — only the deterministic local runtime has run."
        else:
            statement = (
                f"Tracked model usage today: {live['calls']} call(s), {cost_value:.4f} estimated cost"
                f" across {len(summary['by_provider'])} provider(s)."
            )
        provider_rows = [
            [name, str(data["calls"]), f"${data['cost']:.4f}"]
            for name, data in summary["by_provider"].items()
        ] or [["no providers used", "0", "$0.0000"]]
        objects = [
            {
                "id": "cost-total", "type": "metric", "title": "Model cost", "eyebrow": "Cost observability",
                "frame": _frame(15, 12, 30), "label": "Today", "value": f"${cost_value:.4f}",
                "caption": f"{live['calls']} tracked call(s)",
            },
            {
                "id": "cost-providers", "type": "comparison-table", "title": "By provider",
                "eyebrow": "Today", "frame": _frame(50, 16, 40, 2),
                "headers": ["Provider", "Calls", "Cost"],
                "rows": provider_rows,
            },
        ]
        return ExecutionResult(
            response=statement, structured_data=summary,
            ui_composition=_composition(f"cost-{task.id}", "brain-context", "Cost", statement, objects),
            evidence=[f"cost:{cost_value}"],
        )

    async def _troubleshoot(self, task: Task) -> ExecutionResult:
        health = await self.health_aggregator.assess() if self.health_aggregator else {"overall": "unknown", "components": {}}
        failing = [name for name, state in health["components"].items() if state in ("degraded", "offline")]
        if not failing:
            statement = "All monitored components are healthy; nothing is currently failing."
        else:
            statement = f"VYOM is running with these layers not fully healthy: {', '.join(failing)}. Local core commands remain available."
        report = await self.doctor.run()
        relevant = [item for item in report["recommendations"] if item["check"].split(":")[0].replace("_", "-") in
                    [name.replace("_", "-") for name in failing]] or report["recommendations"][:2]
        objects = [
            {
                "id": "health-summary", "type": "verified-result", "title": "System health",
                "eyebrow": "Troubleshooting", "tone": "verified" if not failing else "attention",
                "frame": _frame(15, 12, 42), "statement": statement,
                "evidence": [f"{name}:{state}" for name, state in list(health["components"].items())[:6]],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ]
        if relevant:
            objects.append({
                "id": "health-actions", "type": "evidence-card-group", "title": "What to do",
                "eyebrow": "Recommendations", "frame": _frame(60, 18, 32, 2),
                "cards": [
                    {"statement": f"{item['action'].replace('_', ' ').title()}: {item['explanation']}", "confidence": 0.9, "sources": [item["check"]]}
                    for item in relevant[:3]
                ],
            })
        return ExecutionResult(
            response=statement, structured_data={"overall": health["overall"], "failing": failing},
            ui_composition=_composition(f"health-{task.id}", "brain-context", "Health", statement, objects),
            evidence=[f"health:{health['overall']}"],
        )

    async def _explain_decision(self, task: Task) -> ExecutionResult:
        """'Why did you choose this approach?' — a concise operational
        explanation from the latest recorded experience and evidence.
        No hidden chain-of-thought exists to reveal."""
        if self.experience_store is None:
            statement = "Decision explanations need the adaptive experience store, which is not available."
            return ExecutionResult(response=statement, structured_data={})
        experiences = await self.experience_store._all()
        latest = experiences[0] if experiences else None
        if latest is None:
            statement = "No prior experience applies yet — this choice came from current conditions and default policy."
        else:
            if latest.user_correction:
                evidence = f"a stored user correction overrides inference: \"{latest.user_correction}\""
            elif latest.success and latest.verification_score >= 0.5:
                evidence = (f"a verified similar outcome exists ({latest.verification_score:.0%} verification"
                            + (f", tools {', '.join(latest.tools_used)}" if latest.tools_used else "") + ")")
            elif latest.failure_signature:
                evidence = f"a recorded failure pattern '{latest.failure_signature}' is being avoided"
            else:
                evidence = "the most similar recorded run was inconclusive, so conditions were re-evaluated"
            statement = f"I chose the current approach because {evidence}."
        objects = [{
            "id": "decision", "type": "verified-result", "title": "Decision reasoning",
            "eyebrow": "Explanation", "tone": "verified", "frame": _frame(20, 16, 46),
            "statement": statement,
            "evidence": ["operational evidence only", "no hidden reasoning stored"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
        return ExecutionResult(
            response=statement,
            structured_data={"latest_experience": latest.experience_id} if latest else {},
            ui_composition=_composition(f"explain-{task.id}", "brain-context", "Decision", statement, objects),
            evidence=["explanation:operational"],
        )


DiagnosticsObservabilityEngine = Phase13Engine
__all__ = ["Phase13Engine", "DiagnosticsObservabilityEngine"]

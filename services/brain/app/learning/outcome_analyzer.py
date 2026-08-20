from __future__ import annotations

from app.schemas.tasks import Task


class OutcomeAnalyzer:
    def analyze(self, task: Task) -> dict:
        verification = task.verification
        return {
            "worth_remembering": bool(verification and verification.passed and task.complexity >= 2),
            "success": bool(verification and verification.passed),
            "verification_score": verification.score if verification else 0,
            "domain": task.domain.value,
            "intent": task.profile.intent if task.profile else "unknown",
            "evidence": list(verification.evidence) if verification else [],
        }

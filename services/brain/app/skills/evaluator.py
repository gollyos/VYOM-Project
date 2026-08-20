from __future__ import annotations

from app.schemas.approvals import PermissionLevel

from .schemas import SkillEvaluation, SkillSpec, SkillStatus


class SkillEvaluator:
    def apply(self, skill: SkillSpec, evaluation: SkillEvaluation, *, user_approved: bool = False) -> SkillSpec:
        if not evaluation.passed:
            skill.status = SkillStatus.FAILED
            skill.metrics.failures += 1
            skill.metrics.common_failure_reason = ", ".join(evaluation.errors)
            return skill
        if skill.required_permissions in {PermissionLevel.L2, PermissionLevel.L3} and not user_approved:
            skill.status = SkillStatus.TESTING
            return skill
        skill.status = SkillStatus.ACTIVE
        skill.metrics.verification_score = evaluation.score
        return skill

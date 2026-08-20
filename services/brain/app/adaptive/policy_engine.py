from __future__ import annotations

from .schemas import Experience, SOURCE_PRIORITY

# Rule 19: what adaptive learning may and may never touch.
MUTABLE_SIGNALS = {
    "model_preference", "tool_preference", "strategy_ranking", "skill_ranking",
    "agent_selection", "workflow_ordering", "memory_confidence", "strategy_status",
}
PROTECTED_SIGNALS = {
    "security_boundary", "permission_engine", "l2_l3_requirements", "secret_store",
    "authentication", "risk_hard_limits", "system_safety", "production_bootstrap",
}
# Rule 35: adaptive learning must never autonomously INCREASE these.
RISK_INCREASE_FIELDS = {
    "max_risk_per_trade", "max_daily_loss", "max_drawdown", "leverage", "financial_authority",
}


class ProtectedPolicyError(Exception):
    pass


class AdaptivePolicyEngine:
    """Gatekeeper for every adaptation. Learning may adjust preferences
    and rankings; security, permissions, secrets, and risk hard limits
    are not learnable. Risk increases always require explicit user
    approval — the engine rejects them outright for auto-application."""

    def may_modify(self, signal: str) -> bool:
        return signal in MUTABLE_SIGNALS

    def is_protected(self, signal: str) -> bool:
        return signal in PROTECTED_SIGNALS or signal not in MUTABLE_SIGNALS

    def apply(self, signal: str, proposed_change: dict) -> dict:
        if self.is_protected(signal):
            raise ProtectedPolicyError(
                f"Adaptive learning cannot modify protected signal '{signal}'"
            )
        return {"signal": signal, "change": proposed_change, "applied": True}

    def apply_risk_change(self, field: str, current: float, proposed: float) -> dict:
        if field not in RISK_INCREASE_FIELDS:
            return {"field": field, "applied": True, "change": proposed}
        if proposed > current:
            raise ProtectedPolicyError(
                f"Risk limit '{field}' can never be autonomously increased "
                f"({current} -> {proposed}); user approval is mandatory"
            )
        return {"field": field, "applied": True, "change": proposed,
                "note": "decrease applied autonomously; increases require user approval"}

    @staticmethod
    def resolve_conflict(records: list[Experience]) -> Experience | None:
        """Conflicting knowledge is resolved by source priority, then
        recency: a verified user instruction outranks model inference
        regardless of age (rule 12)."""
        if not records:
            return None
        return max(records, key=lambda record: (
            SOURCE_PRIORITY.get(record.source, 1), record.created_at.isoformat()
        ))

    @staticmethod
    def explain(choice: dict) -> str:
        """Concise operational explanation for 'Why did you choose
        this approach?' — evidence-based, no hidden reasoning."""
        subject = choice.get("subject", "this approach")
        evidence = choice.get("evidence", "")
        return f"I chose {subject}. {evidence}" if evidence else f"I chose {subject} based on current conditions; no conflicting experience applied."

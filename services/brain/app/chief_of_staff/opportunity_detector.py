from __future__ import annotations

from pydantic import BaseModel, Field


class OpportunityItem(BaseModel):
    type: str  # "delegatable_work" | "automation_opportunity" | "free_time" | "goal_acceleration"
    description: str
    suggested_action: str
    evidence: list[str] = Field(default_factory=list)


class OpportunityDetector:
    """Identifies free time, delegatable work, and repeated-behavior
    automation opportunities from real observed signals — a repeated
    manual action is only flagged once it has actually recurred a
    minimum number of times (rule 66/67), never after a single instance."""

    def __init__(self, *, repeated_action_threshold: int = 3):
        self.repeated_action_threshold = repeated_action_threshold

    def detect(
        self, *, available_free_minutes: float = 0.0, delegatable_agent_work: list[str] | None = None,
        repeated_manual_actions: dict[str, int] | None = None,
    ) -> list[OpportunityItem]:
        opportunities: list[OpportunityItem] = []

        if available_free_minutes >= 30 and delegatable_agent_work:
            for item in delegatable_agent_work[:2]:
                opportunities.append(OpportunityItem(
                    type="delegatable_work", description=item,
                    suggested_action=f"Delegate to the relevant agent while you have {available_free_minutes:.0f} free minute(s)",
                    evidence=[f"free_minutes:{available_free_minutes}"],
                ))

        for label, count in (repeated_manual_actions or {}).items():
            if count >= self.repeated_action_threshold:
                opportunities.append(OpportunityItem(
                    type="automation_opportunity",
                    description=f"'{label}' has been performed manually {count} time(s) recently",
                    suggested_action="Consider converting this into an automation (schedule/permissions/cost shown before enabling)",
                    evidence=[f"observed_count:{count}"],
                ))

        return opportunities

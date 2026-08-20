from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import Commitment, PersonalProfile

PERSONAL_ONLY_KEYS = {
    "personal_priorities", "quiet_hours", "focus_preferences", "energy_preference",
    "habit_summary", "goal_summary", "personal_commitments", "work_cutoff_time",
    "daily_energy_preferences", "portfolio", "paper_trading",
}


class PersonalContext(BaseModel):
    """The bounded bundle Chief-of-Staff/daily-planning code reads from —
    never client/business output. See rule 52/53: work and personal
    priorities are unified here, but this bundle itself never crosses into
    a client-facing composition."""

    timezone: str
    working_hours: dict
    quiet_hours: dict
    energy_preference: str | None = None
    open_commitment_count: int = 0
    overdue_commitment_count: int = 0
    top_commitments: list[str] = Field(default_factory=list)
    goal_summaries: list[str] = Field(default_factory=list)
    habit_summaries: list[str] = Field(default_factory=list)


class PersonalContextBuilder:
    def build(
        self,
        profile: PersonalProfile,
        *,
        timezone_name: str,
        working_hours: dict,
        quiet_hours: dict,
        commitments: list[Commitment],
        goal_summaries: list[str] | None = None,
        habit_summaries: list[str] | None = None,
    ) -> PersonalContext:
        energy_field = profile.get("energy_preference")
        overdue = [c for c in commitments if c.status.value == "overdue"]
        open_items = [c for c in commitments if c.status.value in {"open", "overdue"}]
        top = sorted(open_items, key=lambda c: (c.deadline is None, c.deadline))[:5]
        return PersonalContext(
            timezone=timezone_name, working_hours=working_hours, quiet_hours=quiet_hours,
            energy_preference=(energy_field.value if energy_field else None),
            open_commitment_count=len(open_items), overdue_commitment_count=len(overdue),
            top_commitments=[c.description for c in top],
            goal_summaries=goal_summaries or [], habit_summaries=habit_summaries or [],
        )


def strip_personal_for_client_context(data: dict) -> dict:
    """Defensive filter for any code path that might compose client/business
    output from a shared context bundle (rule 53). Removes personal-only
    keys; nothing about client/CRM data is touched."""
    return {key: value for key, value in data.items() if key not in PERSONAL_ONLY_KEYS}

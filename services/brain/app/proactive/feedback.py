from __future__ import annotations

from enum import Enum

from .suppression import ProactiveSuggestionStore


class SuggestionOutcome(str, Enum):
    SURFACED = "surfaced"
    DISMISSED = "dismissed"
    OPENED = "opened"
    ACTED_ON = "acted_on"
    SNOOZED = "snoozed"


class FeedbackTracker:
    """Tracks dismissed/opened/acted_on/snoozed outcomes (rule 36) to
    improve future timing/relevance. This tuning is advisory only — it
    never suppresses a genuinely critical notification; that gate lives
    in `timing.py`/`relevance.py` and always lets `critical` through
    regardless of past feedback."""

    def __init__(self, store: ProactiveSuggestionStore):
        self.store = store

    async def record(self, suggestion_id: str, outcome: SuggestionOutcome) -> None:
        await self.store.update_outcome(suggestion_id, outcome.value)

    async def dismissal_rate(self, title: str) -> float | None:
        outcomes = await self.store.outcomes_for_title(title)
        if not outcomes:
            return None
        dismissed = sum(1 for outcome in outcomes if outcome == SuggestionOutcome.DISMISSED.value)
        return round(dismissed / len(outcomes), 4)

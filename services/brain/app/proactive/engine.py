from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from .relevance import RelevanceChecker
from .rules import ProactiveLevel, ProactiveRules, ProactiveSuggestion
from .suppression import ProactiveSuggestionStore, SuppressionEngine
from .timing import TimingEvaluator


class ProactiveDecision(BaseModel):
    surfaced: bool
    reason: str
    suggestion: ProactiveSuggestion


class ProactiveEngine:
    """The full rule-31 gate: important? actionable? good timing? not
    already surfaced? not auto-handleable? benefit exceeds interruption
    cost? Only when every applicable check passes does a suggestion
    actually surface (rule 31/65) — this is enforced in code here, not
    left to prompt instructions."""

    def __init__(self, rules: ProactiveRules, store: ProactiveSuggestionStore):
        self.rules = rules
        self.store = store
        self.relevance = RelevanceChecker()
        self.timing = TimingEvaluator()
        self.suppression = SuppressionEngine(store)

    async def evaluate(
        self, suggestion: ProactiveSuggestion, *, level: ProactiveLevel | None = None, quiet_hours: dict | None = None,
        focus_active: bool = False, explicit_quiet_until: datetime | None = None, now: datetime | None = None,
    ) -> ProactiveDecision:
        active_level = level or self.rules.default_level
        current_time = now or datetime.now(timezone.utc)

        relevance_result = self.relevance.check(suggestion, self.rules, active_level)
        if not relevance_result.allowed:
            return ProactiveDecision(surfaced=False, reason=relevance_result.reason, suggestion=suggestion)

        if self.rules.require_good_timing:
            timing_result = self.timing.evaluate(suggestion, now=current_time, quiet_hours=quiet_hours, focus_active=focus_active, explicit_quiet_until=explicit_quiet_until)
            if not timing_result.allowed:
                return ProactiveDecision(surfaced=False, reason=timing_result.reason, suggestion=suggestion)

        if self.rules.require_not_already_surfaced:
            suppression_result = await self.suppression.check(
                suggestion, duplicate_window_hours=self.rules.duplicate_window_hours, max_low_priority_per_day=self.rules.max_low_priority_per_day,
            )
            if not suppression_result.allowed:
                return ProactiveDecision(surfaced=False, reason=suppression_result.reason, suggestion=suggestion)

        await self.store.record_surfaced(suggestion)
        return ProactiveDecision(surfaced=True, reason="Passed the full proactive relevance gate", suggestion=suggestion)

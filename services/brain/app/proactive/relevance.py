from __future__ import annotations

from .rules import ProactiveLevel, ProactiveRules, ProactiveSuggestion


class RelevanceResult:
    def __init__(self, allowed: bool, reason: str):
        self.allowed = allowed
        self.reason = reason


class RelevanceChecker:
    """Is it important? Is it actionable? Can VYOM handle it
    automatically? — the content-relevance third of the rule-31 gate.
    Timing and suppression are separate checks (`timing.py`,
    `suppression.py`) so each failure reason stays legible."""

    def check(self, suggestion: ProactiveSuggestion, rules: ProactiveRules, level: ProactiveLevel) -> RelevanceResult:
        if rules.suppress_if_auto_handleable and suggestion.auto_handleable:
            return RelevanceResult(False, "VYOM can handle this automatically; no interruption needed")
        if rules.require_important and suggestion.importance < rules.min_importance_for(level):
            return RelevanceResult(False, f"Importance {suggestion.importance} is below the '{level.value}' threshold ({rules.min_importance_for(level)})")
        if rules.require_actionable and not suggestion.actionable:
            return RelevanceResult(False, "Suggestion is not actionable")
        return RelevanceResult(True, "Passes importance/actionability checks")

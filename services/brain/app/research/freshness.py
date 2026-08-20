from __future__ import annotations

from datetime import timedelta
from typing import Any

from .schemas import Freshness, Source


class FreshnessPolicy:
    def __init__(self, default_stale_after_days: int = 180, time_sensitive_stale_after_days: int = 7):
        self.default_stale_after_days = default_stale_after_days
        self.time_sensitive_stale_after_days = time_sensitive_stale_after_days

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "FreshnessPolicy":
        freshness_config = config.get("freshness", {})
        return cls(
            int(freshness_config.get("default_stale_after_days", 180)),
            int(freshness_config.get("time_sensitive_stale_after_days", 7)),
        )

    def stale_after(self, requirement: Freshness) -> timedelta:
        if requirement == Freshness.FRESH:
            return timedelta(days=self.time_sensitive_stale_after_days)
        return timedelta(days=self.default_stale_after_days)

    def evaluate(self, source: Source, requirement: Freshness) -> Source:
        threshold = self.stale_after(requirement)
        reference = source.published_at
        if reference is None:
            source.freshness = Freshness.UNKNOWN
            return source
        age = source.retrieved_at - reference
        if age <= threshold / 2:
            source.freshness = Freshness.FRESH
        elif age <= threshold:
            source.freshness = Freshness.RECENT
        else:
            source.freshness = Freshness.STALE
        return source

    def is_stale_for_requirement(self, source: Source, requirement: Freshness) -> bool:
        return requirement == Freshness.FRESH and source.freshness in {Freshness.STALE, Freshness.UNKNOWN}

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .schemas import DataFreshness, MarketDataEnvelope


class FreshnessPolicy:
    """Computes an honest `DataFreshness` label from provider timestamp age
    (rule 2). A cached/historical value is never re-labeled `live`."""

    def __init__(self, live_max_age_seconds: float, delayed_max_age_seconds: float, cached_max_age_seconds: float):
        self.live_max_age_seconds = live_max_age_seconds
        self.delayed_max_age_seconds = delayed_max_age_seconds
        self.cached_max_age_seconds = cached_max_age_seconds

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "FreshnessPolicy":
        freshness = config.get("freshness", {})
        return cls(
            live_max_age_seconds=float(freshness.get("live_max_age_seconds", 15)),
            delayed_max_age_seconds=float(freshness.get("delayed_max_age_seconds", 900)),
            cached_max_age_seconds=float(freshness.get("cached_max_age_seconds", 86400)),
        )

    def classify(self, timestamp: datetime, *, provider_is_mock: bool = False) -> DataFreshness:
        if provider_is_mock:
            return DataFreshness.MOCK
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        if age <= self.live_max_age_seconds:
            return DataFreshness.LIVE
        if age <= self.delayed_max_age_seconds:
            return DataFreshness.DELAYED
        if age <= self.cached_max_age_seconds:
            return DataFreshness.CACHED
        return DataFreshness.HISTORICAL

    def is_stale_for_decision(self, envelope: MarketDataEnvelope, *, max_age_seconds: float) -> bool:
        """Rule 54/55: a decision requiring current data must not proceed on
        data older than `max_age_seconds`, regardless of its label."""
        age = (datetime.now(timezone.utc) - envelope.retrieved_at).total_seconds()
        return age > max_age_seconds

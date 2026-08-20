from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone


class ProviderHealth:
    #: A rate limit is not a transient error - it is the provider telling
    #: VYOM to stop for a while. Retrying through it produced the storm
    #: visible in the Brain log: the same request id re-sent three times,
    #: dozens of concurrent 429s, and no work completed. On 429 the target
    #: is marked unavailable for this long and simply not called again.
    RATE_LIMIT_COOLDOWN_SECONDS = 90
    #: Google's free tier meters `GenerateRequestsPerDayPerProjectPerModel`
    #: - a DAILY, PER-MODEL allowance. A short cooldown is useless against
    #: it: the quota does not come back for hours. Backing the exhausted
    #: model off for long enough that the router genuinely moves to a
    #: sibling model is the only thing that keeps work flowing.
    DAILY_QUOTA_COOLDOWN_SECONDS = 3600

    #: How many requests may be in flight against ONE model at once.
    #:
    #: Without this, twenty concurrent missions all check the circuit
    #: before any of them has received a 429, all see it closed, and all
    #: twenty hit the exhausted model - each independently rediscovering
    #: the same rate limit. A small budget means the first couple of calls
    #: establish the truth and the other eighteen see an open circuit.
    MAX_CONCURRENT_PER_MODEL = 2

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self.failures: dict[str, list[datetime]] = defaultdict(list)
        # Keyed by provider, and by "provider/model". Free-tier quota is
        # metered PER MODEL, so blacklisting the whole provider on one
        # model's 429 would skip a sibling model that still has allowance
        # and fail work that could have succeeded.
        self.rate_limited_until: dict[str, datetime] = {}
        self._slots: dict[str, "asyncio.Semaphore"] = {}

    def slot(self, provider: str, model: str | None = None):
        """Acquire a concurrency slot for this model.

        Used as `async with health.slot(provider, model):` around a
        provider request. Re-check `rate_limited` INSIDE the slot: a call
        queued behind another may find the circuit already opened while it
        waited, and must not spend a request rediscovering it."""
        key = self._key(provider, model)
        semaphore = self._slots.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_PER_MODEL)
            self._slots[key] = semaphore
        return semaphore

    @staticmethod
    def _key(provider: str, model: str | None) -> str:
        return f"{provider}/{model}" if model else provider

    def record_success(self, provider: str, model: str | None = None) -> None:
        self.failures[provider].clear()
        self.rate_limited_until.pop(self._key(provider, model), None)
        if model is None:
            for key in [k for k in self.rate_limited_until if k.startswith(f"{provider}/")]:
                self.rate_limited_until.pop(key, None)

    def record_rate_limit(
        self,
        provider: str,
        model: str | None = None,
        *,
        retry_after_seconds: float | None = None,
        daily_quota: bool = False,
    ) -> datetime:
        """Open the circuit for this model (or provider). Returns when it reopens."""
        seconds = retry_after_seconds or (
            self.DAILY_QUOTA_COOLDOWN_SECONDS if daily_quota else self.RATE_LIMIT_COOLDOWN_SECONDS
        )
        until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        key = self._key(provider, model)
        current = self.rate_limited_until.get(key)
        # Never shorten an existing, longer cooldown.
        self.rate_limited_until[key] = max(until, current) if current else until
        return self.rate_limited_until[key]

    def rate_limited(self, provider: str, model: str | None = None) -> bool:
        """Is this target currently backed off?

        A provider-wide limit implies every one of its models; a
        model-specific limit says nothing about its siblings."""
        for key in filter(None, (self._key(provider, model), provider if model else None)):
            until = self.rate_limited_until.get(key)
            if until is None:
                continue
            if datetime.now(timezone.utc) >= until:
                self.rate_limited_until.pop(key, None)
                continue
            return True
        return False

    def cooldown_remaining(self, provider: str, model: str | None = None) -> float:
        remaining = 0.0
        for key in filter(None, (self._key(provider, model), provider if model else None)):
            until = self.rate_limited_until.get(key)
            if until is not None:
                remaining = max(remaining, (until - datetime.now(timezone.utc)).total_seconds())
        return max(0.0, remaining)

    def record_failure(self, provider: str) -> None:
        now = datetime.now(timezone.utc)
        self.failures[provider] = [
            instant for instant in self.failures[provider] if now - instant < self.cooldown
        ]
        self.failures[provider].append(now)

    def available(self, provider: str) -> bool:
        if self.rate_limited(provider):
            return False
        now = datetime.now(timezone.utc)
        recent = [instant for instant in self.failures[provider] if now - instant < self.cooldown]
        self.failures[provider] = recent
        return len(recent) < self.failure_threshold

    def recent_failure_count(self, provider: str) -> int:
        self.available(provider)
        return len(self.failures[provider])


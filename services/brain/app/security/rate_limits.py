from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RateRule:
    name: str
    limit: int
    window_seconds: float


@dataclass
class _Bucket:
    hits: list[float] = field(default_factory=list)


class RateLimitExceeded(Exception):
    def __init__(self, rule: str, retry_after_seconds: float):
        super().__init__(f"Rate limit {rule!r} exceeded; retry in {retry_after_seconds:.1f}s")
        self.rule = rule
        self.retry_after_seconds = retry_after_seconds


class RateLimiter:
    """Sliding-window limiter for API endpoints and global guards
    (provider/agent/automation/remote-device). Prevents accidental API
    storms and retry floods."""

    def __init__(self):
        self._buckets: dict[str, _Bucket] = defaultdict(_Bucket)
        self.rules: dict[str, RateRule] = {}

    def configure(self, rule: RateRule) -> RateRule:
        self.rules[rule.name] = rule
        return rule

    def check(self, rule_name: str, key: str = "*") -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        rule = self.rules.get(rule_name)
        if rule is None:
            return True, 0.0
        bucket_key = f"{rule_name}:{key}"
        bucket = self._buckets[bucket_key]
        now = time.monotonic()
        bucket.hits = [stamp for stamp in bucket.hits if now - stamp < rule.window_seconds]
        if len(bucket.hits) >= rule.limit:
            oldest = bucket.hits[0]
            return False, max(rule.window_seconds - (now - oldest), 0.1)
        bucket.hits.append(now)
        return True, 0.0

    def enforce(self, rule_name: str, key: str = "*") -> None:
        allowed, retry_after = self.check(rule_name, key)
        if not allowed:
            raise RateLimitExceeded(rule_name, retry_after)

    def reset(self) -> None:
        self._buckets.clear()


class GlobalRateLimits:
    """Named global guards for provider/model calls, agents,
    automations, and remote devices. Loaded from
    `config/security.yaml` in production wiring."""

    def __init__(self):
        self.limiter = RateLimiter()

    @classmethod
    def from_config(cls, config: dict) -> "GlobalRateLimits":
        guard = cls()
        for name, spec in (config.get("rate_limits") or {}).items():
            guard.limiter.configure(RateRule(
                name=name,
                limit=int(spec.get("limit", 60)),
                window_seconds=float(spec.get("window_seconds", 60)),
            ))
        return guard

    def check_provider(self, provider: str) -> tuple[bool, float]:
        return self.limiter.check("provider", provider)

    def check_remote_device(self, device: str) -> tuple[bool, float]:
        return self.limiter.check("remote_device", device)

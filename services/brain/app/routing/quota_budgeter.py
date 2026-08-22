"""Client-side quota budgeting for LLM providers ("stay under the limit,
never discover it").

VYOM's free-tier Gemini allowance is metered per model, per minute AND per
day. The old behaviour was purely reactive: fire until a 429 arrives, then
back off - so a busy morning burned the whole day's allowance in bursts
and the afternoon had nothing left, while sibling models sat untouched.
The budgeter inverts that: every request is paced BEFORE it is sent, and
the daily counters persist across Brain restarts.

Three mechanisms:
1. RPM pacing - a sliding 60s window per provider/model; callers wait for
   a free slot instead of bursting.
2. Daily budgeting - a persisted per-day counter per model; models near
   their daily cap are deprioritised by the router (spreading) and models
   past it are skipped entirely, so traffic fans out across sibling
   models whose allowances are separate.
3. Teach-in - the exact free-tier numbers change without notice. When a
   daily-quota 429 still arrives, the observed count becomes that model's
   effective cap for the day. The system converges on the truth without
   ever needing the numbers to be exactly right up front.

Voice (Gemini Live, Rust side) shares the same project allowance but a
different process; it cannot be paced from here. This accounts for text
traffic and exposes /api/quota so the other side can at least see it.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ModelQuota:
    rpm: int
    rpd: int


#: Conservative Gemini free-tier allowances by model-name substring.
#: Conservative because the teach-in clamps the truth the first time a
#: real 429 arrives, so these only shape behaviour until then.
_FREE_TIER: tuple[tuple[str, ModelQuota], ...] = (
    ("flash-lite", ModelQuota(rpm=15, rpd=1000)),
    ("flash", ModelQuota(rpm=10, rpd=250)),
    ("pro", ModelQuota(rpm=5, rpd=100)),
)

#: Never plan to consume the very last request of an allowance: Google's
#: meter and ours are not perfectly aligned, and riding the exact edge is
#: how a burst still slips a 429 through.
_RPM_MARGIN = 0.8
_RPD_MARGIN = 0.9

#: Longest a paced caller waits for an RPM slot before giving the caller
#: its slot back as a rate-limit condition (the existing health/fallback
#: machinery then routes elsewhere - no new failure semantics).
_MAX_PACE_WAIT_SECONDS = 20.0


class QuotaWaitTimeout(RuntimeError):
    """No RPM slot freed up within the bounded wait."""

    def __init__(self, provider: str, model: str, retry_after: float):
        super().__init__(f"Quota pacing window full for {provider}/{model}")
        self.provider = provider
        self.model = model
        self.retry_after = retry_after


class QuotaBudgeter:
    def __init__(self, store_path: Path | None = None, max_pace_wait_seconds: float = _MAX_PACE_WAIT_SECONDS):
        self._store_path = store_path
        self._max_pace_wait = max_pace_wait_seconds
        self._date = self._today()
        self._counts: dict[str, int] = {}
        self._clamped: dict[str, int] = {}
        self._windows: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._load()

    # -- daily persistence ------------------------------------------------

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self) -> None:
        if self._store_path is None or not self._store_path.is_file():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if data.get("date") != self._date:
            return  # a new day resets every allowance
        self._counts = {str(k): int(v) for k, v in (data.get("counts") or {}).items()}
        self._clamped = {str(k): int(v) for k, v in (data.get("clamped") or {}).items()}

    def _persist(self) -> None:
        if self._store_path is None:
            return
        payload = {"date": self._date, "counts": self._counts, "clamped": self._clamped}
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, self._store_path)
        except OSError:
            # Accounting must never break a model call; losing one
            # counter update only makes pacing slightly optimistic.
            pass

    # -- quota math --------------------------------------------------------

    @staticmethod
    def quota_for(model: str) -> ModelQuota:
        lowered = model.lower()
        for needle, quota in _FREE_TIER:
            if needle in lowered:
                return quota
        return ModelQuota(rpm=10, rpd=250)

    @staticmethod
    def _key(provider: str, model: str | None) -> str:
        return f"{provider}/{model}" if model else provider

    def _roll_date_if_needed(self) -> None:
        today = self._today()
        if today != self._date:
            self._date = today
            self._counts = {}
            self._clamped = {}

    def daily_limit(self, provider: str, model: str | None) -> int:
        key = self._key(provider, model)
        if key in self._clamped:
            return self._clamped[key]
        return int(self.quota_for(model or "").rpd * _RPD_MARGIN)

    def daily_used(self, provider: str, model: str | None) -> int:
        self._roll_date_if_needed()
        return self._counts.get(self._key(provider, model), 0)

    def exhausted(self, provider: str, model: str | None) -> bool:
        return self.daily_used(provider, model) >= self.daily_limit(provider, model)

    def usage_ratio(self, provider: str, model: str | None) -> float:
        """0.0 (untouched) .. 1.0 (at the daily limit) - the router's
        spreading signal."""
        limit = self.daily_limit(provider, model)
        if limit <= 0:
            return 1.0
        return min(1.0, self.daily_used(provider, model) / limit)

    # -- pacing ------------------------------------------------------------

    async def acquire(self, provider: str, model: str | None) -> None:
        """Reserve one request against both meters, waiting (bounded) for
        an RPM slot. Raises QuotaWaitTimeout when the window stays full;
        daily exhaustion is NOT waited on here (that is the router's job
        to route around)."""
        key = self._key(provider, model)
        limit = int(self.quota_for(model or "").rpm * _RPM_MARGIN)
        deadline = time.monotonic() + self._max_pace_wait
        async with self._lock:
            self._roll_date_if_needed()
            while True:
                window = self._windows.setdefault(key, deque())
                now = time.monotonic()
                while window and now - window[0] >= 60.0:
                    window.popleft()
                if len(window) < max(1, limit):
                    window.append(now)
                    self._counts[key] = self._counts.get(key, 0) + 1
                    self._persist()
                    return
                wait = min(60.0 - (now - window[0]) + 0.05, deadline - time.monotonic())
                if wait <= 0:
                    raise QuotaWaitTimeout(
                        provider, model or "",
                        retry_after=min(60.0, max(1.0, 60.0 - (now - window[0]))),
                    )
                await asyncio.sleep(wait)

    # -- teach-in ----------------------------------------------------------

    def clamp_daily(self, provider: str, model: str | None) -> None:
        """A daily-quota 429 arrived: today's observed count IS the real
        allowance. Clamp so the router stops selecting this model for the
        rest of the day."""
        self._roll_date_if_needed()
        key = self._key(provider, model)
        observed = self._counts.get(key, 0)
        if observed and (key not in self._clamped or self._clamped[key] > observed):
            self._clamped[key] = observed
            self._persist()

    # -- observability -----------------------------------------------------

    def snapshot(self) -> dict[str, dict[str, object]]:
        """Per-model budget state for /api/quota."""
        self._roll_date_if_needed()
        state: dict[str, dict[str, object]] = {}
        for key, used in self._counts.items():
            provider, _, model = key.partition("/")
            limit = self.daily_limit(provider, model)
            quota = self.quota_for(model)
            state[key] = {
                "used_today": used,
                "daily_limit": limit,
                "daily_remaining": max(0, limit - used),
                "nominal_rpd": quota.rpd,
                "rpm_limit": int(quota.rpm * _RPM_MARGIN),
                "exhausted": used >= limit,
            }
        return state

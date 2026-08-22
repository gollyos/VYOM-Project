"""Repair B — quota budgeting, response cache, and event replay.

The user's report: "Maya ran all day on one Gemini free key; VYOM keeps
hitting rate limits and disconnecting." These tests pin the three
mechanisms that close that gap: pacing before sending, caching repeats,
and replaying events a disconnected client missed.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.providers.base import ProviderRequest
from app.providers.response_cache import ResponseCache
from app.routing.quota_budgeter import QuotaBudgeter, QuotaWaitTimeout
from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType
from app.schemas.tasks import TaskProfile


def _request(text: str = "hello", model: str = "gemini-3.1-flash-lite"):
    return ProviderRequest(
        model=model,
        user_request=text,
        system_instruction="test",
        profile=TaskProfile(),
    )


# -- QuotaBudgeter ---------------------------------------------------------


def test_daily_counter_persists_across_restart(tmp_path: Path):
    store = tmp_path / "quota-usage.json"
    first = QuotaBudgeter(store)
    for _ in range(5):
        asyncio.get_event_loop_policy()
    async def burst(budgeter: QuotaBudgeter):
        for _ in range(5):
            await budgeter.acquire("google", "gemini-3.1-flash-lite")
    asyncio.run(burst(first))
    # A restart must not forget what today already spent.
    second = QuotaBudgeter(store)
    assert second.daily_used("google", "gemini-3.1-flash-lite") == 5


def test_new_day_resets_allowances(tmp_path: Path):
    store = tmp_path / "quota-usage.json"
    budgeter = QuotaBudgeter(store)
    asyncio.run(budgeter.acquire("google", "gemini-3.1-flash-lite"))
    # Forge yesterday's file: loading it must yield a clean slate.
    data = json.loads(store.read_text())
    data["date"] = "2001-01-01"
    store.write_text(json.dumps(data))
    fresh = QuotaBudgeter(store)
    assert fresh.daily_used("google", "gemini-3.1-flash-lite") == 0


def test_daily_quota_429_teaches_the_real_limit(tmp_path: Path):
    budgeter = QuotaBudgeter(tmp_path / "quota-usage.json")
    key = "google/gemini-flash-latest"
    # A day that already spent 40 requests (counts set directly: this
    # test pins the CLAMP logic, not RPM pacing, which has its own test).
    budgeter._counts[key] = 40
    budgeter._persist()
    assert not budgeter.exhausted("google", "gemini-flash-latest")
    # A daily 429 at 40 observed requests means the real allowance was 40.
    budgeter.clamp_daily("google", "gemini-flash-latest")
    assert budgeter.exhausted("google", "gemini-flash-latest")
    assert budgeter.daily_limit("google", "gemini-flash-latest") == 40
    state = budgeter.snapshot()["google/gemini-flash-latest"]
    assert state["exhausted"] is True


def test_rpm_pacing_bounds_the_burst(tmp_path: Path):
    budgeter = QuotaBudgeter(tmp_path / "q.json", max_pace_wait_seconds=0.05)
    async def run():
        for _ in range(12):  # 15 rpm * 0.8 margin = 12 per window
            await budgeter.acquire("google", "gemini-3.1-flash-lite")
        with pytest.raises(QuotaWaitTimeout) as raised:
            await budgeter.acquire("google", "gemini-3.1-flash-lite")
        assert raised.value.retry_after > 0
    asyncio.run(run())


def test_models_are_metered_separately(tmp_path: Path):
    budgeter = QuotaBudgeter(tmp_path / "q.json")
    # flash-latest free tier: 250 RPD nominal, 0.9 margin = 225.
    budgeter._counts["google/gemini-flash-latest"] = 225
    assert budgeter.exhausted("google", "gemini-flash-latest")
    # The sibling model's allowance is a separate bucket entirely.
    assert not budgeter.exhausted("google", "gemini-3.1-flash-lite")
    assert budgeter.usage_ratio("google", "gemini-3.1-flash-lite") == 0.0


# -- ResponseCache ---------------------------------------------------------


def test_identical_request_hits_cache_not_the_provider(tmp_path: Path):
    from app.providers.base import ProviderResponse

    cache = ResponseCache(tmp_path / "cache", ttl_seconds=60)
    request = _request("summarise this")
    assert cache.get(request) is None
    cache.put(request, ProviderResponse(text="answer", structured={"ok": True}))
    hit = cache.get(request)
    assert hit is not None and hit.text == "answer" and hit.structured == {"ok": True}
    different = _request("summarise THAT")
    assert cache.get(different) is None


def test_cache_entries_expire(tmp_path: Path):
    from app.providers.base import ProviderResponse

    cache = ResponseCache(tmp_path / "cache", ttl_seconds=0.05)
    request = _request("status")
    cache.put(request, ProviderResponse(text="ok"))
    import time

    time.sleep(0.08)
    assert cache.get(request) is None


def test_cache_can_be_disabled_by_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.providers.base import ProviderResponse

    monkeypatch.setenv("VYOM_RESPONSE_CACHE", "0")
    cache = ResponseCache(tmp_path / "cache")
    request = _request("hello")
    cache.put(request, ProviderResponse(text="ok"))
    assert cache.enabled is False
    assert cache.get(request) is None


# -- EventBus replay -------------------------------------------------------


def _event(event_id: str, task_id: str = "t1") -> BrainEvent:
    return BrainEvent(
        event_id=event_id,
        task_id=task_id,
        timestamp=datetime.now(timezone.utc),
        type=EventType.TASK_PROGRESS,
        human_readable_message="step",
    )


def test_history_after_replays_exactly_what_was_missed():
    bus = EventBus()
    for event_id in ("e1", "e2", "e3"):
        asyncio.run(bus.publish(_event(event_id)))
    replay = bus.history_after("e1")
    assert [event.event_id for event in replay] == ["e2", "e3"]
    # Unknown cursor (restart / rollover): full bounded history.
    assert len(bus.history_after("missing-id")) == 3
    # No cursor: no replay - live-only clients keep today's behaviour.
    assert bus.history_after(None) == []


def test_register_feeds_live_queue_and_stops_on_unregister():
    bus = EventBus()
    queue, unregister = bus.register()
    asyncio.run(bus.publish(_event("live-1")))
    assert queue.get_nowait().event_id == "live-1"
    unregister()
    asyncio.run(bus.publish(_event("live-2")))
    with pytest.raises(asyncio.QueueEmpty):
        queue.get_nowait()

"""Deterministic weather routing: one free Open-Meteo call, no mission loop.

Before this path existed, "aaj mausam kaisa hai" fell into the general
mission loop - a multi-step planner mission of paid model calls for a
one-call free answer, which on any model hiccup produced steps with no
answer at all (the owner's "weather pucha, bahut sare task, koi jawab
nahi" experience on 2026-08-27).
"""

import pytest

from app.execution.action_engine import ActionEngine
from app.runtime.task_classifier import TaskClassifier


def _classify(text: str):
    return TaskClassifier().classify(text)


def test_hinglish_weather_phrases_route_deterministically():
    for phrase in (
        "aaj mausam kaisa hai",
        "aaj Delhi ka mausam batao",
        "weather batao",
        "Mumbai me barish hogi kya",
        "बाहर गर्मी कितनी है",
        "temperature kya hai",
    ):
        profile = _classify(phrase)
        assert profile.deterministic, phrase
        assert profile.intent in {"weather_current", "weather_forecast"}, phrase


def test_forecast_phrases_route_to_forecast_intent():
    for phrase in (
        "kal ka mausam batao",
        "weather forecast for next week",
        "agle din barish hogi?",
    ):
        assert _classify(phrase).intent == "weather_forecast", phrase


def test_current_phrases_route_to_current_intent():
    for phrase in ("aaj mausam kaisa hai", "weather batao"):
        assert _classify(phrase).intent == "weather_current", phrase


def test_song_named_barish_stays_play_media():
    """A song whose NAME is a weather word must not hijack the media path."""
    profile = _classify("barish song chalao")
    assert profile.intent == "play_media"


def test_location_extraction_keeps_city_drops_fillers():
    extract = ActionEngine._extract_weather_location
    assert extract("aaj Delhi ka mausam batao") == "Delhi"
    assert extract("weather in New York tomorrow") == "New York"
    assert extract("Mumbai me barish hogi") == "Mumbai"


def test_location_extraction_returns_none_for_bare_requests():
    extract = ActionEngine._extract_weather_location
    assert extract("aaj mausam kaisa hai") is None
    assert extract("weather batao") is None
    assert extract("bahar mausam kaisa hai") is None  # "bahar" = outside, not Bahār (Iran)
    assert extract("yaha ka mausam kya hai") is None  # "yaha" = here


@pytest.mark.asyncio
async def test_approximate_location_uses_fresh_cache(monkeypatch, tmp_path, chdir_tmp_path=None):
    """A fresh cache entry is served without hitting the network; a stale
    one re-resolves; when the network is unreachable a stale cache still
    beats a wrong hardcoded default (the travel-with-laptop case)."""
    import json as _json

    from app.execution import action_engine as ae

    cache_file = tmp_path / "weather-location.json"
    monkeypatch.setattr(
        ActionEngine, "_LOCATION_CACHE_PATH", cache_file)
    cache_file.write_text(_json.dumps(
        {"city": "Ahmedabad", "at": __import__("time").time()}), encoding="utf-8")

    async def fail_get(*args, **kwargs):
        raise AssertionError("network must not be touched while cache is fresh")

    class FailClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return await fail_get(*a, **k)

    monkeypatch.setattr(ae.httpx, "AsyncClient", FailClient)
    engine = ActionEngine.__new__(ActionEngine)
    assert await engine._approximate_location() == "Ahmedabad"

    # Stale cache + network down -> last known city, never a wrong default.
    cache_file.write_text(_json.dumps(
        {"city": "Jaipur", "at": 0.0}), encoding="utf-8")
    async def unreachable(self, *a, **k):
        raise ae.httpx.HTTPError("offline")

    class DownClient(FailClient):
        async def get(self, *a, **k):
            return await unreachable(self, *a, **k)

    monkeypatch.setattr(ae.httpx, "AsyncClient", DownClient)
    assert await engine._approximate_location() == "Jaipur"

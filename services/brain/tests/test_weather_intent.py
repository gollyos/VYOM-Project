"""Deterministic weather routing: one free Open-Meteo call, no mission loop.

Before this path existed, "aaj mausam kaisa hai" fell into the general
mission loop - a multi-step planner mission of paid model calls for a
one-call free answer, which on any model hiccup produced steps with no
answer at all (the owner's "weather pucha, bahut sare task, koi jawab
nahi" experience on 2026-08-27).
"""

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

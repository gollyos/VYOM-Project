"""Volume/brightness deterministic routing + media query intelligence.

From the 2026-08-28 overnight trace: "Ek kaam karo audio ko 100% kar do"
FAILED with a raw gemini-404 (the request had no deterministic route and
the general path's model was dead), and "imran hashmi ka song" searched
the bare actor name (interviews/shorts) instead of his songs.
"""

from app.runtime.task_classifier import TaskClassifier


def _classify(text: str):
    return TaskClassifier().classify(text)


def test_volume_requests_route_deterministically():
    for phrase in (
        "Ek kaam karo audio ko 100% kar do",
        "volume badhao",
        "awaaz kam karo",
        "volume 50 percent karo",
        "sound mute kar do",
        "आवाज़ तेज करो",
    ):
        profile = _classify(phrase)
        assert profile.deterministic, phrase
        assert profile.intent == "volume_control", f"{phrase} -> {profile.intent}"


def test_brightness_requests_route_deterministically():
    for phrase in (
        "brightness kam karo",
        "screen ki roshni badhao",
        "brightness 80 percent set karo",
        "स्क्रीन की रोशनी कम करो",
    ):
        profile = _classify(phrase)
        assert profile.deterministic, phrase
        assert profile.intent == "brightness_control", f"{phrase} -> {profile.intent}"


def test_volume_word_alone_without_order_is_not_hardware_control():
    profile = _classify("volume kitna hai abhi")
    assert profile.intent != "volume_control"


def test_possessive_song_request_searches_entity_songs():
    """'X ka song' -> search 'X songs' (artist/actor music, not talk clips)."""
    from app.execution.action_engine import ActionEngine
    from app.schemas.tasks import Task

    query = ActionEngine._extract_media_query("imran hashmi ka song chala do")
    assert "imran hashmi" in query.lower()
    # The suffix is applied in _play_media; extraction itself must have
    # kept the entity name clean.
    assert "chalao" not in query and "song" not in query.lower()

"""Tests for is_conversational's meta-conversational pattern
(app/runtime/planner.py) - a real production bug: "मैं सारी बातें नहीं
बोल रहा हूं जो मेन टॉपिक रहते हैं।" (11 words, no action verb) fell
through the length/verb heuristics into the tool-calling mission,
where the free-tier model itself hallucinated an unrelated
memory_search("Our solar system") call.
"""
from __future__ import annotations

from app.runtime.planner import is_conversational


def test_meta_commentary_about_the_conversation_is_conversational():
    text = "मैं सारी बातें नहीं बोल रहा हूं जो मेन टॉपिक रहते हैं।"
    assert is_conversational(text) is True


def test_english_main_topic_phrasing_is_conversational():
    assert is_conversational("I'm trying to stay on the main topic here") is True


def test_a_real_long_actionable_request_is_not_conversational():
    """The fix must not make every long Hindi/English sentence
    conversational - a genuine multi-word action request must still
    reach the mission path."""
    assert is_conversational("Please search the web for the latest news about AI regulation") is False


def test_a_genuine_question_about_a_topic_subject_is_not_conversational():
    """'topic' appearing as part of an actual research request (not
    meta-commentary about staying on topic) must not be swallowed by
    the same pattern - this checks the phrase list is specific enough
    to avoid over-matching."""
    assert is_conversational("find out about the latest AI topics and remember it") is False

"""Tests for Hinglish vocabulary recognition, STT noise filtering, and Edge TTS voice detection."""
from __future__ import annotations

import pytest

from app.runtime.task_classifier import looks_like_stt_noise
from app.tools_builtin.edge_tts_tool import detect_voice_for_text, DEFAULT_VOICES


def test_hinglish_conversational_phrases_not_rejected_as_noise():
    hinglish_queries = [
        "tum kaun ho",
        "tum kon ho",
        "kya chal raha hai",
        "vyom brain disconnect kyu ho raha hai",
        "baat cheet samajh nahi aa raha",
        "kuch madad chahiye",
        "kaise ho aap",
        "mujhe batao",
        "sab theek hai bhai",
        "main bilkul theek hu",
        "dikkat aa rahi hai",
        "problem solve karo",
    ]
    for query in hinglish_queries:
        assert looks_like_stt_noise(query) is False, f"Expected '{query}' NOT to be noise"


def test_devanagari_phrases_not_rejected_as_noise():
    devanagari_queries = [
        "तुम कौन हो",
        "क्या चल रहा है",
        "बातचीत समझ नहीं आ रही",
        "सब ठीक है",
        "मदद चाहिए",
    ]
    for query in devanagari_queries:
        assert looks_like_stt_noise(query) is False, f"Expected '{query}' NOT to be noise"


def test_pure_garbage_is_rejected_as_noise():
    garbage_queries = [
        "xz qw zz",
        "blorp flump",
        "qq ww rr tt",
    ]
    for query in garbage_queries:
        assert looks_like_stt_noise(query) is True, f"Expected '{query}' to be noise"


def test_edge_tts_detects_hinglish_and_hindi_voice():
    assert detect_voice_for_text("Aap tension mat lo, main abhi ye task complete kar deti hoon", preferred_gender="female") == DEFAULT_VOICES["hi"]
    assert detect_voice_for_text("Main theek se samajh nahi paaya", preferred_gender="male") == DEFAULT_VOICES["hi-male"]
    assert detect_voice_for_text("नमस्ते, आपका स्वागत है", preferred_gender="female") == DEFAULT_VOICES["hi"]
    assert detect_voice_for_text("The current weather is sunny and pleasant", preferred_gender="female") == DEFAULT_VOICES["en-in"]

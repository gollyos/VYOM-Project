"""Tests for TranslationFormatterService.
Validates dictation parsing, Hindi-to-English translation patterns,
recipient greeting formatting, and tone management.
"""
from __future__ import annotations

import pytest

from app.messaging.translation_formatter import TranslationFormatterService


def test_parse_dictation_request():
    prompt = "Amit ko WhatsApp pe bolo ki meeting kal 4 baje shift ho gayi hai isko english me karke bhej do"
    parsed = TranslationFormatterService.parse_dictation_request(prompt)

    assert parsed["platform"] == "whatsapp"
    assert parsed["recipient"] == "Amit"
    assert parsed["tone"] == "professional"


def test_translate_and_format_meeting_reschedule():
    result = TranslationFormatterService.translate_and_format(
        "meeting kal 4 baje shift ho gayi hai",
        recipient="Amit",
        tone="professional",
    )

    assert result.target_language == "en"
    assert result.recipient == "Amit"
    assert "Hi Amit," in result.translated_text
    assert "The meeting has been rescheduled to tomorrow at 4:00 PM" in result.translated_text


def test_translate_and_format_proposal():
    result = TranslationFormatterService.translate_and_format(
        "proposal check karke batao",
        recipient="Rahul",
        tone="polite",
    )

    assert "Hi Rahul," in result.translated_text
    assert "Please review the attached proposal" in result.translated_text

"""Tests for SocialResponderService.
Validates normal mode voice alerts ('Boss, X ka message aaya hai...'),
Focus Mode quiet handling (zero audio interruptions), and stylized reply generation.
"""
from __future__ import annotations

import pytest

from app.messaging.social_responder import SocialMessage, SocialResponderService


def test_normal_mode_voice_prompt():
    service = SocialResponderService(owner_name="Gunjan")
    msg = SocialMessage(
        platform="whatsapp",
        sender_name="Rahul Sharma",
        sender_handle="+919876543210",
        content="Bhai kal meeting ka kya plan hai?",
    )
    decision = service.process_incoming(msg, is_focus_mode=False)

    assert decision.action == "ask_boss"
    assert decision.spoken_prompt is not None
    assert "Boss, Whatsapp pe Rahul ka message aaya hai" in decision.spoken_prompt
    assert "Kya main iska answer kar doon?" in decision.spoken_prompt
    assert "meeting" in decision.suggested_reply.lower() or "slot" in decision.suggested_reply.lower()


def test_focus_mode_quiet_rule():
    service = SocialResponderService(owner_name="Gunjan")
    msg = SocialMessage(
        platform="telegram",
        sender_name="Client John",
        sender_handle="@john_dev",
        content="Hey, did you review the design?",
    )
    decision = service.process_incoming(msg, is_focus_mode=True)

    # In Focus Mode, VYOM must NOT interrupt or speak to boss!
    assert decision.is_focus_mode is True
    assert decision.spoken_prompt is None
    assert decision.action == "quiet_queue"
    assert len(service.queued_in_focus) == 1
    assert "focus session" in decision.suggested_reply.lower()


def test_stylized_replies():
    service = SocialResponderService(owner_name="Gunjan")
    msg = SocialMessage(platform="instagram", sender_name="Amit", sender_handle="@amit", content="Hi!")
    reply = service.generate_stylized_reply(msg)
    assert "Hey Amit!" in reply

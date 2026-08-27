"""Tests for SmartEmailComposer.
Validates professional email formatting, tone customization, key point bulleting,
CTA customization, and DraftRequest preparation.
"""
from __future__ import annotations

import pytest

from app.email.smart_email_service import SmartEmailComposer


def test_compose_professional_proposal():
    composer = SmartEmailComposer(default_sender_name="Gunjan", default_company="VYOM Technologies")
    content = composer.compose_email_content(
        recipient_name="Amit Verma",
        context="the AI automation roadmap",
        tone="proposal",
        key_points=["Complete Phase 1 deployment", "Integration with existing CRM", "24/7 dedicated support"],
        cta="Let us schedule a 15-minute call tomorrow at 3 PM to finalize the scope.",
    )

    assert "Dear Amit Verma," in content
    assert "Thank you for connecting regarding the AI automation roadmap" in content
    assert "• Complete Phase 1 deployment" in content
    assert "• Integration with existing CRM" in content
    assert "Let us schedule a 15-minute call" in content
    assert "Best regards,\nGunjan\nVYOM Technologies" in content


def test_create_draft_request():
    composer = SmartEmailComposer(default_sender_name="Gunjan", default_company="VYOM")
    draft_req = composer.create_draft_request(
        to=["client@example.com"],
        subject="Project Update - Q3 Milestone",
        recipient_name="Sarah",
        context="our Q3 engineering deliverables",
        tone="casual_business",
        key_points=["All APIs integrated", "Test suite 100% green"],
    )

    assert len(draft_req.to) == 1
    assert draft_req.to[0].address == "client@example.com"
    assert draft_req.subject == "Project Update - Q3 Milestone"
    assert "Hi Sarah," in draft_req.body_text
    assert "All APIs integrated" in draft_req.body_text
    assert draft_req.metadata["tone"] == "casual_business"

"""Regression tests for a real bug chain found during live end-to-end
testing this session: "Send an email to X with subject Y and body Z"
silently failed to send despite the user approving it. Root causes (all
fixed together, verified against a REAL Gmail inbox via IMAP search
after a real SMTP send — not just these unit-level checks):

1. PermissionEngine.classify() only matched the exact substring
   "send email" — "send AN email" (or any other article) fell through
   to the default L1, so no approval was ever requested for a real send.
2. TaskClassifier never assigned a real intent to "send an email..."
   requests — they fell through to the generic "general" intent, which
   the runtime cannot route to any tool.
3. ActionEngine had no "send_email" handler at all — even with (1) and
   (2) fixed, there was nothing to actually parse the request and call
   EmailTool's draft->send flow.
"""
from __future__ import annotations

from app.execution.action_engine import TOOL_INTENTS
from app.runtime.task_classifier import TaskClassifier
from app.security.permission_engine import PermissionEngine


def test_send_email_with_article_requires_l2_approval():
    """The exact bug: 'Send AN email' (not the bare 'Send email' the old
    exact-substring marker matched) must still be gated at L2."""
    engine = PermissionEngine()
    assert engine.classify("Send an email to gunjan@example.com with subject Test").value == "L2"
    assert engine.classify("Send an email to the client").value == "L2"
    # Original exact-marker phrasing must still work too (no regression).
    assert engine.classify("Send email to the client").value == "L2"


def test_send_message_with_article_also_requires_l2():
    engine = PermissionEngine()
    assert engine.classify("Send a message to the team about the outage").value == "L2"


def test_read_only_email_requests_stay_below_l2():
    """The new regex must not over-match read-only phrasing that merely
    mentions email/message without an actual send verb driving it."""
    engine = PermissionEngine()
    assert engine.classify("Show me my inbox").value != "L2"
    assert engine.classify("Search my email for invoices").value != "L2"


def test_task_classifier_assigns_send_email_intent():
    classifier = TaskClassifier()
    profile = classifier.classify(
        'Send an email to gunjan@example.com with subject "Hello" and body "This is a test."'
    )
    assert profile.intent == "send_email"
    assert "tools" in profile.needs


def test_send_email_intent_is_a_registered_tool_intent():
    """ActionEngine.execute() only reaches a real handler for intents in
    TOOL_INTENTS — this is what makes task.requires_tools=True actually
    resolve to a real workflow instead of raising 'No registered action
    workflow can satisfy this tool request'."""
    assert "send_email" in TOOL_INTENTS


def test_send_approved_outreach_still_routes_to_the_dedicated_workflow():
    """The new generic 'send X email' catch must not shadow the existing,
    more specific outreach-approval intent."""
    classifier = TaskClassifier()
    profile = classifier.classify("send approved outreach")
    assert profile.intent == "send_approved_outreach"

"""Repair E — the PC remembers its unfinished work.

"Aur kabhi agar kuch work reh gaya, again PC open karne pe jo pending
work ho usko yaad bhi rahe" - the morning briefing now leads with real
failed/paused task-store rows, and the briefing payload carries
retry candidates for the UI.
"""
from __future__ import annotations

from app.daily_review.morning import MorningBriefingInput, MorningBriefingService


def test_pending_work_leads_the_briefing():
    service = MorningBriefingService()
    briefing = service.build(MorningBriefingInput(
        pending_task_notes=["task_abc|Research gold prices (failed)", "task_def|Send invoice (paused)"],
        calendar_meeting_count=2,
    ))
    assert briefing.highlights[0].startswith("task_abc") is False  # note text, not raw id
    assert any("Research gold prices" in item for item in briefing.highlights)
    assert "Unfinished" in briefing.highlights[0] or "Research gold prices" in briefing.highlights[0]
    # Retry candidates parsed for one-tap retry.
    assert {"task_id": "task_abc", "what": "Research gold prices (failed)"} in briefing.retry_candidates


def test_no_pending_work_changes_nothing():
    service = MorningBriefingService()
    briefing = service.build(MorningBriefingInput(calendar_meeting_count=1))
    assert briefing.retry_candidates == []
    assert not any("carried over" in item for item in briefing.highlights)

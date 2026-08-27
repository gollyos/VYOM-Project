"""Repair E — the PC remembers its unfinished work.

"Aur kabhi agar kuch work reh gaya, again PC open karne pe jo pending
work ho usko yaad bhi rahe" - the morning briefing now leads with real
failed/paused task-store rows, and the briefing payload carries
retry candidates for the UI.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.daily_review.morning import MorningBriefingInput, MorningBriefingService
from app.main import create_app
from app.runtime.task_classifier import TaskClassifier
from app.schemas.tasks import Task, TaskStatus


def test_owner_morning_pending_command_routes_to_personal_os():
    classifier = TaskClassifier()
    utterances = (
        "VYOM, morning briefing do. Mere real pending aur failed kaam pehle batao.",
        "Subah ka briefing do, jo adhoora kaam hai pehle batao.",
    )

    for utterance in utterances:
        profile = classifier.classify(utterance)
        assert profile.intent == "plan_today", utterance
        assert profile.deterministic is True
        assert profile.needs == {"phase11"}


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


@pytest.mark.asyncio
async def test_exact_owner_command_speaks_persisted_failed_and_paused_work(tmp_path):
    settings = Settings(
        database_path=tmp_path / "morning.db",
        skills_root=tmp_path / "skills",
        agents_root=tmp_path / "agents",
        audit_log_path=tmp_path / "audit.jsonl",
        secret_store_path=tmp_path / "secrets",
        artifacts_root=tmp_path / "artifacts",
        backup_root=tmp_path / "backups",
        tool_registry_path=Path(__file__).parent / "fixtures" / "tools_no_mcp.yaml",
    )

    with TestClient(create_app(settings)) as client:
        await client.app.state.task_store.save(Task(
            goal="Research gold prices",
            user_request="Research gold prices",
            status=TaskStatus.FAILED,
        ))
        await client.app.state.task_store.save(Task(
            goal="Send Finora invoice",
            user_request="Send Finora invoice",
            status=TaskStatus.PAUSED,
        ))

        created = client.post("/api/tasks", json={
            "user_request": "VYOM, morning briefing do. Mere real pending aur failed kaam pehle batao.",
        }).json()
        current = created
        for _ in range(200):
            current = client.get(f"/api/tasks/{created['id']}").json()
            if current["status"] in {"completed", "failed"}:
                break
            time.sleep(0.025)

        assert current["status"] == "completed", current.get("error")
        assert current["profile"]["intent"] == "plan_today"
        response = current["result"]["response"]
        assert "Unfinished: Research gold prices (failed)" in response
        assert "Unfinished: Send Finora invoice (paused)" in response
        morning = current["result"]["structured_data"]["morning_briefing"]
        assert {item["what"] for item in morning["retry_candidates"]} == {
            "Research gold prices (failed)",
            "Send Finora invoice (paused)",
        }

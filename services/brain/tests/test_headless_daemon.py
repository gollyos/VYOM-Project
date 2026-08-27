"""Tests for HeadlessServerDaemon.
Validates 24/7 VPS daemon lifecycle, cron job registration, periodic execution,
and state file persistence.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from app.automation.headless_daemon import HeadlessServerDaemon


@pytest.mark.asyncio
async def test_daemon_lifecycle_and_job_execution(tmp_path: Path):
    state_file = tmp_path / "daemon_state.json"
    daemon = HeadlessServerDaemon(state_path=state_file)

    executed = []

    def mock_sweep_handler(params):
        executed.append(params.get("module"))
        return "ok"

    daemon.register_handler("sweep_inbox", mock_sweep_handler)

    daemon.add_job(
        job_id="social_sweep",
        name="Periodic Social Inbox Sweep",
        interval_seconds=1,
        action="sweep_inbox",
        params={"module": "whatsapp"},
    )

    await daemon.start()
    assert daemon._running is True
    assert state_file.exists()

    # Let daemon loop trigger
    await asyncio.sleep(1.5)

    await daemon.stop()
    assert daemon._running is False
    assert len(executed) >= 1
    assert "whatsapp" in executed

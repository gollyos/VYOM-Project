from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from app.browser.browser_actions import BrowserActions
from app.browser.browser_session import BrowserSession, BrowserTimeoutError
from app.browser.playwright_manager import PlaywrightManager
from app.runtime import mission_packs


# -- fakes: no real browser, deterministic, fast --------------------------


class _FakePage:
    def __init__(self, *, hang: bool = False, raise_on_goto: Exception | None = None):
        self._closed = False
        self._hang = hang
        self._raise_on_goto = raise_on_goto
        self.url = "about:blank"
        self.goto_calls = 0

    def is_closed(self) -> bool:
        return self._closed

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls += 1
        if self._raise_on_goto is not None:
            raise self._raise_on_goto
        if self._hang:
            await asyncio.Event().wait()  # never completes on its own
        self.url = url
        return _FakeResponse()

    async def title(self) -> str:
        return "fake title"

    async def close(self) -> None:
        self._closed = True


class _FakeResponse:
    status = 200


class _FakeManager:
    """Stands in for PlaywrightManager - no real process is ever spawned."""

    def __init__(self, page: _FakePage):
        self._page = page
        self.new_page_calls = 0
        self.closed = False

    async def new_page(self):
        self.new_page_calls += 1
        return self._page

    async def close(self) -> None:
        self.closed = True


# -- 1/2/3: event loop responsiveness, timeout return of control, continuation --


async def test_event_loop_remains_responsive_during_stuck_navigation():
    page = _FakePage(hang=True)
    session = BrowserSession(_FakeManager(page), default_timeout=1.0)
    actions = BrowserActions(session)

    heartbeats = 0

    async def heartbeat_loop():
        nonlocal heartbeats
        while True:
            await asyncio.sleep(0.1)
            heartbeats += 1

    hb = asyncio.create_task(heartbeat_loop())
    with pytest.raises(BrowserTimeoutError):
        await actions.perform("open", {"url": "https://example.test/stuck"})
    hb.cancel()
    try:
        await hb
    except asyncio.CancelledError:
        pass

    # The caller's own loop kept running other work the whole time the
    # browser call was stuck - proof it was never blocked.
    assert heartbeats >= 5


async def test_navigation_timeout_actually_returns_control():
    page = _FakePage(hang=True)
    session = BrowserSession(_FakeManager(page), default_timeout=0.5)
    actions = BrowserActions(session)

    started = time.monotonic()
    with pytest.raises(BrowserTimeoutError):
        await actions.perform("open", {"url": "https://example.test/stuck"})
    elapsed = time.monotonic() - started

    # Bounded well below the underlying hang (which never resolves on its
    # own) - proves the timeout is real, not cosmetic.
    assert elapsed < 2.0


async def test_outer_coroutine_continues_after_browser_timeout():
    page = _FakePage(hang=True)
    session = BrowserSession(_FakeManager(page), default_timeout=0.3)
    actions = BrowserActions(session)

    with pytest.raises(BrowserTimeoutError):
        await actions.perform("open", {"url": "https://example.test/stuck"})

    # The SAME event loop must still be able to do ordinary async work
    # immediately afterward - proves the loop was never corrupted/blocked.
    result = await asyncio.wait_for(asyncio.sleep(0, result="still alive"), timeout=1.0)
    assert result == "still alive"


# -- 4: cancellation interrupts an in-flight browser action ----------------


async def test_cancellation_interrupts_browser_action_during_navigation():
    page = _FakePage(hang=True)
    session = BrowserSession(_FakeManager(page), default_timeout=30.0)  # long bound on purpose
    actions = BrowserActions(session)

    task = asyncio.create_task(actions.perform("open", {"url": "https://example.test/stuck"}))
    await asyncio.sleep(0.1)  # let it actually start navigating
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    elapsed = time.monotonic() - started

    # Cancellation must be prompt - it must NOT wait out the 30s bound.
    assert elapsed < 2.0


# -- 5: crash / exception recovery - the worker loop survives one bad call --


async def test_browser_crash_recovery_worker_survives_exception():
    page = _FakePage(raise_on_goto=RuntimeError("simulated renderer crash"))
    session = BrowserSession(_FakeManager(page), default_timeout=2.0)
    actions = BrowserActions(session)

    with pytest.raises(RuntimeError, match="simulated renderer crash"):
        await actions.perform("open", {"url": "https://example.test/crash"})

    # A normal follow-up call on the SAME session/worker must still work -
    # one failed operation must never leave the runtime permanently stuck.
    page._raise_on_goto = None
    result = await actions.perform("open", {"url": "https://example.test/ok"})
    assert result["url"] == "https://example.test/ok"


# -- 6/7: real browser - no orphan process, repeated runs ------------------


async def test_no_orphan_process_after_real_timeout():
    psutil = pytest.importorskip("psutil")

    manager = PlaywrightManager()
    session = BrowserSession(manager, default_timeout=1.5)
    actions = BrowserActions(session)

    # Force a REAL browser/driver process to launch (allow a generous
    # bound for a cold launch), then sabotage navigation on the real page
    # so it can never complete on its own - this proves timeout + cleanup
    # against a genuine OS process tree, not just a fake double.
    page = await session.run(session.ensure_page, timeout=20.0)

    async def _hang(*args, **kwargs):
        await asyncio.Event().wait()

    page.goto = _hang

    with pytest.raises(BrowserTimeoutError):
        await actions.perform("open", {"url": "https://example.com/"}, timeout=1.5)

    await session.shutdown(timeout=10)

    remaining = [proc for proc in psutil.Process().children(recursive=True) if proc.is_running()]
    assert remaining == [], f"orphan browser/driver processes remained: {remaining}"


async def test_repeated_real_browser_runs_do_not_degrade():
    psutil = pytest.importorskip("psutil")

    manager = PlaywrightManager()
    session = BrowserSession(manager, default_timeout=15.0)
    actions = BrowserActions(session)

    for _ in range(3):
        result = await actions.perform("open", {"url": "https://example.com/"})
        assert result["status"] in (200, None)

    await session.shutdown(timeout=10)
    remaining = [proc for proc in psutil.Process().children(recursive=True) if proc.is_running()]
    assert remaining == [], f"orphan browser/driver processes remained: {remaining}"


# -- 8: mission context propagation -----------------------------------------


async def test_run_pack_forwards_context_into_mission_loop():
    captured: dict = {}

    class _FakeMissionLoop:
        async def run(self, goal, *, executor, verifier, step_permissions, context=None, **_ignored):
            captured["context"] = context
            captured["goal"] = goal
            return "mission-state"

    class _FakeState:
        mission_loop = _FakeMissionLoop()

    result = await mission_packs.run_pack(
        "deep-research", _FakeState(), goal="Extract the pricing page",
        context={"url": "https://example.com/pricing"},
    )

    assert result == "mission-state"
    assert captured["context"] == {"url": "https://example.com/pricing"}


# -- end-to-end: real MissionLoop + real browser, cancelled mid-navigation --


async def test_mission_cancellation_during_real_browser_navigation_leaves_no_orphan():
    psutil = pytest.importorskip("psutil")

    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    with tempfile.TemporaryDirectory(prefix="vyom-cancel-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = Settings(
            database_path=base / "e2e.db", skills_root=base / "skills", agents_root=base / "agents",
            audit_log_path=base / "audit.jsonl", secret_store_path=base / "secrets",
            artifacts_root=base / "artifacts", backup_root=base / "backups",
            tool_registry_path=Path(__file__).parent / "fixtures" / "tools_no_mcp.yaml",
        )
        with TestClient(create_app(settings)) as client:
            state = client.app.state

            # Force a real browser to launch, then sabotage navigation so
            # it is genuinely in flight (never completes on its own) when
            # cancellation arrives.
            page = await state.browser_session.run(state.browser_session.ensure_page, timeout=20.0)

            async def _hang(*args, **kwargs):
                await asyncio.Event().wait()

            page.goto = _hang

            pack = mission_packs.MISSION_PACKS["browser"]
            mission_id = "test-cancel-browser-mission"
            task = asyncio.create_task(state.mission_loop.run(
                pack.goal_template, executor=pack.executor_factory(state), verifier=pack.verifier,
                step_permissions=pack.step_permissions, context={"url": "https://example.com/pricing"},
                mission_id=mission_id,
            ))

            # Let the mission actually reach the "open" step and start
            # navigating before cancelling.
            await asyncio.sleep(0.5)
            started = time.monotonic()
            cancelled = state.mission_loop.cancel(mission_id)
            assert cancelled, "mission_loop.cancel() did not find the running mission"

            mission = await asyncio.wait_for(task, timeout=5.0)
            elapsed = time.monotonic() - started

            assert mission.status == "cancelled"
            assert elapsed < 5.0  # cancellation was prompt, not bounded only by the browser's own timeout

            # Checkpoint must persist so a later resume does not start over.
            checkpoint = await state.checkpoint_store.get(mission_id)
            assert checkpoint is not None
            assert checkpoint.task_state["status"] == "cancelled"

            # No further browser action executes after cancellation: the
            # step never reported completed/verified.
            assert not any(step.status == "completed" for step in mission.completed if "open" in step.title.lower())

        # App shutdown (still inside the outer temp-dir block, but after
        # the TestClient __exit__ above) must have cleanly closed the
        # browser - proven with a fresh, external process check.
        remaining = [proc for proc in psutil.Process().children(recursive=True) if proc.is_running()]
        assert remaining == [], f"orphan browser/driver processes remained after cancellation: {remaining}"

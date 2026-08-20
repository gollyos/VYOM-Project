"""P0 regression: the Brain event loop must never freeze for a blocking
desktop/UIA call, unrelated work must keep flowing while one is in
flight, and a mission cancelled mid-call must not have that call's result
reported as success.

These reproduce, at the DesktopTool/InputControlTool level, the family of
symptoms a synchronous pywinauto call on the async event loop produces:
unrelated commands stall, STOP stalls, and a cancelled mission can still
appear to "complete" after the fact.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.schemas.approvals import PermissionLevel
from app.tools.context import ToolContext
from app.tools.errors import ToolCancelledError
from app.tools_builtin.desktop import DesktopTool


def _context(task_id: str = "loop-test-task") -> ToolContext:
    return ToolContext(task_id=task_id, permission_level=PermissionLevel.L1, allowed_roots=())


class _Dumpable:
    """Stand-in for the pydantic schema objects DesktopController methods
    return (WindowInfo, SystemStatus, ...) - only `.model_dump` is used by
    DesktopTool."""

    def __init__(self, data: dict):
        self._data = data

    def model_dump(self, mode: str = "json") -> dict:
        return dict(self._data)


class SlowFakeController:
    """A desktop controller double whose calls block the calling thread
    for `delay` seconds, the way a real pywinauto/UIA wait or a
    keystroke-settle sleep does. Records wall-clock start/end per call so
    tests can prove (non-)overlap."""

    def __init__(self, delay: float = 0.4):
        self.delay = delay
        self.calls: list[tuple[str, float, float, int]] = []

    def _blocking(self, name: str, result: dict) -> _Dumpable:
        start = time.monotonic()
        time.sleep(self.delay)
        end = time.monotonic()
        self.calls.append((name, start, end, threading.get_ident()))
        return _Dumpable(result)

    def status(self):
        return self._blocking("status", {"platform": "windows"})

    def window_list(self):
        return []

    def window_focus(self, title: str):
        return self._blocking("window_focus", {"title": title, "focused": True})


@pytest.mark.asyncio
async def test_unrelated_async_work_is_not_blocked_by_a_slow_desktop_call():
    """Reproduction + fix proof for section 6.A: a slow UIA-shaped call
    must not delay an unrelated coroutine running on the same loop."""
    controller = SlowFakeController(delay=0.6)
    tool = DesktopTool(controller)
    context = _context()

    ticks: list[float] = []

    async def heartbeat() -> None:
        # Stands in for "what are you doing right now?" / STOP / a
        # WebSocket keepalive: cheap async work that must keep landing on
        # schedule regardless of what the desktop tool is doing.
        for _ in range(6):
            await asyncio.sleep(0.05)
            ticks.append(time.monotonic())

    started = time.monotonic()
    desktop_call = asyncio.create_task(tool.execute({"action": "status"}, context))
    heartbeat_call = asyncio.create_task(heartbeat())

    await asyncio.gather(desktop_call, heartbeat_call)

    # The heartbeat's 6th tick (~300ms of scheduled sleeps) must have
    # landed well before the 600ms blocking desktop call finished - i.e.
    # it was never stuck behind it. Before the fix this coroutine could
    # not even be scheduled until the synchronous controller call returned.
    assert ticks[-1] - started < 0.6, (
        f"unrelated async work was delayed until after the blocking call "
        f"finished (last tick at {ticks[-1] - started:.3f}s, blocking call "
        f"took ~0.6s) - the event loop was frozen"
    )
    # And the ticks arrived close to their intended cadence, not in one
    # burst released only once the desktop call returned.
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert all(gap < 0.3 for gap in gaps), f"ticks arrived in a burst, not on cadence: {gaps}"


@pytest.mark.asyncio
async def test_stop_equivalent_is_not_delayed_by_a_slow_desktop_call():
    """Reproduction + fix proof for section 6.B: cancelling the owning
    task's cancellation event ("Stop.") must be observed promptly, not
    only after a slow desktop call already in flight finishes."""
    controller = SlowFakeController(delay=0.8)
    tool = DesktopTool(controller)
    context = _context()

    desktop_call = asyncio.create_task(tool.execute({"action": "window_focus", "title": "Calculator"}, context))

    stop_observed_at: list[float] = []
    started = time.monotonic()

    async def send_stop_after(delay: float) -> None:
        await asyncio.sleep(delay)
        context.cancellation_event.set()
        stop_observed_at.append(time.monotonic())

    # The desktop call is expected to end in cancellation once STOP lands
    # mid-flight (see the dedicated cancellation test below) - what this
    # test is proving is *when* STOP itself gets to run, so exceptions
    # from the desktop call are not the point here.
    await asyncio.gather(desktop_call, send_stop_after(0.1), return_exceptions=True)

    # STOP itself must be processable ~0.1s in, not stuck for the full
    # 0.8s the desktop call takes - proving the loop kept scheduling other
    # coroutines while the blocking call ran on the worker thread.
    assert stop_observed_at[0] - started < 0.3


@pytest.mark.asyncio
async def test_two_desktop_calls_never_run_their_physical_action_concurrently():
    """Reproduction + fix proof for section 5/8: the Brain may run many
    things concurrently, but two physical desktop actions must never
    execute at the same moment (shared mouse/keyboard/focus)."""
    controller = SlowFakeController(delay=0.25)
    tool = DesktopTool(controller)

    async def call(title: str):
        return await tool.execute({"action": "window_focus", "title": title}, _context(f"task-{title}"))

    await asyncio.gather(call("Calculator"), call("Notepad"))

    assert len(controller.calls) == 2
    (_, start_a, end_a, thread_a), (_, start_b, end_b, thread_b) = controller.calls
    # Same worker thread both times - one dedicated, serialized thread.
    assert thread_a == thread_b
    # Non-overlapping intervals: whichever ran second did not start until
    # the first's physical action had actually finished.
    overlap = min(end_a, end_b) - max(start_a, start_b)
    assert overlap <= 0, f"two physical desktop actions overlapped by {overlap:.3f}s"


@pytest.mark.asyncio
async def test_a_cancelled_mission_does_not_report_a_late_desktop_result_as_success():
    """Reproduction + fix proof for section 4/8: a mission cancelled WHILE
    the physical action is running on the worker thread must see that
    action reported as cancelled, not completed - so nothing downstream
    (evidence, speech, memory) treats a superseded task's action as real
    success."""
    controller = SlowFakeController(delay=0.3)
    tool = DesktopTool(controller)
    context = _context()

    async def cancel_mid_flight():
        await asyncio.sleep(0.05)
        # Equivalent of the mission loop / task_runtime cancelling this
        # task's ToolContext out from under the still-running worker call.
        context.cancellation_event.set()

    with pytest.raises(ToolCancelledError):
        await asyncio.gather(
            tool.execute({"action": "window_focus", "title": "Calculator"}, context),
            cancel_mid_flight(),
        )

    # The physical action still ran for real (pywinauto calls cannot be
    # safely interrupted mid-flight) - what matters is that the tool layer
    # refused to report it as this (superseded) task's success.
    assert len(controller.calls) == 1

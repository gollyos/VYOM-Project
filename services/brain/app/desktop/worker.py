"""Serialized worker for blocking desktop / Windows UI Automation work.

VYOM's runtime has two planes. The async cognitive plane (voice, tasks,
missions, model calls, STOP, WebSocket events) must never stall - it is
what keeps the assistant responsive. Physical desktop control (pywinauto /
UI Automation, window management, clipboard) is a BLOCKING EFFECT plane:
it drives real OS state through synchronous APIs that have no async form,
and it touches a shared physical resource (the one mouse/keyboard/focus
the user has). Calling any of it directly from an `async def execute()`
freezes the entire event loop for the duration of the call - including
unrelated voice commands, STOP, other tasks, and WebSocket delivery - for
however long that blocking call takes (window waits, tree walks, settle
sleeps between keystrokes routinely run into multiple seconds).

Everything in this module exists to submit that blocking work to a
dedicated OS thread and await the result, so the event loop stays free
while it runs.

Why ONE thread, not `asyncio.to_thread()` per call
----------------------------------------------------
Two reasons, both hard requirements rather than tuning choices:

1. COM/thread affinity. pywinauto's `uia` backend goes through comtypes.
   comtypes initializes COM automatically only for the thread that first
   imports it - normally the Brain's event-loop thread, at process start
   (see comtypes/__init__.py: "COM is initialized automatically for the
   thread that imports this module for the first time... we have to
   initialize and uninitialize COM for every new thread... in which we are
   using COM"). `asyncio.to_thread()` runs on an arbitrary thread from
   Python's default ThreadPoolExecutor, which never did that import and
   never calls CoInitializeEx itself - every UIA call made there would
   fail. This module's worker thread performs that initialization once,
   itself, before doing anything else.

2. Serialization. Desktop interaction is a shared physical resource: two
   threads clicking/typing into two windows at the same moment is not
   concurrency, it is a race for keyboard focus. Routing every blocking
   desktop call through the SAME single thread makes serialization free -
   the thread's own work queue is the lock, with no separate lock object
   to acquire, forget, or deadlock on. Brain concurrency stays unlimited;
   simultaneous conflicting physical actions become structurally
   impossible.
"""

from __future__ import annotations

import asyncio
import functools
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def _init_com_apartment() -> None:
    """Give this worker thread its own COM apartment before any pywinauto
    call touches it, using the same threading mode pywinauto itself chose
    at import time (`sys.coinit_flags`, normally MTA) so this thread does
    not fight pywinauto's own apartment choice on the main thread."""
    if sys.platform != "win32":
        return
    try:
        import pythoncom

        pythoncom.CoInitializeEx(getattr(sys, "coinit_flags", 0))
    except Exception:
        # If this fails, the first real UIA call on this thread will raise
        # its own honest error - nothing here should mask that by pretending
        # the apartment exists when it does not.
        pass


#: Exactly one worker thread, process-wide. See module docstring: this is
#: what makes COM initialization a one-time cost and physical-action
#: serialization automatic rather than something every caller has to
#: remember to coordinate.
_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="vyom-desktop-uia", initializer=_init_com_apartment,
)


async def run_blocking(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a blocking desktop/UIA call on VYOM's dedicated desktop worker
    thread, off the Brain's async event loop.

    Every blocking desktop call - app launch, window control, clipboard,
    UIA tree walk, control invoke, browser-page automation, mouse/keyboard
    fallback - goes through this SAME thread, one at a time. The event loop
    stays free to keep handling unrelated voice commands, STOP, task
    lifecycle and WebSocket traffic while a slow physical action is in
    flight.

    If the awaiting task is cancelled, this coroutine raises
    `asyncio.CancelledError` immediately - it does not wait for the
    physical action to finish. The action itself keeps running to
    completion on the worker thread (Windows UI Automation calls cannot be
    safely interrupted mid-flight), but nothing in this process still
    awaits that result, so no evidence is recorded and no success is
    reported for it. The next queued desktop action still waits its turn
    behind it, which is correct: the physical desktop stays serialized even
    though the cognitive plane already moved on.
    """
    loop = asyncio.get_running_loop()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_EXECUTOR, call)

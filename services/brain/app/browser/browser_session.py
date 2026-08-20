from __future__ import annotations

import asyncio
import os
import threading
from contextlib import suppress
from typing import Any, Awaitable, Callable

from .playwright_manager import EDGE_CANDIDATE_PATHS, PlaywrightManager

DEFAULT_TIMEOUT_SECONDS = 20.0


def _known_browser_executables() -> set[str]:
    """Every executable path PlaywrightManager might actually launch:
    the two hardcoded Edge fallback candidates plus VYOM_BROWSER_EXECUTABLE
    if the operator overrode it. Used only to widen the orphan-cleanup
    safety net below (which is otherwise scoped to the Playwright install
    directory) - never to decide what CAN be launched."""
    known = {str(path).lower() for path in EDGE_CANDIDATE_PATHS}
    override = os.getenv("VYOM_BROWSER_EXECUTABLE")
    if override:
        known.add(override.lower())
    return known


class BrowserTimeoutError(RuntimeError):
    """A browser operation did not complete within its bound. The caller's
    event loop is never left waiting past this - the operation is
    abandoned (best-effort cancelled) rather than awaited indefinitely."""


class BrowserSession:
    """Owns the real Playwright page and the ONE dedicated worker thread
    every real browser call must run through (BrowserActions, BrowserVerifier,
    or any future caller that needs the live page).

    Root cause this exists to remove: a Playwright browser/page created on
    one asyncio event loop can never be safely awaited from a different
    loop - the underlying driver subprocess transport belongs to the loop
    that created it, and a caller on another loop waiting on it can hang
    forever with nothing able to interrupt it (confirmed reproducible:
    see VYOM_IMPLEMENTATION_STATUS.md, Phase 17.1 verification pass -
    Brain shutdown hung waiting to close a browser that had been touched
    from a different loop than the one running app shutdown). Routing
    every real call through one fixed worker loop removes that failure
    mode entirely, regardless of which loop happens to be calling in
    (Brain main loop, a MissionLoop step, a background automation, a
    test harness). The bounded `asyncio.wait_for` on the calling side
    guarantees the caller always regains control at the timeout even if
    the worker-side call is genuinely stuck.
    """

    def __init__(self, manager: PlaywrightManager, *, default_timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.manager = manager
        self.page: Any = None
        self._default_timeout = default_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._child_pids: set[int] = set()

    # -- worker lifecycle --------------------------------------------------

    def _ensure_worker(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return self._loop
            ready = threading.Event()
            holder: dict[str, asyncio.AbstractEventLoop] = {}

            def _run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                holder["loop"] = loop
                ready.set()
                loop.run_forever()

            thread = threading.Thread(target=_run, name="vyom-browser-worker", daemon=True)
            thread.start()
            if not ready.wait(timeout=10):
                raise RuntimeError("browser worker thread failed to start")
            self._thread = thread
            self._loop = holder["loop"]
            return self._loop

    async def run(self, factory: Callable[[], Awaitable[Any]], *, timeout: float | None = None) -> Any:
        """Runs factory() to completion on the dedicated worker loop,
        bounded by `timeout` (default_timeout if unset). Never runs the
        real Playwright call on the caller's own loop."""
        loop = self._ensure_worker()
        bound = self._default_timeout if timeout is None else timeout
        future = asyncio.run_coroutine_threadsafe(factory(), loop)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=bound)
        except asyncio.TimeoutError:
            future.cancel()
            self._kill_orphans()
            raise BrowserTimeoutError(f"browser operation did not complete within {bound:.0f}s") from None

    # -- real page/browser access - only ever awaited from inside run() ---

    async def ensure_page(self) -> Any:
        if self.page is None or self.page.is_closed():
            before = self._snapshot_pids()
            self.page = await self.manager.new_page()
            # The actual browser process is spawned by the Node driver and
            # can appear a moment after new_page() returns - a single
            # instantaneous diff can miss it. Poll briefly so the process
            # this session is responsible for is reliably tracked for
            # cleanup, without ever touching processes outside this
            # session's own lineage.
            for _ in range(5):
                self._child_pids |= self._snapshot_pids() - before
                await asyncio.sleep(0.1)
        return self.page

    async def close(self) -> None:
        if self.page is not None and not self.page.is_closed():
            with suppress(Exception):
                await self.page.close()
        self.page = None

    async def _close_all(self) -> None:
        await self.close()
        await self.manager.close()

    # -- process bookkeeping: defense in depth against orphaned browsers --

    @staticmethod
    def _snapshot_pids() -> set[int]:
        try:
            import psutil

            return {child.pid for child in psutil.Process().children(recursive=True)}
        except Exception:
            return set()

    def _kill_orphans(self) -> list[int]:
        """Best-effort but thorough: gives a graceful `playwright.stop()`
        a brief moment to actually finish exiting (it is async and may
        still be tearing down when this runs), then hard-kills whatever
        of ours is still alive.

        A real browser is a multi-process tree (renderer/GPU/network
        helper processes, each also named e.g. chrome.exe), not one PID,
        and killing a tracked parent does not cascade to its children on
        Windows. So this also sweeps any current child of THIS process
        whose executable either lives under the Playwright install
        directory or IS one of the known Edge-fallback executables
        PlaywrightManager itself can launch - scoped by exact executable
        path, never by name alone, so it can only ever catch processes
        Playwright/PlaywrightManager itself launched and can never touch
        an unrelated Brain subprocess (a terminal-tool run, git, a future
        MCP server, ...)."""
        killed: list[int] = []
        try:
            import psutil
        except Exception:
            return killed

        known_executables = _known_browser_executables()
        candidates: dict[int, Any] = {}
        for pid in list(self._child_pids):
            with suppress(Exception):
                proc = psutil.Process(pid)
                candidates[proc.pid] = proc
                for child in proc.children(recursive=True):
                    candidates[child.pid] = child

        with suppress(Exception):
            for child in psutil.Process().children(recursive=True):
                if child.pid in candidates:
                    continue
                with suppress(Exception):
                    exe = (child.exe() or "").lower()
                    if "ms-playwright" in exe or exe in known_executables:
                        candidates[child.pid] = child

        self._child_pids.clear()
        if not candidates:
            return killed

        _gone, alive = psutil.wait_procs(list(candidates.values()), timeout=2.0)
        for proc in alive:
            with suppress(Exception):
                proc.kill()
                killed.append(proc.pid)
        return killed

    # -- shutdown -----------------------------------------------------------

    async def shutdown(self, *, timeout: float | None = None) -> list[int]:
        """Bounded teardown: closes the page and the browser/Playwright
        driver on the worker loop, then stops the worker thread. Always
        hard-kills any tracked child process still alive afterward - no
        orphan is left behind on any path (success, timeout, crash, or
        cancellation)."""
        if self._thread is None:
            return []
        with suppress(BrowserTimeoutError):
            await self.run(self._close_all, timeout=timeout)
        loop, thread = self._loop, self._thread
        self._loop = None
        self._thread = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=5)
        return self._kill_orphans()

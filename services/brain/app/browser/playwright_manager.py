from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from typing import Any

# Fallback executable when Playwright's own bundled Chromium isn't
# installed. Exposed as a module constant (not inlined in start()) so
# BrowserSession's orphan-cleanup safety net can recognize an Edge-backed
# launch too, not just the Playwright-install-path case.
EDGE_CANDIDATE_PATHS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


class PlaywrightManager:
    def __init__(self):
        self._playwright: Any = None
        self._browser: Any = None
        # Whether the browser shows on the user's real screen. Default
        # headless=True (background, invisible). A task the user asked to
        # WATCH (see app/execution/visibility.py) flips this to False so a
        # REAL, visible browser window opens that they can see. Because the
        # browser is long-lived and shared, this is set BEFORE the task's
        # first browser action and applied on the next launch — it never
        # hot-swaps a running browser mid-session (a visible window can't
        # be silently made headless, and vice-versa without a reload).
        self.headless = True

    def set_headless(self, headless: bool) -> None:
        self.headless = headless

    def set_visibility(self, visibility: str) -> None:
        """'visual' -> a real on-screen browser window; 'background' (or
        anything else) -> headless. Central place the ActionEngine calls
        to make a task's browser run visibly or invisibly."""
        if visibility == "visual":
            self.headless = False
        else:
            self.headless = True

    async def start(self) -> Any:
        if self._browser is not None:
            return self._browser
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise RuntimeError("Python Playwright is not installed") from error
        self._playwright = await async_playwright().start()
        executable = os.getenv("VYOM_BROWSER_EXECUTABLE")
        if not executable:
            executable = next((str(path) for path in EDGE_CANDIDATE_PATHS if path.exists()), None)
        launch_options: dict[str, Any] = {"headless": self.headless}
        if executable:
            launch_options["executable_path"] = executable
        self._browser = await self._playwright.chromium.launch(**launch_options)
        return self._browser

    # A default Playwright page announces itself as HeadlessChrome with no
    # locale, which many sites answer with an interstitial instead of the
    # page. Presenting an ordinary desktop browser identity is normal
    # browser configuration - it is NOT an attempt to defeat bot
    # protection. When a site still refuses or serves a verification
    # challenge, VYOM reports that honestly and stops (see
    # ActionEngine._scrape_retailer / _web_browse); it never solves or
    # circumvents such a challenge.
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    async def new_page(self) -> Any:
        browser = await self.start()
        context = await browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=os.getenv("VYOM_BROWSER_USER_AGENT", self.DEFAULT_USER_AGENT),
            locale=os.getenv("VYOM_BROWSER_LOCALE", "en-IN"),
            timezone_id=os.getenv("VYOM_BROWSER_TIMEZONE", "Asia/Kolkata"),
        )
        return await context.new_page()

    async def close(self) -> None:
        if self._browser is not None:
            with suppress(Exception):
                await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            with suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

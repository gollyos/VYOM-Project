"""Tests for PlaywrightManager's browser-download fallback
(app/browser/playwright_manager.py) - needed because the VYOM
installer deliberately ships WITHOUT Playwright's bundled Chromium
(to keep the installer small; see scripts/prepare-bundled-runtimes.sh)
and instead relies on the Edge browser every real Windows machine
already has. On the rare machine missing both, a one-time
`playwright install chromium` should run automatically instead of the
browser feature just failing outright.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser.playwright_manager import PlaywrightManager, _looks_like_missing_browser


def test_looks_like_missing_browser_true_for_playwrights_own_error_message():
    error = Exception(
        "BrowserType.launch: Executable doesn't exist at "
        "C:\\Users\\x\\AppData\\Local\\ms-playwright\\chromium-1234\\chrome.exe\n"
        "Run 'playwright install' to download new browsers."
    )
    assert _looks_like_missing_browser(error) is True


def test_looks_like_missing_browser_false_for_an_unrelated_failure():
    """A permissions error or an already-running-browser lock must NOT
    trigger a doomed download attempt that would only mask the real
    error."""
    error = Exception("Target page, context or browser has been closed")
    assert _looks_like_missing_browser(error) is False


@pytest.mark.asyncio
async def test_start_falls_back_to_installing_chromium_when_no_browser_is_found():
    """The exact installer scenario: no Edge on this machine, no
    bundled Chromium either - start() must run the one-time install
    and retry, not just propagate the failure."""
    manager = PlaywrightManager()

    fake_browser = MagicMock()
    launch_calls = []

    async def fake_launch(**kwargs):
        launch_calls.append(kwargs)
        if len(launch_calls) == 1:
            raise Exception("Executable doesn't exist. Run 'playwright install' to download new browsers.")
        return fake_browser

    fake_chromium = MagicMock()
    fake_chromium.launch = fake_launch
    fake_playwright_instance = MagicMock()
    fake_playwright_instance.chromium = fake_chromium

    fake_playwright_context = MagicMock()
    fake_playwright_context.start = AsyncMock(return_value=fake_playwright_instance)

    with patch("app.browser.playwright_manager.EDGE_CANDIDATE_PATHS", []), \
         patch.object(PlaywrightManager, "_install_chromium", new=AsyncMock()) as install_mock, \
         patch("playwright.async_api.async_playwright", return_value=fake_playwright_context):
        result = await manager.start()

    install_mock.assert_awaited_once()
    assert len(launch_calls) == 2
    assert result is fake_browser


@pytest.mark.asyncio
async def test_start_does_not_attempt_a_download_for_an_unrelated_launch_failure():
    """A non-missing-browser failure must propagate as-is, never
    silently swallowed by an attempted (doomed) download."""
    manager = PlaywrightManager()

    async def fake_launch(**kwargs):
        raise Exception("Target page, context or browser has been closed")

    fake_chromium = MagicMock()
    fake_chromium.launch = fake_launch
    fake_playwright_instance = MagicMock()
    fake_playwright_instance.chromium = fake_chromium

    fake_playwright_context = MagicMock()
    fake_playwright_context.start = AsyncMock(return_value=fake_playwright_instance)

    with patch("app.browser.playwright_manager.EDGE_CANDIDATE_PATHS", []), \
         patch.object(PlaywrightManager, "_install_chromium", new=AsyncMock()) as install_mock, \
         patch("playwright.async_api.async_playwright", return_value=fake_playwright_context):
        with pytest.raises(Exception, match="has been closed"):
            await manager.start()

    install_mock.assert_not_awaited()

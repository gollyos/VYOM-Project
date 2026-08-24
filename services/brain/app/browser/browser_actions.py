from __future__ import annotations

from pathlib import Path
from typing import Any

from .browser_session import BrowserSession


class BrowserActions:
    def __init__(self, session: BrowserSession):
        self.session = session

    async def perform(self, action: str, inputs: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        """Bounded: always runs the real Playwright work on the session's
        dedicated worker loop (see BrowserSession), so a stuck navigation
        or action can never block the caller's own event loop - the
        caller regains control at `timeout` (or the session default)
        regardless of what happens worker-side."""
        return await self.session.run(lambda: self._perform(action, inputs), timeout=timeout)

    async def _perform(self, action: str, inputs: dict[str, Any]) -> dict[str, Any]:
        page = await self.session.ensure_page()
        if action in {"open", "navigate"}:
            response = await page.goto(str(inputs["url"]), wait_until="domcontentloaded", timeout=int(inputs.get("timeout_ms", 15_000)))
            return {"url": page.url, "title": await page.title(), "status": response.status if response else None}
        selector = str(inputs.get("selector", ""))
        if action == "read":
            locator = page.locator(selector or "body")
            return {"url": page.url, "title": await page.title(), "text": (await locator.inner_text())[:100_000]}
        if action == "extract":
            locator = page.locator(selector)
            texts = await locator.all_text_contents()
            # href is NOT text content - a caller needing the actual link
            # target (BrowserSearchProvider, matching each result to its
            # own URL rather than the search page itself) needs it
            # alongside the visible label, not instead of it. `.href` (the
            # resolved property, not getAttribute) so a relative or
            # protocol-relative markup href still comes back as a full
            # absolute URL the caller can actually use.
            hrefs = await locator.evaluate_all("(els) => els.map((el) => el.href || null)")
            return {"items": texts, "hrefs": hrefs, "url": page.url}
        if action == "click":
            await page.locator(selector).click()
        elif action == "type":
            await page.locator(selector).fill(str(inputs.get("text", "")))
        elif action == "select":
            await page.locator(selector).select_option(str(inputs.get("value", "")))
        elif action == "scroll":
            await page.mouse.wheel(float(inputs.get("x", 0)), float(inputs.get("y", 500)))
        elif action == "wait":
            await page.locator(selector).wait_for(state=str(inputs.get("state", "visible")), timeout=int(inputs.get("timeout_ms", 10_000)))
        elif action == "screenshot":
            path = Path(str(inputs["path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(path), full_page=bool(inputs.get("full_page", True)))
            return {"path": str(path), "url": page.url, "title": await page.title()}
        else:
            raise ValueError(f"Unsupported browser action: {action}")
        return {"url": page.url, "title": await page.title(), "action": action}

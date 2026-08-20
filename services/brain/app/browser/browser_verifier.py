from __future__ import annotations

from typing import Any

from .browser_session import BrowserSession


class BrowserVerifier:
    def __init__(self, session: BrowserSession):
        self.session = session

    async def verify(self, *, expected_text: str | None = None, expected_url: str | None = None,
                     timeout: float | None = None) -> dict[str, Any]:
        """Bounded: runs on the session's dedicated worker loop, same as
        BrowserActions - a stuck verification can never block the caller."""
        return await self.session.run(lambda: self._verify(expected_text, expected_url), timeout=timeout)

    async def _verify(self, expected_text: str | None, expected_url: str | None) -> dict[str, Any]:
        page = await self.session.ensure_page()
        text = await page.locator("body").inner_text()
        checks = {
            "page_loaded": bool(await page.title() or text.strip()),
            "text_match": expected_text.lower() in text.lower() if expected_text else True,
            "url_match": expected_url in page.url if expected_url else True,
        }
        return {"passed": all(checks.values()), "checks": checks, "url": page.url, "title": await page.title()}

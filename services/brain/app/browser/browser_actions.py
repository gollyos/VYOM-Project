from __future__ import annotations

from pathlib import Path
from typing import Any

from .browser_session import BrowserSession


class BrowserActions:
    def __init__(self, session: BrowserSession):
        self.session = session

    def set_visibility(self, visibility: str | None) -> None:
        """Tell the underlying PlaywrightManager whether the next browser
        launch should be HEADED (a real, on-screen window the user can
        watch) or HEADLESS (invisible/background). Passed through from the
        task's visibility decision (see app/execution/visibility.py); a
        None/background value is the safe headless default. Because the
        browser is long-lived, this is applied on the next launch, never
        hot-swapped mid-session."""
        if visibility and getattr(self.session.manager, "set_visibility", None):
            self.session.manager.set_visibility(visibility)

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
            raw_url = str(inputs["url"]).strip()
            import urllib.parse
            parsed = urllib.parse.urlparse(raw_url)
            if parsed.scheme not in {"http", "https"}:
                raise ValueError(f"URL guardrail: forbidden scheme '{parsed.scheme}'. Only http and https allowed.")
            if parsed.hostname in {"169.254.169.254", "metadata.google.internal"}:
                raise ValueError("URL guardrail: cloud metadata endpoints are blocked.")
            response = await page.goto(raw_url, wait_until="domcontentloaded", timeout=int(inputs.get("timeout_ms", 15_000)))
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
        elif action == "click_coordinate":
            x = float(inputs.get("x", 0))
            y = float(inputs.get("y", 0))
            await page.mouse.click(x, y)
            return {"url": page.url, "title": await page.title(), "action": "click_coordinate", "x": x, "y": y}
        elif action == "press_key":
            key = str(inputs.get("key", "Escape"))
            await page.keyboard.press(key)
            return {"url": page.url, "title": await page.title(), "action": "press_key", "key": key}
        elif action == "skip_youtube_ad":
            # 1. Check for standard YouTube Skip Ad buttons
            skipped = False
            skip_selectors = [
                ".ytp-ad-skip-button",
                ".ytp-ad-skip-button-modern",
                ".ytp-skip-ad-button",
                "button.ytp-ad-skip-button",
                ".ytp-ad-overlay-close-button",
            ]
            for sel in skip_selectors:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.click()
                    skipped = True
                    break
            # 2. If no button yet or unskippable timer, fast-forward ad video via DOM
            if not skipped:
                res = await page.evaluate("""() => {
                    const video = document.querySelector('video');
                    const adModule = document.querySelector('.ad-showing, .ad-interrupting, .video-ads');
                    if (video && adModule) {
                        video.muted = true;
                        video.playbackRate = 16.0;
                        video.currentTime = video.duration || 9999;
                        return { fast_forwarded: true };
                    }
                    return { ad_detected: !!adModule };
                }""")
                return {"url": page.url, "title": await page.title(), "ad_skipped": skipped, "details": res}
            return {"url": page.url, "title": await page.title(), "ad_skipped": True}
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
        elif action == "resolve_stuck_screen":
            # Inspect dialogs, alerts, overlays, CAPTCHA
            page_title = await page.title()
            current_url = page.url
            screenshot_path = Path("services/brain/data/artifacts/stuck_screen_probe.png")
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot_path), full_page=False)
            
            stuck_info = await page.evaluate("""() => {
                const bodyText = document.body ? document.body.innerText.slice(0, 2000) : '';
                const hasCaptcha = /captcha|recaptcha|verify you are human|cloudflare/i.test(bodyText);
                const hasModal = !!document.querySelector('.modal, [role="dialog"], .overlay, .popup');
                const hasLogin = /sign in|log in|enter password|2-step verification/i.test(bodyText);
                return { hasCaptcha, hasModal, hasLogin, snippet: bodyText.slice(0, 300) };
            }""")
            
            recommendation = "Normal page state."
            if stuck_info.get("hasCaptcha"):
                recommendation = "Boss, CAPTCHA / Human verification screen aayi hai. Boss ko verify karne bolo."
            elif stuck_info.get("hasLogin"):
                recommendation = "Boss, Login/Password required screen aayi hai. Authentication input chahiye."
            elif stuck_info.get("hasModal"):
                recommendation = "Boss, Popup/Modal detected. Dismiss karne ke liye Escape press kar rahe hain."
                await page.keyboard.press("Escape")
            
            return {
                "url": current_url,
                "title": page_title,
                "screenshot": str(screenshot_path),
                "stuck_analysis": stuck_info,
                "recommendation": recommendation,
            }
        elif action == "wait_for_user_otp":
            import asyncio
            timeout_ms = int(inputs.get("timeout_ms", 60_000))
            poll_interval_s = float(inputs.get("poll_interval_s", 2.0))
            start_url = page.url
            deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000.0)
            
            otp_status = "waiting"
            while asyncio.get_event_loop().time() < deadline:
                current_info = await page.evaluate("""() => {
                    const bodyText = document.body ? document.body.innerText : '';
                    const hasOtp = /enter code|verification code|one-time password|enter otp|2-step|sms code|authenticator/i.test(bodyText);
                    const otpInputs = document.querySelectorAll('input[type="tel"], input[name*="otp"], input[id*="otp"], input[autocomplete="one-time-code"]');
                    return { hasOtp: hasOtp || otpInputs.length > 0 };
                }""")
                if page.url != start_url or not current_info.get("hasOtp"):
                    otp_status = "completed"
                    break
                await asyncio.sleep(poll_interval_s)
                
            return {
                "url": page.url,
                "title": await page.title(),
                "action": "wait_for_user_otp",
                "status": otp_status,
                "message": "OTP verification completed." if otp_status == "completed" else "OTP wait timed out."
            }
        else:
            raise ValueError(f"Unsupported browser action: {action}")
        return {"url": page.url, "title": await page.title(), "action": action}


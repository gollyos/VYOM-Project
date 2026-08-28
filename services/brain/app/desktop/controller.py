from __future__ import annotations

from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

from app.execution.process_manager import ProcessManager

from .app_launcher import AppLauncher, ApplicationRegistry
from .clipboard import ClipboardController
from .notifications import NotificationDispatcher
from .schemas import AppStatus, ClipboardEntry, NotificationRequest, StartupStatus, SystemStatus, WindowInfo
from .startup import StartupController
from .system_status import SystemStatusService
from .window_manager import WindowManager


class DesktopController:
    """Facade over app launching, window management, clipboard, native
    notification dispatch policy, system status, startup, and VYOM-managed
    process control. Wrapped by the `desktop` tool adapter
    (tools_builtin/desktop.py) so every action still passes through the
    Permission Engine, evidence collector, and audit log -- this facade
    never bypasses them."""

    def __init__(
        self,
        registry: ApplicationRegistry,
        launcher: AppLauncher,
        windows: WindowManager,
        clipboard: ClipboardController,
        notifications: NotificationDispatcher,
        system_status: SystemStatusService,
        startup: StartupController,
        process_manager: ProcessManager,
        accessibility=None,
    ):
        self.registry = registry
        self.launcher = launcher
        self.windows = windows
        self.clipboard = clipboard
        self.notifications = notifications
        self.system_status = system_status
        self.startup = startup
        self.process_manager = process_manager
        # Windows UI Automation. Optional so existing tests that build a
        # controller directly keep working; when present it is the FIRST
        # choice for operating a visible application, above vision and far
        # above mouse/keyboard.
        self.accessibility = accessibility

    # -- Applications ----------------------------------------------------

    def resolve_app(self, text: str) -> str | None:
        """One place that turns "chrome"/"calculator kholo" into an app_id."""
        return self.registry.resolve(text)

    def app_open(self, app_id: str, *, args: list[str] | None = None) -> AppStatus:
        """`args` lets a launch carry a target - a URL for a browser, a path
        for an editor - so the user sees the thing they asked for rather
        than an empty application window."""
        # An app that is ALREADY running does not produce a new window -
        # Windows just reuses the existing one, which may be minimised or
        # buried behind VYOM. Launching in that case looks like success
        # while the user sees nothing, so an existing instance is brought
        # forward instead.
        existing = self.app_status(app_id)
        browser_state_before: dict[int, tuple[str, bool]] = {}
        target = str((args or [""])[0] or "").strip()
        if (app_id in {"chrome", "edge"} and self.accessibility is not None
                and self.accessibility.available):
            for browser_window in self.accessibility.browser_windows():
                try:
                    browser_state_before[browser_window.handle] = (
                        browser_window.window_text() or "",
                        bool(browser_window.is_active()),
                    )
                except Exception:
                    continue
        status = self.launcher.open(app_id, args=args)

        # A launch call returning is not the same as an application being
        # ON SCREEN. Wait for the real window, then put it in front of the
        # user. "Verified running" was true of a process the user could not
        # see - which is exactly what they reported as "it didn't open".
        app = self.registry.get(app_id)
        title = (app.window_title or app.name) if app else app_id
        if self.accessibility is not None and self.accessibility.available:
            window = self.accessibility.wait_for_window(title, timeout=12.0)
            if window is not None:
                if app_id in {"chrome", "edge"} and target:
                    window = self._bind_launched_browser_window(
                        target, browser_state_before, fallback=window)
                else:
                    self.bring_to_front(title)
                try:
                    return AppStatus(app_id=app_id, running=True,
                                     pid=window.process_id(), window_title=window.window_text())
                except Exception:
                    pass
        if existing.running:
            self.bring_to_front(title)
        return self.app_status(app_id) if status.pid is None else status

    def _bind_launched_browser_window(
        self,
        target: str,
        before: dict[int, tuple[str, bool]],
        *,
        fallback,
        timeout: float = 12.0,
    ):
        """Bind follow-up page actions to the browser window a launch changed.

        Chromium may reuse one of several existing windows or create a new
        one. Merely waiting for a window titled ``Chrome`` returns whichever
        window UI Automation enumerates first, which can be an unrelated
        ChatGPT tab. We instead observe the launch transition and retain the
        exact window handle that appeared, changed title, or became active.
        """
        accessibility = self.accessibility
        if accessibility is None:
            return fallback

        try:
            parsed = urlparse(target)
            host = (parsed.hostname or "").lower()
            parts = [part for part in host.split(".") if part and part != "www"]
            site_token = parts[0] if parts else ""
        except Exception:
            site_token = ""

        active_before = next(
            (handle for handle, (_title, active) in before.items() if active), None)
        deadline = time.monotonic() + timeout
        latest: list[Any] = []
        chosen = None
        while time.monotonic() < deadline:
            try:
                latest = accessibility.browser_windows()
            except Exception:
                latest = []

            new_windows = []
            changed_windows = []
            newly_active = []
            active_matching = []
            for candidate in latest:
                try:
                    handle = candidate.handle
                    candidate_title = candidate.window_text() or ""
                    active = bool(candidate.is_active())
                except Exception:
                    continue
                previous = before.get(handle)
                if previous is None:
                    new_windows.append(candidate)
                elif candidate_title != previous[0]:
                    changed_windows.append(candidate)
                if active and handle != active_before:
                    newly_active.append(candidate)
                if active and site_token and site_token in candidate_title.lower():
                    active_matching.append(candidate)

            # A new handle is strongest. A title transition is next: it is
            # direct evidence that the requested navigation affected that
            # window. Only then use foreground state as supporting evidence.
            pool = new_windows or changed_windows or newly_active or active_matching
            if pool:
                chosen = next(
                    (candidate for candidate in pool
                     if site_token and site_token in (candidate.window_text() or "").lower()),
                    None,
                ) or next(
                    (candidate for candidate in pool
                     if bool(candidate.is_active())),
                    pool[0],
                )
                break
            time.sleep(0.35)

        if chosen is None:
            # Timeout fallback is intentionally conservative. Prefer the
            # foreground window, then a target-matching one, before the
            # arbitrary wrapper returned by wait_for_window().
            chosen = next(
                (candidate for candidate in latest if bool(candidate.is_active())), None)
            if chosen is None and site_token:
                chosen = next(
                    (candidate for candidate in latest
                     if site_token in (candidate.window_text() or "").lower()), None)
            chosen = chosen or fallback

        try:
            chosen.set_focus()
        except Exception:
            pass
        try:
            accessibility.intended_window_handle = chosen.handle
        except Exception:
            pass
        return chosen

    def bring_to_front(self, title_contains: str) -> bool:
        """Restore and focus a window so the USER can actually see it.

        VYOM runs as a foreground desktop app, so anything it launches can
        land behind its own window - and a minimised app never comes
        forward on its own. Without this, "open Calculator" verified a
        live process while the user's screen did not change."""
        try:
            window = self.windows.restore(title_contains)
            if window.minimized:
                self.windows.restore(title_contains)
            self.windows.focus(title_contains)
            return True
        except Exception:
            return False

    def app_close(self, app_id: str, *, force: bool = False) -> AppStatus:
        return self.launcher.close(app_id, force=force)

    def app_focus(self, app_id: str) -> WindowInfo:
        app = self.registry.get(app_id)
        title = (app.window_title or app.name) if app else app_id
        return self.windows.focus(title)

    def app_status(self, app_id: str) -> AppStatus:
        """Liveness from the real process table, then the visible window."""
        status = self.launcher.status(app_id)
        app = self.registry.get(app_id)
        if app is None:
            return status
        title = (app.window_title or app.name).lower()
        matches = [window for window in self.windows.list() if title in window.title.lower()]
        if matches:
            return AppStatus(app_id=app_id, running=True, pid=status.pid, window_title=matches[0].title)
        return status

    # -- browser targets: app / window / profile / tab ---------------------

    def resolve_browser_profile(self, text: str) -> dict[str, str] | None:
        return self.registry.resolve_browser_profile(text)

    def open_browser_profile(self, text: str, *, app_id: str = "chrome",
                             url: str | None = None) -> dict[str, Any]:
        """Open the named signed-in profile, or say exactly why it cannot."""
        profile = self.registry.resolve_browser_profile(text)
        if profile is None:
            available = self.registry.browser_profiles()
            raise RuntimeError(
                "No browser profile on this PC matches that name. Available profiles: "
                + (", ".join(f"{item['name']} ({item['account']})" for item in available)
                   or "none found")
            )
        status = self.launcher.open_browser_profile(app_id, profile, url=url)
        if self.accessibility is not None and self.accessibility.available:
            self.accessibility.wait_for_window("Chrome", timeout=12.0)
            self.bring_to_front("Chrome")
        return {"app_id": app_id, "profile": profile, "pid": status.pid, "url": url}

    def list_browser_tabs(self) -> list[dict[str, Any]]:
        return self._require_accessibility().list_browser_tabs()

    # -- page-level operation of the visible browser ---------------------
    #
    # Every method observes the window title before and after, because
    # verification reads what ACTUALLY changed, not what was intended.

    def _browser_page_call(self, operation, **kwargs) -> dict[str, Any]:
        accessibility = self._require_accessibility()
        window = accessibility.browser_window()
        if window is None:
            raise RuntimeError("No visible browser window is open to operate on.")
        # INTENDED-CONTEXT CONTINUITY: every operation remembers the
        # window it used, and the next operation prefers THAT window -
        # the browser context the conversation is about. Without this,
        # each call re-picked whatever window happened to be foreground
        # (on a cluttered desktop that is some unrelated window), so
        # "type in the search box" landed on the wrong page entirely.
        try:
            accessibility.intended_window_handle = window.handle
        except Exception:
            pass
        title_before = ""
        try:
            title_before = window.window_text() or ""
        except Exception:
            pass
        result = operation(**kwargs)
        import time as _time

        _time.sleep(1.2)  # let navigation settle
        title_after = ""
        try:
            title_after = (accessibility.browser_window() or window).window_text() or ""
        except Exception:
            title_after = title_before
        return {
            "success": bool(getattr(result, "success", True)),
            "summary": getattr(result, "summary", str(result)),
            "value": getattr(result, "value", None),
            "title_before": title_before,
            "title_after": title_after,
        }

    def browser_page_click(self, target: str) -> dict[str, Any]:
        accessibility = self._require_accessibility()
        return self._browser_page_call(accessibility.browser_page_click, target=target)

    def browser_first_result(self) -> dict[str, Any]:
        accessibility = self._require_accessibility()
        return self._browser_page_call(accessibility.browser_first_result)

    def browser_page_type(self, value: str, *, enter: bool = True, field: str | None = None) -> dict[str, Any]:
        accessibility = self._require_accessibility()
        return self._browser_page_call(
            accessibility.browser_page_type, value=value, enter=enter, field=field)

    def browser_page_scroll(self, direction: str = "down", times: int = 3) -> dict[str, Any]:
        accessibility = self._require_accessibility()
        return self._browser_page_call(
            accessibility.browser_page_scroll, direction=direction, times=times)

    def browser_page_read(self) -> dict[str, Any]:
        return self._require_accessibility().browser_page_read()

    def browser_media_state(self) -> dict[str, Any]:
        """Playback state from the visible browser's accessibility tree."""
        return self._require_accessibility().browser_media_state()

    def browser_activate_audio_tab(self) -> dict[str, Any]:
        result = self._require_accessibility().activate_audio_tab()
        return {
            "success": bool(getattr(result, "success", True)),
            "summary": getattr(result, "summary", str(result)),
        }

    #: Well-known site names the user says conversationally, mapped to the
    #: URL a new tab should actually load.
    _SITE_URLS = {
        "youtube": "https://www.youtube.com",
        "gmail": "https://mail.google.com",
        "google": "https://www.google.com",
        "google drive": "https://drive.google.com",
        "google docs": "https://docs.google.com",
        "maps": "https://maps.google.com",
        "github": "https://github.com",
        "chatgpt": "https://chatgpt.com",
        "claude": "https://claude.ai",
        "whatsapp": "https://web.whatsapp.com",
        "linkedin": "https://www.linkedin.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "amazon": "https://www.amazon.in",
        "flipkart": "https://www.flipkart.com",
        "netflix": "https://www.netflix.com",
        "twitter": "https://x.com",
        "x.com": "https://x.com",
    }

    @classmethod
    def _normalise_tab_url(cls, text: str) -> str | None:
        """A URL, a known site name, or a search URL - never a guess."""
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        import re as _re

        if _re.match(r"^https?://", cleaned, _re.I):
            return cleaned
        if "." in cleaned and " " not in cleaned:
            return f"https://{cleaned}"
        lowered = cleaned.lower().strip(" .,!?।")
        if lowered in cls._SITE_URLS:
            return cls._SITE_URLS[lowered]
        for name, url in cls._SITE_URLS.items():
            if name in lowered:
                return url
        if lowered:
            return f"https://www.google.com/search?q={_re.quote(lowered)}"
        return None

    def open_browser_tab(self, url_text: str, *, app_id: str = "chrome") -> dict[str, Any]:
        """Open a NEW TAB in the browser window the user is already using.

        The physical session asked exactly this ("usi profile me new tab pe
        YouTube kholo") and got a NEW Chrome window every time, because the
        request was routed to a generic application launch. When a browser
        window exists, the tab is opened INSIDE it - focus, Ctrl+T, type,
        enter, all through the accessibility layer, no new window created.
        Only when NO browser window exists is an application launch the
        honest way for the tab to come into being, and the result says so."""
        import time as _time

        accessibility = self._require_accessibility()
        url = self._normalise_tab_url(url_text)
        if not url:
            raise RuntimeError("No page was named for the new tab.")

        windows_before = accessibility.browser_windows()
        tabs_before = accessibility.list_browser_tabs()
        launched_new_window = False
        active_title = ""
        if windows_before:
            # The window the user is LOOKING AT is the intended context -
            # with several windows open, the foreground one is the one the
            # "new tab" belongs in, not whichever the enumeration found
            # first.
            window = windows_before[0]
            try:
                active = [w for w in windows_before if w.is_active()]
                if active:
                    window = active[0]
            except Exception:
                pass
            window.set_focus()
            _time.sleep(0.2)
            window.type_keys("^t")
            _time.sleep(0.9)
            # Target Chrome's semantic address-bar Edit control. Raw
            # ``type_keys(url)`` interprets '+' in a query string as the
            # Shift modifier and can silently type a different URL.
            try:
                accessibility.intended_window_handle = window.handle
            except Exception:
                pass
            typed = accessibility.browser_page_type(url, enter=True, field="address")
            if not typed.success:
                raise RuntimeError(
                    f"The new tab opened, but its address bar could not be set: "
                    f"{typed.summary}")
            # OBSERVE, with retries: Chrome's tab strip is not exposed
            # through UIA the instant a tab is created, and the page takes
            # a moment to load. The window TITLE is the active tab's title
            # in Chrome, so it is direct evidence the new tab exists and
            # shows the requested page.
            import re as _re

            site_token = _re.sub(r"^https?://(www\.)?", "", url).split("/")[0].split(".")[0]
            deadline = _time.monotonic() + 12.0
            activated = False
            while _time.monotonic() < deadline:
                _time.sleep(1.0)
                try:
                    window.set_focus()
                    active_title = window.window_text() or ""
                except Exception:
                    active_title = ""
                # The new tab must actually be ACTIVE and showing the
                # site before this reports success - a tab-count bump
                # alone fired too early and left the previous tab (or the
                # user's own foreground work) as the live target.
                if site_token and site_token.lower() in active_title.lower():
                    activated = True
                    break
                tabs_after_probe = accessibility.list_browser_tabs()
                if len(tabs_after_probe) > len(tabs_before) and site_token.lower() in (
                        " ".join(tab.get("title", "") for tab in tabs_after_probe)).lower():
                    activated = True
                    break
            if not activated and site_token:
                raise RuntimeError(
                    f"The new tab did not activate - the browser stayed on "
                    f"'{(active_title or 'its previous tab')[:60]}'. This was not "
                    f"marked done.")
            if not activated and not active_title:
                _time.sleep(2.0)
                try:
                    active_title = window.window_text() or ""
                except Exception:
                    active_title = ""
        else:
            launched_new_window = True
            status = self.launcher.open(app_id, args=[url])
            if self.accessibility is not None and self.accessibility.available:
                self.accessibility.wait_for_window("Chrome", timeout=12.0)
                self.bring_to_front("Chrome")
            _time.sleep(1.0)
            try:
                fresh = accessibility.browser_windows()
                if fresh:
                    active_title = fresh[0].window_text() or ""
            except Exception:
                active_title = ""

        tabs_after = accessibility.list_browser_tabs()
        windows_after = accessibility.browser_windows()
        # The window this tab landed in is now the intended browser
        # context for subsequent page operations.
        try:
            accessibility.intended_window_handle = window.handle
        except Exception:
            pass
        return {
            "url": url,
            "tabs_before": len(tabs_before),
            "tabs_after": len(tabs_after),
            "windows_before": len(windows_before),
            "windows_after": len(windows_after),
            "launched_new_window": launched_new_window,
            "active_tab_title": active_title[:120],
            "tab_titles": [tab["title"] for tab in tabs_after][:10],
        }

    def close_browser_tab(self, target: str) -> dict[str, Any]:
        """Close one named TAB, never the browser."""
        accessibility = self._require_accessibility()
        before = accessibility.list_browser_tabs()
        result = accessibility.close_browser_tab(target)
        after = accessibility.list_browser_tabs()
        return {
            "success": result.success,
            "summary": result.summary,
            "tabs_before": len(before),
            "tabs_after": len(after),
            "remaining": [tab["title"] for tab in after][:10],
            "browser_still_running": bool(accessibility.browser_windows()),
        }

    def open_settings_page(self, page_text: str) -> dict[str, Any]:
        """Open a named Settings page through its own protocol URI.

        "Bluetooth settings kholo" resolves to `ms-settings:bluetooth` and
        Windows opens that exact page. No shell, no UI navigation, no
        model."""
        uri = self.registry.resolve_settings_page(page_text) or "ms-settings:"
        self.launcher._launch_shell("settings", uri)
        return {"app_id": "settings", "uri": uri}

    # -- Accessibility / semantic UI --------------------------------------
    #
    # This is the tier that makes a visible application a real environment
    # rather than a picture. Everything here is read from, or driven
    # through, Windows UI Automation.

    def _require_accessibility(self):
        if self.accessibility is None or not self.accessibility.available:
            raise RuntimeError(
                "Windows UI Automation is not available in this Brain environment; "
                "VYOM will not substitute pixel automation without saying so."
            )
        return self.accessibility

    def active_window(self) -> dict[str, Any] | None:
        """What the user is looking at RIGHT NOW, read fresh every call."""
        return self._require_accessibility().active_window()

    def inspect_ui_tree(self, *, app_id: str | None = None, title: str | None = None) -> list[dict[str, Any]]:
        accessibility = self._require_accessibility()
        resolved_title = title
        if app_id and not resolved_title:
            app = self.registry.get(app_id)
            resolved_title = (app.window_title or app.name) if app else app_id
        return [node.to_dict() for node in accessibility.inspect_ui_tree(title=resolved_title)]

    def find_control(self, target: str, *, app_id: str | None = None, title: str | None = None,
                     role: str | None = None) -> list[dict[str, Any]]:
        accessibility = self._require_accessibility()
        resolved_title = title
        if app_id and not resolved_title:
            app = self.registry.get(app_id)
            resolved_title = (app.window_title or app.name) if app else app_id
        return [node.to_dict() for node in accessibility.find_control(target, title=resolved_title, role=role)]

    def invoke_control(self, target: str, *, app_id: str | None = None, title: str | None = None) -> dict[str, Any]:
        accessibility = self._require_accessibility()
        resolved_title = self._title_for(app_id, title)
        result = accessibility.invoke_control(target, title=resolved_title)
        return {"success": result.success, "summary": result.summary}

    def invoke_sequence(self, targets: list[str], *, app_id: str | None = None,
                        title: str | None = None) -> dict[str, Any]:
        accessibility = self._require_accessibility()
        results = accessibility.invoke_sequence(targets, title=self._title_for(app_id, title))
        return {
            "success": all(item.success for item in results),
            "steps": [{"success": item.success, "summary": item.summary} for item in results],
        }

    def set_control_value(self, target: str, value: str, *, app_id: str | None = None,
                          title: str | None = None) -> dict[str, Any]:
        accessibility = self._require_accessibility()
        result = accessibility.set_control_value(target, value, title=self._title_for(app_id, title))
        return {"success": result.success, "summary": result.summary, "value": result.value}

    def get_control_value(self, target: str, *, app_id: str | None = None,
                          title: str | None = None) -> dict[str, Any]:
        accessibility = self._require_accessibility()
        result = accessibility.get_control_value(target, title=self._title_for(app_id, title))
        return {"success": result.success, "summary": result.summary, "value": result.value}

    def _title_for(self, app_id: str | None, title: str | None) -> str | None:
        if title:
            return title
        if not app_id:
            return None
        app = self.registry.get(app_id)
        return (app.window_title or app.name) if app else app_id

    # -- Windows -----------------------------------------------------------

    def window_list(self) -> list[WindowInfo]:
        return self.windows.list()

    def window_focus(self, title_contains: str) -> WindowInfo:
        return self.windows.focus(title_contains)

    def window_minimize(self, title_contains: str) -> WindowInfo:
        return self.windows.minimize(title_contains)

    def window_maximize(self, title_contains: str) -> WindowInfo:
        return self.windows.maximize(title_contains)

    def window_restore(self, title_contains: str) -> WindowInfo:
        return self.windows.restore(title_contains)

    def window_move(self, title_contains: str, x: int, y: int) -> WindowInfo:
        return self.windows.move(title_contains, x, y)

    def window_resize(self, title_contains: str, width: int, height: int) -> WindowInfo:
        return self.windows.resize(title_contains, width, height)

    # -- Clipboard -----------------------------------------------------------

    def clipboard_read(self) -> tuple[str, ClipboardEntry]:
        return self.clipboard.read()

    def clipboard_write(self, content: str) -> ClipboardEntry:
        return self.clipboard.write(content)

    def clipboard_clear(self) -> ClipboardEntry:
        return self.clipboard.clear()

    # -- Notifications -----------------------------------------------------------

    def notify(self, request: NotificationRequest) -> NotificationRequest | None:
        return self.notifications.dispatch(request)

    # -- System status -----------------------------------------------------------

    def status(self) -> SystemStatus:
        return self.system_status.snapshot()

    # -- Startup -----------------------------------------------------------

    def startup_enable(self) -> StartupStatus:
        return self.startup.enable()

    def startup_disable(self) -> StartupStatus:
        return self.startup.disable()

    def startup_status(self) -> StartupStatus:
        return self.startup.status()

    # -- Managed processes -----------------------------------------------------------

    def process_list_managed(self) -> list[dict[str, Any]]:
        return [self.process_manager.snapshot(pid) for pid in self.process_manager.processes]

    async def process_stop(self, process_id: int) -> dict[str, Any]:
        return await self.process_manager.stop(process_id)

    def process_status(self, process_id: int) -> dict[str, Any]:
        return self.process_manager.snapshot(process_id)

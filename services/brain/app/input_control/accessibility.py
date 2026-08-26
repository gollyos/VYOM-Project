from __future__ import annotations

import importlib.util
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

PYWINAUTO_AVAILABLE = importlib.util.find_spec("pywinauto") is not None
Application = None
Desktop = None


def _load_pywinauto() -> None:
    """Load Windows UI Automation only when a desktop task needs it."""
    global Application, Desktop
    if Application is not None and Desktop is not None:
        return
    from pywinauto import Application as PywinautoApplication, Desktop as PywinautoDesktop

    Application = PywinautoApplication
    Desktop = PywinautoDesktop


class AccessibilityUnavailableError(Exception):
    pass


class ElementNotFoundError(Exception):
    pass


@dataclass
class AccessibilityResult:
    success: bool
    summary: str
    value: str | None = None


@dataclass
class ControlNode:
    """One semantic control, as the accessibility layer sees it.

    This is deliberately small and flat. The whole point of reading the UI
    Automation tree is that VYOM already KNOWS what a control is - its
    role, its accessible name, its automation id, its value. None of that
    needs a model to interpret, and none of it should be sent to one."""

    role: str
    name: str
    automation_id: str
    value: str | None = None
    enabled: bool = True
    focused: bool = False
    depth: int = 0
    patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role, "name": self.name, "automation_id": self.automation_id,
            "value": self.value, "enabled": self.enabled, "focused": self.focused,
            "actions": self.patterns,
        }

    def matches(self, query: str) -> int:
        """Deterministic relevance for a plain-language target.

        Returns 0 for no match. Higher is better. An exact automation id or
        accessible name always outranks a substring hit, so "equals" picks
        the Equals button rather than the first control that merely
        contains the word."""
        wanted = query.strip().lower()
        if not wanted:
            return 0
        name = self.name.lower()
        auto = self.automation_id.lower()
        if auto == wanted or name == wanted:
            return 100
        if auto.rstrip("button") == wanted or name.rstrip(" .") == wanted:
            return 90
        if wanted in auto or wanted in name:
            return 60
        # Word-level overlap: "clear all memory" vs "clear memory".
        wanted_words = set(wanted.split())
        node_words = set(name.split()) | set(auto.split())
        overlap = len(wanted_words & node_words)
        if overlap and overlap == len(wanted_words):
            return 50
        return overlap * 10


#: Controls that are chrome, not content. Filtering these out before
#: anything else is what keeps a candidate set small enough to resolve
#: deterministically instead of shipping a 56-node tree to a model.
_CHROME_NAMES = {
    "system", "minimise", "minimize", "maximise", "maximize", "close",
    "restore", "titlebar", "system menu bar",
}
_CHROME_ROLES = {"TitleBar", "MenuBar", "ScrollBar", "Thumb", "Separator"}


class NativeAccessibilityController:
    """Accessibility-first native-app automation via Windows UI Automation.

    This is the FIRST-CHOICE tier for operating a visible application --
    above vision, above mouse/keyboard, and far above shelling out. Every
    method takes a semantic target ("the button called Equals", "the
    control whose automation id is num7Button"), never a screen
    coordinate, so it survives window moves, DPI changes and themes.

    Everything here reads or drives REAL UIA state. Nothing infers, and
    nothing reports success it did not observe."""

    #: How long to wait for a window to appear after a launch.
    WINDOW_TIMEOUT = 15.0
    #: Hard cap on tree walks. A pathological app (a huge web view hosted
    #: in a native frame) must not hang a mission.
    MAX_NODES = 400

    def _require_backend(self) -> None:
        if not PYWINAUTO_AVAILABLE:
            raise AccessibilityUnavailableError(
                "Windows UI Automation is unavailable (pywinauto is not installed in this "
                "Brain environment). VYOM will not silently fall back to pixel automation."
            )
        _load_pywinauto()

    @property
    def available(self) -> bool:
        return PYWINAUTO_AVAILABLE

    # -- window resolution -------------------------------------------------

    def _desktop(self):
        self._require_backend()
        return Desktop(backend="uia")

    def list_windows(self) -> list[dict[str, Any]]:
        """Every visible top-level window, with the process behind it."""
        windows: list[dict[str, Any]] = []
        for window in self._desktop().windows():
            try:
                if not window.is_visible():
                    continue
                title = window.window_text()
                if not title:
                    continue
                windows.append({
                    "title": title,
                    "class_name": window.class_name(),
                    "process_id": window.process_id(),
                    "focused": bool(window.has_keyboard_focus()) if hasattr(window, "has_keyboard_focus") else False,
                })
            except Exception:
                continue
        return windows

    def active_window(self) -> dict[str, Any] | None:
        """The window the user is actually looking at right now.

        Read fresh from the OS on every call. A cached answer is how VYOM
        ended up describing a window that had already been closed."""
        self._require_backend()
        try:
            import win32gui
            import win32process

            handle = win32gui.GetForegroundWindow()
            if not handle:
                return None
            title = win32gui.GetWindowText(handle)
            _, process_id = win32process.GetWindowThreadProcessId(handle)
            return {
                "title": title,
                "class_name": win32gui.GetClassName(handle),
                "process_id": process_id,
                "handle": handle,
                "focused": True,
            }
        except Exception:
            # win32gui is the precise answer; the UIA enumeration is the
            # honest fallback rather than a guess.
            for window in self.list_windows():
                if window.get("focused"):
                    return window
            return None

    def wait_for_window(self, title_contains: str, *, timeout: float | None = None):
        """Block until a window whose title contains `title_contains` is
        visible. Returns the wrapper, or None on timeout -- never a
        fabricated success."""
        deadline = time.monotonic() + (timeout if timeout is not None else self.WINDOW_TIMEOUT)
        wanted = title_contains.strip().lower()
        while time.monotonic() < deadline:
            match = self._find_window(wanted)
            if match is not None:
                return match
            time.sleep(0.35)
        return None

    def _find_window(self, wanted: str):
        for window in self._desktop().windows():
            try:
                title = window.window_text().lower()
                if not title or wanted not in title:
                    continue
                if window.is_visible():
                    return window
                # A window that MATCHES but is minimized is not "not
                # found" - it is legitimately open, just needing to be
                # restored before it can be driven. Windows Calculator
                # (and other UWP apps) commonly launches minimized/
                # cloaked depending on how it was started, and pywinauto
                # reports is_visible()=False for a minimized window even
                # though the app is genuinely running. Restoring it here
                # is what turns "app is open but hidden" into a usable
                # target, instead of silently failing the whole request.
                try:
                    if window.is_minimized():
                        window.restore()
                        time.sleep(0.2)
                        if window.is_visible():
                            return window
                except Exception:
                    pass
            except Exception:
                continue
        return None

    def _window_by_process(self, process_id: int):
        self._require_backend()
        app = Application(backend="uia").connect(process=process_id, timeout=5)
        return app.top_window()

    def _resolve_window(self, *, process_id: int | None = None, title: str | None = None):
        """One window-resolution path for every operation below."""
        if title:
            window = self.wait_for_window(title, timeout=6.0)
            if window is None:
                raise ElementNotFoundError(f"No visible window matching '{title}'")
            return window
        if process_id:
            return self._window_by_process(process_id)
        active = self.active_window()
        if active is None:
            raise ElementNotFoundError("No foreground window could be resolved")
        return self._window_by_process(int(active["process_id"]))

    # -- semantic tree -----------------------------------------------------

    def inspect_ui_tree(
        self,
        *,
        process_id: int | None = None,
        title: str | None = None,
        include_chrome: bool = False,
    ) -> list[ControlNode]:
        """Read the accessible control tree of ONE window.

        Returns semantic nodes, not a screenshot and not a blob of text.
        Window chrome (minimise/maximise/close/titlebar) is dropped unless
        asked for, because it is never what a user means."""
        window = self._resolve_window(process_id=process_id, title=title)
        nodes: list[ControlNode] = []
        try:
            descendants = window.descendants()
        except Exception as error:
            raise ElementNotFoundError(f"The window exposed no accessible tree: {error}") from error

        for element in descendants[: self.MAX_NODES]:
            try:
                info = element.element_info
                role = str(info.control_type or "")
                name = str(element.window_text() or "")
                automation_id = str(info.automation_id or "")
            except Exception:
                continue
            if not include_chrome:
                if role in _CHROME_ROLES:
                    continue
                if name.lower() in _CHROME_NAMES or automation_id in {"Minimize", "Maximize", "Close", "TitleBar"}:
                    continue
            if not name and not automation_id:
                continue
            nodes.append(ControlNode(
                role=role, name=name, automation_id=automation_id,
                value=self._value_of(element),
                enabled=self._safe(lambda: element.is_enabled(), True),
                focused=self._safe(lambda: element.has_keyboard_focus(), False),
                patterns=self._patterns(element),
            ))
        return nodes

    @staticmethod
    def _safe(call, default):
        try:
            return bool(call())
        except Exception:
            return default

    @staticmethod
    def _value_of(element) -> str | None:
        try:
            pattern = element.iface_value
            return str(pattern.CurrentValue)
        except Exception:
            return None

    @staticmethod
    def _patterns(element) -> list[str]:
        """Which real UIA actions this control actually supports.

        VYOM chooses Invoke vs SetValue vs Select from what the control
        declares, rather than trying one and hoping."""
        supported: list[str] = []
        for name, attribute in (
            ("invoke", "iface_invoke"), ("value", "iface_value"),
            ("selection_item", "iface_selection_item"), ("toggle", "iface_toggle"),
            ("expand_collapse", "iface_expand_collapse"), ("scroll", "iface_scroll"),
        ):
            try:
                getattr(element, attribute)
                supported.append(name)
            except Exception:
                continue
        return supported

    def find_control(
        self,
        target: str,
        *,
        process_id: int | None = None,
        title: str | None = None,
        role: str | None = None,
        limit: int = 5,
    ) -> list[ControlNode]:
        """Deterministically narrow a window's tree to a small candidate set.

        active window -> descendants -> role filter -> name/automation-id
        scoring -> top N. A model is consulted ONLY if this still leaves
        genuine ambiguity, which for real applications it almost never
        does."""
        nodes = self.inspect_ui_tree(process_id=process_id, title=title)
        if role:
            wanted_role = role.lower()
            nodes = [node for node in nodes if node.role.lower() == wanted_role]
        scored = [(node.matches(target), node) for node in nodes]
        hits = [node for score, node in sorted(scored, key=lambda pair: pair[0], reverse=True) if score > 0]
        return hits[:limit]

    def _element_for(self, window, node: ControlNode):
        """Re-resolve a ControlNode to a live element in the given window."""
        for element in window.descendants():
            try:
                info = element.element_info
                if node.automation_id and str(info.automation_id or "") == node.automation_id:
                    return element
                if not node.automation_id and str(element.window_text() or "") == node.name:
                    return element
            except Exception:
                continue
        raise ElementNotFoundError(f"Control '{node.name or node.automation_id}' is no longer present")

    def _resolve_one(self, target: str, *, process_id: int | None, title: str | None, role: str | None = None):
        window = self._resolve_window(process_id=process_id, title=title)
        candidates = self.find_control(target, process_id=process_id, title=title, role=role)
        if not candidates:
            raise ElementNotFoundError(
                f"No accessible control matching '{target}' exists in this window")
        return window, candidates[0], self._element_for(window, candidates[0])

    # -- semantic actions --------------------------------------------------

    def invoke_control(self, target: str, *, process_id: int | None = None,
                       title: str | None = None) -> AccessibilityResult:
        """Press/activate a control through its declared UIA action."""
        _window, node, element = self._resolve_one(target, process_id=process_id, title=title)
        if "invoke" in node.patterns:
            element.invoke()
        elif "toggle" in node.patterns:
            element.toggle()
        elif "selection_item" in node.patterns:
            element.select()
        else:
            # The control exposes no programmatic action. Clicking it is a
            # deliberate, declared step DOWN the fallback order, not a
            # silent substitution.
            element.click_input()
            return AccessibilityResult(
                True, f"Activated '{node.name or node.automation_id}' via input fallback "
                      "(the control exposes no UI Automation action)")
        return AccessibilityResult(True, f"Invoked '{node.name or node.automation_id}'")

    def set_control_value(self, target: str, value: str, *, process_id: int | None = None,
                          title: str | None = None) -> AccessibilityResult:
        _window, node, element = self._resolve_one(target, process_id=process_id, title=title)
        if "value" in node.patterns:
            element.set_edit_text(value) if hasattr(element, "set_edit_text") else element.set_text(value)
        else:
            element.set_focus()
            element.type_keys(value, with_spaces=True)
        readback = self._value_of(element)
        return AccessibilityResult(True, f"Set '{node.name or node.automation_id}' to {value!r}", value=readback)

    def get_control_value(self, target: str, *, process_id: int | None = None,
                          title: str | None = None) -> AccessibilityResult:
        _window, node, element = self._resolve_one(target, process_id=process_id, title=title)
        value = self._value_of(element)
        if value is None:
            value = str(element.window_text() or "")
        return AccessibilityResult(True, f"Read '{node.name or node.automation_id}'", value=value)

    def select_control(self, target: str, *, process_id: int | None = None,
                       title: str | None = None) -> AccessibilityResult:
        _window, node, element = self._resolve_one(target, process_id=process_id, title=title)
        element.select()
        return AccessibilityResult(True, f"Selected '{node.name or node.automation_id}'")

    def scroll_control(self, target: str, direction: str = "down", amount: int = 3, *,
                       process_id: int | None = None, title: str | None = None) -> AccessibilityResult:
        _window, node, element = self._resolve_one(target, process_id=process_id, title=title)
        element.scroll(direction, "line", amount)
        return AccessibilityResult(True, f"Scrolled '{node.name or node.automation_id}' {direction}")

    def focus_control(self, target: str, *, process_id: int | None = None,
                      title: str | None = None) -> AccessibilityResult:
        _window, node, element = self._resolve_one(target, process_id=process_id, title=title)
        element.set_focus()
        return AccessibilityResult(True, f"Focused '{node.name or node.automation_id}'")

    def invoke_sequence(self, targets: Iterable[str], *, process_id: int | None = None,
                        title: str | None = None, settle: float = 0.12) -> list[AccessibilityResult]:
        """Drive several controls in order within ONE window resolution.

        Used for things like a calculation, where re-resolving the window
        per keystroke is both slow and racy."""
        window = self._resolve_window(process_id=process_id, title=title)
        results: list[AccessibilityResult] = []
        nodes = self.inspect_ui_tree(process_id=process_id, title=title)
        for target in targets:
            scored = [(node.matches(target), node) for node in nodes]
            best = max(scored, key=lambda pair: pair[0], default=(0, None))
            if best[0] <= 0 or best[1] is None:
                results.append(AccessibilityResult(False, f"No control matching '{target}'"))
                continue
            node = best[1]
            try:
                element = self._element_for(window, node)
                if "invoke" in node.patterns:
                    element.invoke()
                else:
                    element.click_input()
                results.append(AccessibilityResult(True, f"Invoked '{node.name or node.automation_id}'"))
            except Exception as error:
                results.append(AccessibilityResult(False, f"'{target}' failed: {error}"[:160]))
            time.sleep(settle)
        return results

    # -- browser tabs ------------------------------------------------------
    #
    # A browser is not one object. "Chrome" is an APP, each Chrome window is
    # a WINDOW, each window belongs to a PROFILE, and each window holds
    # TABS showing PAGES. "Chrome me YouTube close karo" names a TAB;
    # "Chrome close karo" names the APP. Treating them alike closes the
    # whole browser and loses everything else the user had open.

    #: Chrome/Edge top-level window class.
    BROWSER_WINDOW_CLASS = "Chrome_WidgetWin_1"

    def browser_windows(self) -> list[Any]:
        """Visible Chromium-family browser windows."""
        found = []
        for window in self._desktop().windows():
            try:
                if window.class_name() == self.BROWSER_WINDOW_CLASS and window.window_text():
                    found.append(window)
            except Exception:
                continue
        return found

    # -- visible-browser PAGE operation ---------------------------------
    #
    # The page inside the user's browser is part of the desktop UI
    # Automation tree: Chromium exposes its document - links, buttons,
    # edit fields - to UIA clients. Everything here drives the page the
    # user can SEE, through the same accessibility layer that presses
    # Calculator buttons. No hidden browser, no pixels, no guessed
    # coordinates: elements are found by NAME, the way a human finds
    # them.

    #: Short names that are browser CHROME (navigation, menus), never
    #: page content - skipped when looking for "the first result".
    _BROWSER_CHROME_NAMES = frozenset({
        "home", "youtube home", "shorts", "subscriptions", "you", "history", "playlists",
        "your playlists", "search", "explore", "trending", "music",
        "films", "live", "gaming", "news", "sport", "courses",
        "back", "forward", "reload", "menu", "more options", "extensions",
        "notifications", "settings", "account", "profile", "sign in",
        "create", "notification", "categories", "library",
    })

    #: The window the operator last used (intended-context continuity).
    #: Set by the desktop controller; the browser_window() lookup prefers
    #: it so consecutive page operations stay in ONE browser context even
    #: when several windows are open.
    intended_window_handle: int | None = None

    def browser_window(self) -> Any | None:
        """The INTENDED browser window: the one the operator last used,
        else the foreground one, else the first found."""
        windows = self.browser_windows()
        if not windows:
            return None
        if self.intended_window_handle is not None:
            for window in windows:
                try:
                    if window.handle == self.intended_window_handle:
                        return window
                except Exception:
                    continue
        try:
            active = [w for w in windows if w.is_active()]
            if active:
                return active[0]
        except Exception:
            pass
        return windows[0]

    def _page_elements(self, window) -> list[tuple[str, str, Any]]:
        """(name, role, element) for the clickable/textual parts of the
        page, bounded so a huge page cannot hang the walk. The bound is
        TIME as much as nodes: a heavy page is allowed a larger scan as
        long as it stays inside the budget."""
        elements: list[tuple[str, str, Any]] = []
        deadline = time.monotonic() + 8.0
        try:
            for index, element in enumerate(window.descendants()):
                if index >= self.MAX_NODES * 3 or time.monotonic() > deadline:
                    break
                try:
                    role = str(element.element_info.control_type)
                    if role not in ("Hyperlink", "ListItem", "Button", "Edit", "Text", "Document"):
                        continue
                    name = (element.window_text() or "").strip()
                    if name:
                        elements.append((name, role, element))
                except Exception:
                    continue
        except Exception:
            return elements
        return elements

    def browser_page_read(self, *, limit: int = 25) -> dict[str, Any]:
        """What is on the page right now: its title plus the named
        elements (links, buttons, fields) a human would see."""
        window = self.browser_window()
        if window is None:
            raise AccessibilityUnavailableError("No visible browser window is open.")
        window.set_focus()
        title = window.window_text() or ""
        elements = self._page_elements(window)
        links = [name for name, role, _ in elements
                 if role in ("Hyperlink", "ListItem") and len(name) > 2][:limit]
        fields = [name for name, role, _ in elements if role == "Edit"][:5]
        return {"title": title, "links": links, "fields": fields}

    def browser_media_state(self) -> dict[str, Any]:
        """Read whether the visible browser is actually playing media.

        Chrome exposes ``Audio playing`` on the accessible name of a tab
        that is producing sound.  YouTube also exposes the player toggle as
        ``Pause (k)`` while playback is running.  Both signals come from the
        user's real visible browser; neither is inferred from a successful
        navigation or from a model response.
        """
        tabs = self.list_browser_tabs()
        playing_tabs = [
            tab for tab in tabs
            if "audio playing" in str(tab.get("title") or "").lower()
        ]
        if playing_tabs:
            raw_title = str(playing_tabs[0].get("title") or "")
            clean_title = re.split(
                r"\s+-\s+audio playing(?:\s+-\s+.*)?$", raw_title,
                maxsplit=1, flags=re.IGNORECASE,
            )[0].strip()
            return {
                "playing": True,
                "title": clean_title or raw_title,
                "source": "browser-tab-audio-state",
                "playing_tabs": [str(tab.get("title") or "") for tab in playing_tabs],
            }

        window = self.browser_window()
        if window is None:
            raise AccessibilityUnavailableError("No visible browser window is open.")
        title = window.window_text() or ""
        buttons = [
            name for name, role, _ in self._page_elements(window)
            if role == "Button"
        ]
        pause_buttons = [
            name for name in buttons
            if re.search(r"(?:^|\b)pause(?:\s*\([^)]+\))?(?:$|\b)", name, re.IGNORECASE)
        ]
        if pause_buttons:
            return {
                "playing": True,
                "title": title,
                "source": "page-pause-control",
                "control": pause_buttons[0],
                "playing_tabs": [],
            }
        play_buttons = [
            name for name in buttons
            if re.search(r"(?:^|\b)play(?:\s*\([^)]+\))?(?:$|\b)", name, re.IGNORECASE)
        ]
        if play_buttons:
            return {
                "playing": False,
                "title": title,
                "source": "page-play-control",
                "control": play_buttons[0],
                "playing_tabs": [],
            }
        return {
            "playing": None,
            "title": title,
            "source": "unobservable",
            "playing_tabs": [],
        }

    def browser_page_click(self, target: str) -> AccessibilityResult:
        """Click a named link/button on the visible page."""
        window = self.browser_window()
        if window is None:
            raise AccessibilityUnavailableError("No visible browser window is open.")
        window.set_focus()
        wanted = target.strip().lower()
        best_name, best_element, best_score = None, None, 0
        for name, role, element in self._page_elements(window):
            if role not in ("Hyperlink", "ListItem", "Button"):
                continue
            lowered = name.lower()
            if lowered == wanted:
                score = 100
            elif lowered.startswith(wanted):
                score = 60
            elif wanted in lowered:
                score = 40
            else:
                continue
            if score > best_score:
                best_name, best_element, best_score = name, element, score
        if best_element is None:
            return AccessibilityResult(
                False, f"No link or button called '{target}' is visible on this page")
        try:
            best_element.click_input()
            return AccessibilityResult(True, f"Clicked '{best_name[:60]}'")
        except Exception as error:
            return AccessibilityResult(False, f"Clicking '{best_name[:40]}' failed: {error}"[:160])

    def browser_first_result(self) -> AccessibilityResult:
        """Open the FIRST RESULT on the page - the first substantial
        content link, skipping the browser's own navigation chrome.
        Waits briefly for results to appear, because this is normally
        said right after a search whose page is still loading."""
        window = self.browser_window()
        if window is None:
            raise AccessibilityUnavailableError("No visible browser window is open.")
        window.set_focus()

        def qualifying(elements):
            fallback = None
            for name, role, element in elements:
                if role not in ("Hyperlink", "ListItem"):
                    continue
                lowered = name.lower().strip()
                if len(lowered) < 12:
                    continue  # nav labels are short; results carry titles
                if lowered in self._BROWSER_CHROME_NAMES:
                    continue
                if lowered.startswith(("search", "filter", "show more", "related searches")):
                    continue
                try:
                    automation_id = str(element.element_info.automation_id or "").lower()
                except Exception:
                    automation_id = ""
                # Chromium exposes actual YouTube result titles with the
                # semantic id ``video-title``. Prefer that over traversal
                # order, where the first long hyperlink is often the
                # YouTube logo or a subscribed-channel item in the sidebar.
                if automation_id == "video-title":
                    return name, element
                if automation_id in {"logo", "channel-thumbnail"}:
                    continue
                if lowered.startswith("go to channel"):
                    continue
                if fallback is None:
                    fallback = (name, element)
            return fallback

        found = qualifying(self._page_elements(window))
        deadline = time.monotonic() + 8.0
        while found is None and time.monotonic() < deadline:
            time.sleep(1.0)
            found = qualifying(self._page_elements(window))
        if found is None:
            return AccessibilityResult(False, "No result link is visible on this page")
        name, element = found
        try:
            element.click_input()
            return AccessibilityResult(True, f"Opened the first result: '{name[:70]}'")
        except Exception as error:
            return AccessibilityResult(False, f"Opening the first result failed: {error}"[:160])

    def browser_page_type(self, value: str, *, enter: bool = True,
                          field: str | None = None) -> AccessibilityResult:
        """Type into the page's search/entry field - the page's own Edit
        control if it has one, the browser's address bar otherwise."""
        window = self.browser_window()
        if window is None:
            raise AccessibilityUnavailableError("No visible browser window is open.")
        window.set_focus()
        target_element = None
        label = "the address bar"
        for name, role, element in self._page_elements(window):
            if role != "Edit":
                continue
            lowered = name.lower()
            if field and field.lower() in lowered:
                target_element, label = element, f"the '{name[:30]}' field"
                break
            if "search" in lowered or "query" in lowered:
                target_element, label = element, f"the '{name[:30]}' field"
                break
            if target_element is None:
                target_element, label = element, f"the '{name[:30]}' field"
        try:
            target_element.set_focus()
            time.sleep(0.1)
            # UIA's value pattern writes literal text. ``type_keys`` treats
            # characters such as ``+``, ``^`` and ``%`` as keyboard
            # modifiers, which corrupted search URLs (``?q=...+...``) and
            # left Chrome on the previous ChatGPT tab. Prefer the semantic
            # Edit control's value API; keep a literal-key fallback only for
            # controls that do not implement it.
            try:
                target_element.set_edit_text(value)
            except Exception:
                escaped = {
                    "{": "{{}", "}": "{}}", "+": "{+}", "^": "{^}",
                    "%": "{%}", "~": "{~}", "(": "{(}", ")": "{)}",
                }
                literal = "".join(escaped.get(char, char) for char in value)
                target_element.type_keys(literal, with_spaces=True)
            readback = self._value_of(target_element) or value
            if enter:
                time.sleep(0.1)
                target_element.type_keys("{ENTER}")
            return AccessibilityResult(
                True, f"Typed {value!r} into {label}", value=str(readback))
        except Exception as error:
            return AccessibilityResult(False, f"Typing into {label} failed: {error}"[:160])

    def browser_page_scroll(self, direction: str = "down", times: int = 3) -> AccessibilityResult:
        """Scroll the visible page with the keyboard, on the window the
        user is looking at."""
        window = self.browser_window()
        if window is None:
            raise AccessibilityUnavailableError("No visible browser window is open.")
        window.set_focus()
        key = "{PGDN}" if direction.lower().startswith("d") else "{PGUP}"
        for _ in range(max(1, min(times, 10))):
            try:
                window.type_keys(key)
            except Exception as error:
                return AccessibilityResult(False, f"Scrolling failed: {error}"[:160])
            time.sleep(0.15)
        return AccessibilityResult(
            True, f"Scrolled the page {direction} {times} time(s) in "
                  f"'{(window.window_text() or '')[:50]}'")

    @staticmethod
    def _tab_close_button(item) -> Any | None:
        """A browser tab's own close button, if it has one."""
        try:
            for child in item.descendants():
                if "close" in (child.window_text() or "").lower():
                    return child
        except Exception:
            return None
        return None

    @classmethod
    def _tab_strip_items(cls, window) -> list[Any]:
        """The window's REAL tabs.

        A bare descendant scan for TabItem also returns PAGE CONTENT:
        YouTube's "All / AI / Gaming" filter chips are TabItem controls
        sitting in a tablist, and acting on one would click the wrong
        thing entirely. Two conditions separate them:

          1. the parent is the `Tab` strip, and
          2. the item has its own close button.

        The second is the reliable one - a browser tab can always be
        closed, a page filter chip never can - and unlike Chrome's
        internal container id it does not change between versions."""
        items = []
        for element in window.descendants():
            try:
                if str(element.element_info.control_type) != "TabItem":
                    continue
                parent = element.parent()
                if parent is None or str(parent.element_info.control_type) != "Tab":
                    continue
                if cls._tab_close_button(element) is None:
                    continue
                items.append(element)
            except Exception:
                continue
        return items

    def list_browser_tabs(self) -> list[dict[str, Any]]:
        """Every open tab across every visible browser window."""
        tabs: list[dict[str, Any]] = []
        for window in self.browser_windows():
            try:
                window_title = window.window_text()
                process_id = window.process_id()
            except Exception:
                continue
            for item in self._tab_strip_items(window):
                try:
                    tabs.append({
                        "title": item.window_text(),
                        "window": window_title,
                        "process_id": process_id,
                    })
                except Exception:
                    continue
        return tabs

    @staticmethod
    def _tab_score(title: str, target: str) -> int:
        """How well a tab title answers what the user named.

        Exact beats prefix beats substring, so "close the YouTube tab"
        prefers a tab actually called "YouTube" over a video whose title
        merely mentions it."""
        title_lower, wanted = title.lower(), target.strip().lower()
        if not wanted:
            return 0
        # Chrome appends live status to the accessible name ("- Audio
        # playing - Memory usage - 372 MB"); it is not part of the page.
        cleaned = title_lower.split(" - audio playing")[0].split(" - memory usage")[0].strip()
        if cleaned == wanted:
            return 100
        if cleaned.startswith(wanted) or cleaned.endswith(wanted):
            return 80
        if wanted in cleaned.split(" - "):
            return 70
        if wanted in cleaned:
            return 40
        return 0

    def find_browser_tabs(self, target: str) -> list[dict[str, Any]]:
        """Tabs matching a named page, best first."""
        scored = [
            (self._tab_score(tab["title"], target), tab)
            for tab in self.list_browser_tabs()
        ]
        return [tab for score, tab in sorted(scored, key=lambda pair: pair[0], reverse=True)
                if score > 0]

    def close_browser_tab(self, target: str) -> AccessibilityResult:
        """Close ONE named tab, leaving every other tab and the browser
        itself untouched. Verified by re-reading the tab strip."""
        before = self.list_browser_tabs()
        matches = self.find_browser_tabs(target)
        if not matches:
            return AccessibilityResult(
                False, f"No open tab matches '{target}'. Open tabs: "
                       + ", ".join(tab["title"][:40] for tab in before[:6]))

        wanted = matches[0]
        for window in self.browser_windows():
            for item in self._tab_strip_items(window):
                try:
                    title = item.window_text()
                except Exception:
                    continue
                # Re-MATCH rather than compare titles exactly: Chrome
                # rewrites a tab's accessible name while it is open
                # ("- Audio playing", "- Memory usage - 372 MB"), so the
                # string captured a moment ago is often already stale and
                # an equality test simply never fires.
                if self._tab_score(title, target) <= 0:
                    continue
                if title != wanted["title"] and self._tab_score(title, target) < self._tab_score(
                    wanted["title"], target
                ):
                    continue
                closed = False
                close_button = self._tab_close_button(item)
                if close_button is not None:
                    try:
                        close_button.invoke()
                        closed = True
                    except Exception:
                        closed = False
                if not closed:
                    try:
                        item.select()
                        window.type_keys("^w")
                        closed = True
                    except Exception:
                        pass
                if not closed:
                    continue
                time.sleep(1.2)
                after = self.list_browser_tabs()
                # Same staleness caveat on the way out: verify by MATCH,
                # not by the exact string, or a tab whose title merely
                # changed would look like it had closed.
                still_there = any(self._tab_score(tab["title"], target) > 0 for tab in after)
                if still_there:
                    return AccessibilityResult(
                        False, f"a tab matching '{target}' is still open after the close")
                survived = len(after)
                return AccessibilityResult(
                    True,
                    f"Closed the tab '{wanted['title'][:50]}'. {survived} other tab(s) "
                    f"and the browser itself are untouched.",
                    value=str(survived),
                )
        return AccessibilityResult(False, f"The tab '{target}' could not be operated")

    # -- backwards-compatible surface --------------------------------------
    #
    # The existing InputControlTool calls these by process id + label. They
    # now run on the semantic resolver above rather than an exact-title
    # child_window lookup, which only ever matched a perfectly spelled
    # label and raised for everything else.

    def find_element(self, process_id: int, label: str) -> Any:
        window = self._window_by_process(process_id)
        candidates = self.find_control(label, process_id=process_id)
        if not candidates:
            raise ElementNotFoundError(f"No element labeled '{label}' was found")
        return self._element_for(window, candidates[0])

    def click(self, process_id: int, label: str) -> AccessibilityResult:
        return self.invoke_control(label, process_id=process_id)

    def set_value(self, process_id: int, label: str, value: str) -> AccessibilityResult:
        return self.set_control_value(label, value, process_id=process_id)

    def read_text(self, process_id: int, label: str) -> AccessibilityResult:
        return self.get_control_value(label, process_id=process_id)

    def invoke(self, process_id: int, label: str) -> AccessibilityResult:
        return self.invoke_control(label, process_id=process_id)

    def select_menu_item(self, process_id: int, menu_path: str) -> AccessibilityResult:
        self._require_backend()
        app = Application(backend="uia").connect(process=process_id, timeout=5)
        app.top_window().menu_select(menu_path)
        return AccessibilityResult(True, f"Selected menu item '{menu_path}'")

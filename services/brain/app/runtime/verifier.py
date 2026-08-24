from __future__ import annotations

import re as _re

from app.schemas.results import ExecutionResult, VerificationResult
from app.schemas.tasks import Task

#: Words that carry no identifying weight when checking that the thing the
#: user asked to be searched for is what actually got searched for.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "to", "of", "on", "in", "my", "me",
    "please", "karo", "kar", "do", "kijiye", "open", "search", "find", "browser",
    "pe", "par", "me", "mein", "aur", "hai", "ka", "ki", "ke", "wala", "sa",
})


class Verifier:
    async def verify(self, task: Task, result: ExecutionResult) -> VerificationResult:
        evidence: list[str] = []
        if not result.response.strip():
            return VerificationResult(passed=False, score=0, summary="Response was empty")
        evidence.append("Non-empty response")

        tool_verification = result.structured_data.get("verification")
        if isinstance(tool_verification, dict) and tool_verification.get("passed") is False:
            return VerificationResult(
                passed=False,
                score=0.2,
                summary=str(tool_verification.get("summary", "Tool verification failed")),
                evidence=list(tool_verification.get("evidence", [])),
            )

        if result.ui_composition is not None:
            composition = result.ui_composition
            required = {"schemaVersion", "id", "mode", "label", "objects", "sequence"}
            if not required.issubset(composition):
                return VerificationResult(
                    passed=False,
                    score=0.2,
                    summary="UI composition is missing required fields",
                    evidence=evidence,
                )
            object_ids = {item.get("id") for item in composition.get("objects", [])}
            referenced = {
                object_id
                for step in composition.get("sequence", [])
                for object_id in step.get("objectIds", [])
            }
            if None in object_ids or not referenced.issubset(object_ids):
                return VerificationResult(
                    passed=False,
                    score=0.3,
                    summary="UI composition references invalid objects",
                    evidence=evidence,
                )
            evidence.append("UI composition structure valid")

        if task.metadata.get("force_verification_failure"):
            return VerificationResult(
                passed=False,
                score=0.1,
                summary="Verification failure injected for test",
                evidence=evidence,
            )

        evidence.extend(result.evidence)
        return VerificationResult(
            passed=True,
            score=1,
            summary="Result passed structural and completion checks",
            evidence=evidence,
        )


# ======================================================================
# Postconditions
# ======================================================================
#
# "Tool returned success" is NOT completion. A mission that made five
# tool calls and verified two was still being reported COMPLETE, so VYOM
# announced work it had not done. Completion now requires the requested
# effect to be observable in the world:
#
#   requested goal + execution evidence + postcondition = COMPLETE
#
# A postcondition that cannot be satisfied yields PARTIAL or FAILED. It
# never yields COMPLETE.

def _process_running(*names: str) -> tuple[bool, str]:
    """True when any of these image names is currently running."""
    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil ships with the Brain
        return False, "psutil unavailable"
    wanted = {name.lower() for name in names if name}
    for process in psutil.process_iter(["name"]):
        current = (process.info.get("name") or "").lower()
        if current in wanted or any(current.startswith(w.split(".")[0]) for w in wanted):
            return True, f"process {current} (pid {process.pid})"
    return False, f"no process matching {sorted(wanted)}"


class PostconditionVerifier:
    """Checks that the requested effect actually happened.

    Every check reads REAL state - the process table, the filesystem, the
    captured exit code - never the model's description of what it did."""

    #: Image names a registered app_id is expected to produce.
    APP_PROCESSES = {
        "calculator": ("calc.exe", "calculatorapp.exe", "application frame host.exe"),
        "chrome": ("chrome.exe",),
        "notepad": ("notepad.exe",),
        "paint": ("mspaint.exe", "paintstudio.view.exe"),
        "file_explorer": ("explorer.exe",),
        "terminal": ("windowsterminal.exe", "wt.exe"),
        "vscode": ("code.exe",),
    }

    def check(self, *, kind: str, context: dict) -> tuple[bool, str]:
        """Return (satisfied, human readable evidence)."""
        handler = getattr(self, f"_check_{kind}", None)
        if handler is None:
            return True, f"no postcondition defined for {kind}"
        try:
            return handler(context)
        except Exception as error:  # a failing check never fakes success
            return False, f"postcondition check errored: {error}"[:200]

    # -- concrete postconditions ---------------------------------------

    #: Window titles a registered app_id is expected to put on screen.
    APP_WINDOWS = {
        "calculator": "calculator", "chrome": "chrome", "notepad": "notepad",
        "paint": "paint", "file_explorer": "explorer", "terminal": "terminal",
        "vscode": "visual studio code", "settings": "settings", "edge": "edge",
    }

    def _check_app_launch(self, context: dict) -> tuple[bool, str]:
        """"Open the app" means the user can SEE it.

        A live process is necessary but not sufficient: VYOM verified
        `calculatorapp.exe` was running while the user was telling it
        "ओपन नहीं हुआ, मेरे को नहीं शो हो रहा" - the window existed behind
        VYOM's own. Completion now requires a visible window."""
        app_id = str(context.get("app_id", "")).lower()
        candidates = self.APP_PROCESSES.get(app_id, (f"{app_id}.exe",))
        running, detail = _process_running(*candidates)
        if not running:
            return False, detail

        wanted = self.APP_WINDOWS.get(app_id, app_id.replace("_", " "))
        try:
            from app.desktop.window_manager import WindowManager

            windows = WindowManager().list()
        except Exception:
            # No window backend: the process check is the honest best
            # available evidence, and it is reported as exactly that.
            return True, f"{detail} (window visibility could not be checked)"
        visible = [
            window for window in windows
            if wanted in window.title.lower() and not window.minimized
        ]
        if visible:
            return True, f"visible window '{visible[0].title}'"
        buried = [window for window in windows if wanted in window.title.lower()]
        if buried:
            return False, f"'{buried[0].title}' exists but is minimised, so it is not on screen"
        return False, f"{detail}, but no visible window matching '{wanted}' is on screen"

    def _check_app_close(self, context: dict) -> tuple[bool, str]:
        app_id = str(context.get("app_id", "")).lower()
        candidates = self.APP_PROCESSES.get(app_id, (f"{app_id}.exe",))
        running, detail = _process_running(*candidates)
        return (not running), ("still running: " + detail if running else "process is gone")

    def _check_file_write(self, context: dict) -> tuple[bool, str]:
        from pathlib import Path

        path = Path(str(context.get("path", "")))
        if not path.exists():
            return False, f"{path} does not exist"
        size = path.stat().st_size
        if context.get("expect_content") and size == 0:
            return False, f"{path} exists but is empty"
        return True, f"{path} exists ({size} bytes)"

    def _check_command(self, context: dict) -> tuple[bool, str]:
        exit_code = context.get("exit_code")
        if exit_code is None:
            return False, "the process did not report an exit code (it may still be running)"
        return exit_code == 0, f"exit code {exit_code}"

    def _check_automation_scheduled(self, context: dict) -> tuple[bool, str]:
        automation_id = str(context.get("automation_id", "")).strip()
        if not automation_id or not context.get("persisted"):
            return False, "the automation was not read back from durable storage"
        if not context.get("next_run_at"):
            return False, f"{automation_id} has no next run time"
        return True, f"{automation_id} is durably stored for {context['next_run_at']}"

    def _check_research(self, context: dict) -> tuple[bool, str]:
        sources = context.get("sources") or []
        characters = int(context.get("characters") or 0)
        if not sources and characters < 200:
            return False, "no source content was retrieved"
        return True, f"{len(sources)} source(s), {characters} characters of retrieved content"

    def _check_system_query(self, context: dict) -> tuple[bool, str]:
        measurement = context.get("measurement")
        if measurement in (None, "", {}, []):
            return False, "no real measurement was returned"
        return True, "measurement captured from the system API"

    def _check_window_visible(self, context: dict) -> tuple[bool, str]:
        """A window the USER can see must actually exist."""
        wanted = str(context.get("title", "")).lower()
        if not wanted:
            return False, "no window title to verify"
        try:
            from app.desktop.window_manager import WindowManager

            titles = [window.title for window in WindowManager().list()]
        except Exception as error:
            return False, f"the window list could not be read: {error}"[:160]
        matches = [title for title in titles if wanted in title.lower()]
        if matches:
            return True, f"visible window '{matches[0]}'"
        return False, f"no visible window matching '{wanted}'"

    def _check_control_value(self, context: dict) -> tuple[bool, str]:
        """The application's own UI must show the expected value."""
        expected = str(context.get("expected", "")).strip()
        actual = str(context.get("actual", "")).strip()
        if not expected:
            return False, "no expected value was supplied"
        normalised = actual.replace(",", "").replace("Display is", "").strip()
        if normalised == expected or expected in normalised:
            return True, f"the application displays {actual!r}"
        return False, f"the application displays {actual!r}, not {expected!r}"

    def _check_tab_closed(self, context: dict) -> tuple[bool, str]:
        """The named tab is gone AND the browser survived.

        Closing the whole browser would also make the tab disappear, so
        "the tab is gone" alone is not proof the right thing happened."""
        if not context.get("browser_still_running"):
            return False, "the tab went away because the whole browser closed"
        remaining = [str(title).lower() for title in context.get("remaining") or []]
        page = str(context.get("page", "")).lower()
        if page and any(page in title for title in remaining):
            return False, f"a '{page}' tab is still open"
        before, after = context.get("tabs_before"), context.get("tabs_after")
        if isinstance(before, int) and isinstance(after, int) and after >= before:
            return False, f"tab count did not drop ({before} -> {after})"
        return True, f"'{page}' closed; {after} other tab(s) and the browser intact"

    def _check_profile_open(self, context: dict) -> tuple[bool, str]:
        """The REQUESTED profile is the one that opened."""
        profile = context.get("profile") or {}
        if not profile.get("directory"):
            return False, "no browser profile was actually resolved"
        window = context.get("window")
        if not window:
            return False, f"the {profile.get('name')} profile produced no visible window"
        return True, f"{profile.get('name')} ({profile.get('account')}) is open"

    def _check_requested_target(self, context: dict) -> tuple[bool, str]:
        """SERVICE CONSTRAINTS ARE HARD.

        If the user said Amazon, the evidence must be Amazon. Substituting
        Flipkart because Amazon blocked automation is a different task with
        a different answer, and reporting it as success is a lie about
        which service was consulted."""
        requested = [str(item).lower() for item in (context.get("requested") or []) if item]
        if not requested:
            return True, "no specific service was named"
        visited = " ".join(str(item).lower() for item in (context.get("visited") or []))
        missing = [name for name in requested if name not in visited]
        if missing:
            return False, (
                f"you asked for {', '.join(requested)} but nothing was retrieved from "
                f"{', '.join(missing)}"
            )
        return True, f"evidence came from the requested service(s): {', '.join(requested)}"

    def _check_observation(self, context: dict) -> tuple[bool, str]:
        """A question about the world was answered from a real reading."""
        count = int(context.get("observed") or 0)
        if count <= 0:
            return False, "nothing was actually observed"
        return True, f"{count} item(s) read directly from the operating system"

    #: Pages that are served INSTEAD of a result. Landing on one of these
    #: means the search did not happen, however healthy the HTTP status
    #: was. VYOM reported "is all website like a yeh chrome off kar do aur"
    #: as a completed search while the browser was parked on
    #: google.com/sorry - an anti-bot interstitial with no results on it.
    _NON_RESULT_PAGES = (
        "/sorry/", "captcha", "unusual traffic", "are you a robot",
        "consent.google", "accounts.google.com/signin", "/challenge",
        "access denied", "403 forbidden", "enable javascript to continue",
    )

    def _check_search_performed(self, context: dict) -> tuple[bool, str]:
        """A search GOAL needs the search to have actually run.

        Launching the browser is not searching. Landing on a CAPTCHA wall
        is not searching. Both were being reported as completed searches."""
        visited = " ".join(
            str(item) for item in (context.get("visited") or []) if item
        ).lower()
        if not visited.strip():
            return False, "the browser was opened but no search or navigation was observed"

        for marker in self._NON_RESULT_PAGES:
            if marker in visited:
                return False, (
                    f"the browser landed on an anti-bot/consent interstitial "
                    f"({marker.strip('/')}), so no search result was actually reached"
                )

        query = str(context.get("query", "")).strip().lower()
        if not query:
            return True, "a navigation was observed"
        # Any distinctive term of the query must appear in what was
        # actually visited. "search Luxora Designs" that navigated to
        # google.com with no query is not the requested search.
        terms = [
            term for term in _re.split(r"[^\wऀ-ॿ]+", query)
            if len(term) > 2 and term not in _STOPWORDS
        ]
        if not terms:
            return True, "a navigation was observed"
        hit = [term for term in terms if term in visited]
        if not hit:
            return False, (
                f"nothing matching '{query}' appears in what was actually "
                f"opened, so the requested search was not performed"
            )
        return True, f"the search for '{query}' reached a real result page"

    def _check_media_playing(self, context: dict) -> tuple[bool, str]:
        """"Play a song" means audio is PLAYING, not that a page opened."""
        if context.get("playing") is True:
            return True, f"playback is running ({context.get('title') or 'media'})"
        if context.get("playing") is False:
            return False, (
                "the media page opened but playback did not start "
                "(the browser blocked autoplay)"
            )
        return False, (
            "a page was opened but no playback state could be observed, so "
            "it is not known whether anything is actually playing"
        )

    def _check_page_action(self, context: dict) -> tuple[bool, str]:
        """A click/scroll on the visible page really happened.

        Evidence is the OBSERVED world, in two acceptable forms: the
        window title changed (navigation occurred), or the actuation ran
        through the element's own UIA pattern with the before/after
        titles recorded (non-navigating actions like scrolling)."""
        summary = str(context.get("summary") or "").strip()
        title_before = str(context.get("title_before") or "")
        title_after = str(context.get("title_after") or "")
        if not summary:
            return False, "no record of the page action was observed"
        if title_before and title_after and title_before != title_after:
            return True, f"the page changed to '{title_after[:60]}'"
        if title_after:
            return True, f"{summary[:120]} (page: '{title_after[:50]}')"
        return True, summary[:160]

    def _check_new_tab(self, context: dict) -> tuple[bool, str]:
        """A new TAB in the existing browser - not a new browser window.

        The physical session asked for a new tab and got a whole new
        Chrome window every time, so the constraint is now verified, not
        assumed: when a browser window already existed, the window count
        must not grow. Two observations can prove the tab: the tab strip
        count rising, or - when Chrome has not exposed the strip yet -
        the WINDOW TITLE, which in Chrome is always the active tab's
        title."""
        before, after = context.get("tabs_before"), context.get("tabs_after")
        windows_before = context.get("windows_before")
        windows_after = context.get("windows_after")
        if (isinstance(windows_before, int) and windows_before > 0
                and isinstance(windows_after, int) and windows_after > windows_before):
            return False, (
                f"a new browser window was created ({windows_before} -> {windows_after}) "
                f"instead of a tab in the browser already being used"
            )
        windows_stable = (
            isinstance(windows_before, int) and isinstance(windows_after, int)
            and windows_after <= windows_before
        )
        counts_known = isinstance(before, int) and isinstance(after, int)
        # before == 0 while a browser window already existed is Chrome's
        # tab strip not having been exposed yet at the moment of reading
        # (a real window cannot have zero tabs) - that is the one case the
        # count is not trustworthy and the title fallback below still
        # applies. Any OTHER known count (including 0 -> N, or a real
        # non-zero count that did not rise) is authoritative.
        strip_not_exposed_yet = (
            counts_known and before == 0
            and isinstance(windows_before, int) and windows_before > 0
        )
        if counts_known and not strip_not_exposed_yet:
            if after > before:
                if windows_before == 0:
                    return True, (
                        f"no browser was open, so one opened with the tab ({after} tab(s))"
                    )
                return True, f"a new tab was opened in the existing browser ({before} -> {after} tabs)"
            # The tab count IS known and trustworthy, and did NOT rise: no
            # new tab was created, full stop. The physical-mic session
            # showed this exact state ("tabs_before": 2, "tabs_after": 2)
            # still get reported VERIFIED_COMPLETE by falling through to
            # the title check below, off a title that had nothing to do
            # with what was asked for ('ChatGPT', 'Claude' - other
            # windows/tabs, not the requested page). A known, unchanged,
            # non-zero count is proof, not an ambiguous case the title
            # fallback should ever override.
            return False, f"tab count did not increase ({before} -> {after}); no new tab was created"
        # Tab count genuinely UNAVAILABLE, or the strip-not-exposed-yet
        # placeholder above - only here is the window title the sole
        # signal, and only when no new window opened.
        tab_title = str(context.get("tab_title") or "").strip()
        if tab_title and windows_stable:
            return True, f"the active tab in the existing browser reads '{tab_title[:60]}'"
        if context.get("launched_new_window"):
            return False, (
                "a separate browser window was launched instead of a new tab "
                "in the browser you were already using"
            )
        return False, "no evidence that a new tab was created"


# ======================================================================
# Goal verification
# ======================================================================
#
# LAW 1/2/3. A model may not declare a real-world action successful; only
# a goal-level postcondition may produce VERIFIED_COMPLETE; and tool
# success is not goal success.
#
# The Verifier above is STRUCTURAL - it checks that a result is
# well-formed. That is necessary and nowhere near sufficient: a
# well-formed result saying "Mission finished: 5 tool calls, 2 verified"
# passed it cleanly while the user's actual goal had not been met.
#
# GoalVerifier answers the only question that matters: did the thing the
# user asked for actually happen, as observed in the world?

#: intent -> (postcondition kind, how to build its context from the result)
#: An intent that is ABSENT from this map has no world-effect to verify
#: (a question, a conversation); an intent that is present may NEVER
#: complete without its postcondition passing.
GOAL_POSTCONDITIONS: dict[str, str] = {
    "app_launch": "app_launch",
    "app_close": "app_close",
    "browser_tab_close": "tab_closed",
    "browser_tab_open": "new_tab",
    "browser_profile_open": "profile_open",
    "browser_page_click": "page_action",
    "browser_first_result": "page_action",
    "browser_page_scroll": "page_action",
    "browser_page_type": "control_value",
    "play_media": "media_playing",
    "browser_page_read": "observation",
    "recover_visibility": "window_visible",
    "web_browse": "requested_target",
    "shop_compare": "requested_target",
    "settings_open": "window_visible",
    "screen_observe": "observation",
    "ui_interact": "control_value",
    "create_project_file": "file_write",
    "run_command": "command",
    "run_tests": "command",
    "schedule_command": "automation_scheduled",
}


# ======================================================================
# GoalFrame
# ======================================================================
#
# A spoken command is not a tool call. "Open the Chrome browser and search
# Luxora Designs" is TWO required effects, and VYOM was reporting it
# complete after satisfying the first one - Chrome opened, nothing
# searched, "verified" at score 1.0.
#
# A GoalFrame is the structured form of what the user actually asked for:
# the set of effects that must ALL be observable before the goal is met.
# It is derived DETERMINISTICALLY - no model call, no second planner. It
# recognises the families of request that have a real-world effect and
# stays silent (empty) on everything else, so conversation is unaffected.

#: (regex, effect kind, how to pull the effect's target out of the match)
_EFFECT_PATTERNS: list[tuple[str, str]] = [
    # search / find something on the web
    (r"\b(?:search|google|find|dhundo|khojo|search\s+karo)\b\s*(?:for\s+)?(?P<target>.{2,80})", "search"),
    (r"(?P<target>[\w.\-]{2,60})\s+(?:search|khoj)\s*(?:karo|kar do|kijiye)", "search"),
    # open a named browser profile
    (r"\b(?P<target>[\w .\-]{2,40}?)\s*(?:profile|प्रोफाइल)\b", "profile"),
    # a new tab specifically
    (r"\bnew\s*tab\b|\bnayi?\s*tab\b|\bनई\s*टैब\b", "new_tab"),
    # play media
    (r"\b(?:play|bajao|baja do|chalao|चलाओ|बजाओ)\b", "media"),
]

_APP_WORDS = {
    "chrome": "chrome", "क्रोम": "chrome", "browser": "chrome", "ब्राउज़र": "chrome",
    "calculator": "calculator", "कैलकुलेटर": "calculator", "calc": "calculator",
    "notepad": "notepad", "edge": "edge", "explorer": "file_explorer",
    "youtube": "chrome", "यूट्यूब": "chrome",
}

_OPEN_WORDS = ("open", "launch", "kholo", "khol do", "start", "chalu karo", "ओपन", "खोलो")


class GoalFrame:
    """What the user asked for, as a set of effects that must all hold."""

    def __init__(self, request: str):
        self.request = request or ""
        self.effects: list[dict] = []
        self.targets: list[str] = []

    def require(self, kind: str, **context) -> None:
        self.effects.append({"kind": kind, "context": context})

    def __bool__(self) -> bool:
        return bool(self.effects)

    def describe(self) -> str:
        return ", ".join(effect["kind"] for effect in self.effects) or "no world-effect"


def derive_goal_frame(request: str) -> GoalFrame:
    """Turn a spoken command into the effects that must be observable.

    Conservative by construction: an unrecognised sentence yields an empty
    frame, which verifies exactly as it does today. This never INVENTS a
    requirement - it only makes explicit the ones the words plainly state."""
    frame = GoalFrame(request)
    text = (request or "").strip()
    lowered = text.lower()
    if not text:
        return frame

    # -- an app the user wants open -------------------------------------
    #
    # Gated by an actual IMPERATIVE, not by the word "open": the physical
    # session's "अभी जो क्रोम की प्रोफाइल ओपन है उसमें..." ("the Chrome
    # profile that IS open...") is a DESCRIPTION of state, and it required
    # an app_launch effect - which the planner then satisfied by opening a
    # profile nobody asked for.
    from app.runtime.task_classifier import requests_external_action

    if requests_external_action(text):
        for word, app_id in _APP_WORDS.items():
            if word in lowered:
                frame.require("app_launch", app_id=app_id)
                frame.targets.append(app_id)
                break

    # -- a named browser profile ----------------------------------------
    profile_match = _re.search(r"(?:^|\s)([\w][\w .\-]{1,38}?)\s*(?:profile|प्रोफाइल)\b",
                               text, _re.IGNORECASE)
    if profile_match:
        wanted = profile_match.group(1).strip()
        # Strip leading command words AND REFERENTS that are not part of
        # a name. "isi profile me new tab kholo" means "in the SAME
        # profile" - a reference to the context, not a profile called
        # "Isi"; requiring profile_open for it failed a goal that had
        # actually succeeded.
        for word in ("open", "kholo", "chrome", "pe", "par", "me", "mein", "the", "ओपन",
                     "isi", "usi", "is", "us", "same", "meri", "mere", "apni", "wali"):
            wanted = _re.sub(rf"^{_re.escape(word)}(?:\s+|$)", "", wanted, flags=_re.IGNORECASE)
        if wanted and wanted.lower() not in {"a", "the", "this"}:
            frame.require("profile_open", requested_profile=wanted)
            frame.targets.append(wanted)

    # -- a search that must actually run --------------------------------
    # Devanagari verbs included: the physical session's "YouTube सर्च करो"
    # produced no search effect at all, so opening Chrome alone verified
    # as the whole goal.
    search_match = _re.search(
        r"\b(?:search|google|find|dhundo|khojo)\b\s*(?:for\s+|the\s+|about\s+|out\s*about\s+|out\s+|up\s+|more\s*about\s+)?(?P<target>.{2,80})"
        r"|(?:सर्च|खोज|ढूंढो|ढूँढो)\s*(?:करो|कर\s*दो|कीजिए)?\s*(?P<target2>.{2,80})",
        text, _re.IGNORECASE)
    if not search_match:
        search_match = _re.search(
            r"(?P<target>[\w.\- ]{3,60}?)\s+(?:search|सर्च|khoj|खोज)\s*(?:karo|करो|kar do|कर दो|kijiye)",
            text, _re.IGNORECASE)
    if search_match:
        query = (search_match.group("target") or search_match.group("target2") or "").strip(" .,!?।")
        query = _re.sub(r"\b(karo|kar do|kijiye|please|now|करो|कर दो)\b\s*$", "", query,
                        flags=_re.IGNORECASE).strip(" .,!?।")
        # "find" is ambiguous: "find restaurants" is a web search, but
        # "find all python files" is a LOCAL filesystem find served by the
        # filesystem tool (which reports "found N matches") - never the
        # browser. Requiring `search_performed` for the latter made a
        # successful local `find *.py` fail verification with the
        # nonsensical "browser was opened but no search observed". Detect
        # the filesystem case from the SEARCH TARGET alone (a file noun or
        # a file extension). Devanagari "फाइल"/"फोल्डर" are deliberately
        # omitted: "फाइल" is a substring of "प्रोफाइल" (profile) and the
        # regex \b does not split Devanagari compound words.
        filesystem_find = _re.search(
            r"\bfiles?\b|\bfilename\b|\bfolder\b|\bdirectory\b|\.[a-z]{1,5}\b",
            query, _re.IGNORECASE,
        )
        # "what is X" / "who is X" / "define X" / "explain X" questions name
        # the REAL search subject. A trailing phrasal verb ("find out and
        # remember it", "tell me about", "learn") is NOT the subject — it is
        # the follow-up instruction about an already-named topic. Prefer the
        # knowledge-question subject (e.g. "Model Context Protocol") over the
        # fragment after "find out" / "learn" / "tell me about", so the
        # verifier demands a search of the actual topic and not of the
        # instruction words themselves.
        subject_match = _re.search(
            r"(?:what is|what are|who is|who was|what's|define|definition of|explain|about)\s+(?P<subject>[\w\-.() ]{2,60}?)"
            r"(?:\?|\.|,|,?\s*and\s*remember|,?\s*and\s*learn|$)",
            text, _re.IGNORECASE,
        )
        if subject_match and not filesystem_find:
            real_subject = subject_match.group("subject").strip(" .,!?।")
            real_subject = _re.sub(r"^(?:the|a|an)\s+", "", real_subject, flags=_re.IGNORECASE).strip()
            if len(real_subject.split()) <= 6:  # a topic, not a full sentence
                query = real_subject
        # "find out about X" / "learn about X" / "find out X": strip any
        # leading phrasal-verb connector that the optional group above
        # failed to consume, so the SEARCH TARGET becomes "X" and not
        # "out about X" / "up X".
        query = _re.sub(r"^(?:out\s*about\s+|out\s+|about\s+|up\s+|more\s*about\s+|more\s+)",
                        "", query, flags=_re.IGNORECASE).strip(" .,!?।")
        # A trailing "and remember it"/"and learn X" clause is the follow-up
        # instruction, not the subject — drop it so the target is the topic.
        query = _re.sub(r"(?:^|\s),(?:\s*and\s*remember it|,?\s*and\s*learn)\s*$", "",
                        query, flags=_re.IGNORECASE).strip(" .,!?।")
        if query and not filesystem_find:
            frame.require("search_performed", query=query)
            frame.targets.append(query)

    # -- a new tab, not a new window ------------------------------------
    if _re.search(
        r"\bnew\s*tab\b|\bnay[aiye]*\s*tab\b|नई\s*टैब|नया\s*टैब|न्यू\s*टैब",
        text, _re.IGNORECASE,
    ):
        frame.require("new_tab")

    # -- media that must actually be playing ----------------------------
    if _re.search(r"\b(?:play|bajao|baja\s*do|chalao)\b|चलाओ|बजाओ", text, _re.IGNORECASE):
        if _re.search(r"\b(?:song|music|gaana|gana|track|video|गाना|संगीत)\b",
                      text, _re.IGNORECASE):
            frame.require("media_playing")

    return frame


class GoalVerifier:
    """The single authority that can promote a task to VERIFIED_COMPLETE.

    It reads the REAL world - process table, window list, filesystem, the
    application's own display - and compares it with what the user asked
    for. Nothing here consults the model's opinion of its own success."""

    def __init__(self, postconditions: PostconditionVerifier | None = None):
        self.postconditions = postconditions or PostconditionVerifier()

    def requirement_for(self, intent: str) -> str | None:
        return GOAL_POSTCONDITIONS.get(intent)

    def verify(self, *, intent: str, result) -> tuple[str, str]:
        """Return (status, evidence).

        status is one of: VERIFIED_COMPLETE, PARTIAL, FAILED, NOT_APPLICABLE.
        PARTIAL and FAILED are honest outcomes. COMPLETE is not available
        as a guess."""
        kind = self.requirement_for(intent)
        if kind is None:
            return "NOT_APPLICABLE", "this goal has no observable world-effect to verify"

        data = getattr(result, "structured_data", None) or {}
        context = self._context_for(kind, intent, data)
        if context is None:
            return "PARTIAL", (
                f"the '{intent}' result carried no evidence to check its postcondition against"
            )
        satisfied, detail = self.postconditions.check(kind=kind, context=context)
        if satisfied:
            return "VERIFIED_COMPLETE", detail
        return "FAILED", detail

    # -- whole-goal verification ---------------------------------------

    def verify_goal(
        self, *, goal_frame: GoalFrame, observations: list[dict], result=None
    ) -> tuple[str, str]:
        """Verify EVERY effect the goal requires, against real observations.

        This is the answer to "tool success is not goal success". A goal
        with three required effects and two satisfied is PARTIAL - it is
        never a completion with a caveat, and never a completion at all."""
        if not goal_frame or not goal_frame.effects:
            return "NOT_APPLICABLE", "this goal has no observable world-effect to verify"

        evidence: list[str] = []
        unmet: list[str] = []
        for effect in goal_frame.effects:
            kind = effect["kind"]
            context = self._effect_context(kind, effect["context"], observations, result)
            if context is None:
                unmet.append(f"{kind}: nothing was observed that could satisfy it")
                continue
            satisfied, detail = self.postconditions.check(kind=kind, context=context)
            (evidence if satisfied else unmet).append(f"{kind}: {detail}")

        if unmet:
            status = "PARTIAL" if evidence else "FAILED"
            return status, "; ".join(unmet + evidence)
        return "VERIFIED_COMPLETE", "; ".join(evidence)

    @staticmethod
    def _effect_context(
        kind: str, declared: dict, observations: list[dict], result
    ) -> dict | None:
        """Build a postcondition's input from what the mission actually did.

        Reads the OBSERVATION stream - the real inputs and outputs of the
        capability calls that ran - not the model's account of them."""
        observations = observations or []
        data = (getattr(result, "structured_data", None) or {}) if result else {}

        def outputs_of(*names: str) -> list[dict]:
            return [
                item.get("output") or {}
                for item in observations
                if item.get("call") in names and item.get("ok")
                and isinstance(item.get("output"), dict)
            ]

        if kind == "app_launch":
            return {"app_id": declared.get("app_id", "")}

        if kind == "profile_open":
            for output in outputs_of("browser_open_profile", "desktop_browser_open_profile"):
                if output.get("profile"):
                    return {"profile": output.get("profile"),
                            "window": output.get("window_title") or output.get("window") or "chrome"}
            if data.get("profile"):
                return {"profile": data.get("profile"), "window": data.get("window")}
            return None

        if kind == "search_performed":
            visited: list[str] = []
            for item in observations:
                if not item.get("ok"):
                    continue
                inputs, output = item.get("inputs") or {}, item.get("output")
                for candidate in (inputs.get("url"), inputs.get("target"), inputs.get("query")):
                    if candidate:
                        visited.append(str(candidate))
                if isinstance(output, dict):
                    for key in ("url", "title", "final_url", "window_title", "target"):
                        if output.get(key):
                            visited.append(str(output[key]))
            for key in ("url", "title", "target"):
                if data.get(key):
                    visited.append(str(data[key]))
            return {"query": declared.get("query", ""), "visited": visited}

        if kind == "new_tab":
            for output in outputs_of("browser_open_tab", "desktop_browser_open_tab", "browser_new_tab"):
                if output.get("tabs_before") is not None:
                    return {"tabs_before": output.get("tabs_before"),
                            "tabs_after": output.get("tabs_after"),
                            "windows_before": output.get("windows_before"),
                            "windows_after": output.get("windows_after"),
                            "tab_title": output.get("active_tab_title")}
            # Deterministic intents carry the same evidence in their
            # structured_data (they do not write an observations stream);
            # without this fallback the frame verifier saw "no evidence"
            # for a tab that demonstrably opened.
            if isinstance(data.get("tabs_before"), int):
                return {"tabs_before": data.get("tabs_before"),
                        "tabs_after": data.get("tabs_after"),
                        "windows_before": data.get("windows_before"),
                        "windows_after": data.get("windows_after"),
                        "tab_title": data.get("tab_title")}
            launched = any(
                item.get("call") in {"desktop_launch", "app_open"} and item.get("ok")
                for item in observations
            )
            return {"launched_new_window": launched}

        if kind == "media_playing":
            for output in outputs_of("browser_media_state", "browser_read", "browser_evaluate"):
                if "playing" in output:
                    return {"playing": bool(output.get("playing")), "title": output.get("title")}
                if "paused" in output:
                    return {"playing": not output.get("paused"), "title": output.get("title")}
            if "playing" in data:
                return {"playing": data.get("playing"), "title": data.get("title")}
            return {}

        return declared or None

    @staticmethod
    def _context_for(kind: str, intent: str, data: dict) -> dict | None:
        """Build the postcondition's input from the executed result.

        Returns None when the result did not carry enough evidence, which
        is itself a finding - not a reason to assume success."""
        if kind == "app_launch":
            app_id = data.get("app_id")
            return {"app_id": app_id} if app_id else None
        if kind == "app_close":
            app_id = data.get("app_id")
            if not app_id:
                return None
            # An app that was never running was already in the goal state.
            if data.get("was_running") is False:
                return {"app_id": "__already_absent__"}
            return {"app_id": app_id}
        if kind == "window_visible":
            window = data.get("window") or data.get("app_id") or "Settings"
            return {"title": str(window)}
        if kind == "page_action":
            summary = data.get("summary")
            if not summary:
                return None
            return {"summary": str(summary),
                    "title_before": data.get("title_before"),
                    "title_after": data.get("title_after")}
        if kind == "tab_closed":
            if not data.get("page"):
                return None
            return {"page": data.get("page"), "remaining": data.get("remaining"),
                    "tabs_before": data.get("tabs_before"), "tabs_after": data.get("tabs_after"),
                    "browser_still_running": data.get("browser_still_running")}
        if kind == "new_tab":
            if not isinstance(data.get("tabs_before"), int) and not isinstance(
                    data.get("tabs_after"), int):
                return None
            return {"tabs_before": data.get("tabs_before"), "tabs_after": data.get("tabs_after"),
                    "windows_before": data.get("windows_before"),
                    "windows_after": data.get("windows_after"),
                    "tab_title": data.get("tab_title"),
                    "launched_new_window": data.get("launched_new_window")}
        if kind == "profile_open":
            if not data.get("profile"):
                return None
            return {"profile": data.get("profile"), "window": data.get("window")}
        if kind == "requested_target":
            requested = data.get("requested_services") or data.get("requested") or []
            if not requested:
                return {"requested": [], "visited": []}
            visited = data.get("visited") or data.get("sources") or []
            if not visited:
                visited = [str(data.get("url", "")), str(data.get("title", ""))]
            return {"requested": requested, "visited": visited}
        if kind == "observation":
            observed = data.get("observed")
            if isinstance(observed, int):
                return {"observed": observed}
            windows = data.get("windows") or []
            return {"observed": len(windows) or (1 if data.get("active_window") else 0)}
        if kind == "control_value":
            expected = data.get("expected")
            if expected is None:
                return None
            return {"expected": str(expected), "actual": str(data.get("display", ""))}
        if kind == "file_write":
            path = data.get("path") or data.get("file")
            return {"path": str(path), "expect_content": True} if path else None
        if kind == "command":
            exit_code = data.get("exit_code")
            if exit_code is None:
                command = data.get("command") or {}
                exit_code = command.get("exit_code") if isinstance(command, dict) else None
            return {"exit_code": exit_code}
        if kind == "automation_scheduled":
            if not data.get("automation_id"):
                return None
            return {
                "automation_id": data.get("automation_id"),
                "persisted": data.get("persisted"),
                "next_run_at": data.get("next_run_at"),
            }
        if kind == "media_playing":
            if "playing" not in data:
                return None
            return {"playing": data.get("playing"), "title": data.get("title")}
        return None

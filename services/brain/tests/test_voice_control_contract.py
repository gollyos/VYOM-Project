"""The control contract between speech and real-world effect.

Every test here is anchored to a SPECIFIC wrong decision recorded in the
user's physical-microphone session of 2026-08-17 (16:09-16:39 UTC). The
docstrings name the utterance and what VYOM actually did, so a future
regression is recognisable as the same failure rather than an abstract
assertion.

These are runtime laws, not features:

    ONE HUMAN UTTERANCE      -> ONE CANONICAL COMMAND
    ONE TASK                 -> ONE TERMINAL EVENT
    TOOL SUCCESS             != GOAL SUCCESS
    HTTP 200 / CAPTCHA PAGE  != REQUESTED WEB RESULT
    STOP                     >  EVERY OTHER MISSION
"""

from __future__ import annotations

import pytest

from app.memory.consolidation import extract_durable_facts, split_clauses
from app.runtime.error_messages import humanise_observation
from app.runtime.task_classifier import is_interrupt_command
from app.runtime.verifier import GoalVerifier, derive_goal_frame


# ======================================================================
# STOP is a kernel command
# ======================================================================

@pytest.mark.parametrize("utterance", [
    "Stop. Stop. Stop.",          # the exact logged utterance
    "stop", "Stop", "STOP",
    "cancel", "Cancel this",
    "ruko", "ruk jao", "bas", "bas karo",
    "रुको", "बस करो", "बंद करो",
    "chhodo", "mat karo", "rehne do",
    "vyom stop", "ok stop",
])
def test_bare_stop_is_a_kernel_interrupt(utterance):
    """'Stop. Stop. Stop.' reached filesystem.list on C:\\ and read the
    directory back to the user as a completed task at score 1.0. The user
    was trying to make VYOM stop talking."""
    assert is_interrupt_command(utterance) is True


@pytest.mark.parametrize("utterance", [
    "Chrome band karo",            # names a target: ordinary app-close
    "Calculator band karo",
    "music band karo",
    "stop focus session",
    "stop the deployment before it breaks production",
    "Open chrome",
    "close the browser tab",
])
def test_a_named_target_is_not_a_kernel_interrupt(utterance):
    """STOP must not swallow real capability requests. 'Chrome band karo'
    is an app-close that has always worked and must keep working."""
    assert is_interrupt_command(utterance) is False


# ======================================================================
# Whole-goal verification
# ======================================================================

class _Result:
    def __init__(self, **structured_data):
        self.structured_data = structured_data
        self.response = "Done."


def test_launching_the_browser_does_not_complete_a_search_goal():
    """'Open the Chrome browser and search the Luxura Designs.'

    VYOM launched Chrome, searched nothing, and reported the task
    complete at verification score 1.0."""
    frame = derive_goal_frame("Open the Chrome browser and search the Luxora Designs.")
    kinds = [effect["kind"] for effect in frame.effects]
    assert "app_launch" in kinds, "opening Chrome is a required effect"
    assert "search_performed" in kinds, "the search is a SECOND required effect"

    status, evidence = GoalVerifier().verify_goal(
        goal_frame=frame,
        # Chrome launched; nothing else observed.
        observations=[{"call": "desktop_launch", "ok": True,
                       "inputs": {"app_id": "chrome"}, "output": {"running": True}}],
        result=_Result(),
    )
    assert status != "VERIFIED_COMPLETE"
    assert "search" in evidence.lower()


def test_a_captcha_page_is_not_a_search_result():
    """'is all website like a yeh chrome off kar do aur'

    The browser landed on https://www.google.com/sorry/index - Google's
    anti-bot wall - and that URL was accepted as a completed search."""
    frame = derive_goal_frame("chrome kholo aur search karo luxora designs")
    status, evidence = GoalVerifier().verify_goal(
        goal_frame=frame,
        observations=[{
            "call": "browser_navigate", "ok": True, "inputs": {},
            "output": {"url": "https://www.google.com/sorry/index?continue=..."},
        }],
        result=_Result(),
    )
    assert status != "VERIFIED_COMPLETE"
    assert "anti-bot" in evidence or "interstitial" in evidence


def test_a_real_result_page_satisfies_the_search_goal():
    """The positive case: the requested query actually reached a result."""
    frame = derive_goal_frame("search luxora designs")
    status, _ = GoalVerifier().verify_goal(
        goal_frame=frame,
        observations=[{
            "call": "browser_navigate", "ok": True, "inputs": {},
            "output": {"url": "https://www.google.com/search?q=luxora+designs",
                       "title": "luxora designs - Google Search"},
        }],
        result=_Result(),
    )
    assert status == "VERIFIED_COMPLETE"


def test_a_new_window_does_not_satisfy_a_new_tab_goal():
    """'new tab pe YouTube open karo.'

    VYOM launched a detached browser window instead of opening a tab in
    the Chrome the user was already looking at, and reported success."""
    frame = derive_goal_frame("new tab pe YouTube open karo")
    assert "new_tab" in [effect["kind"] for effect in frame.effects]
    status, evidence = GoalVerifier().verify_goal(
        goal_frame=frame,
        observations=[{"call": "desktop_launch", "ok": True,
                       "inputs": {"app_id": "chrome", "url": "https://www.youtube.com"},
                       "output": {"running": True}}],
        result=_Result(),
    )
    assert status != "VERIFIED_COMPLETE"
    assert "tab" in evidence.lower()


def test_opening_a_media_page_is_not_playback():
    """'Ek achcha sa Bollywood song play kar do.'

    A page that opened is not a song that is playing. If autoplay is
    blocked VYOM must say so, not claim success."""
    frame = derive_goal_frame("ek achcha sa bollywood song play kar do")
    assert "media_playing" in [effect["kind"] for effect in frame.effects]
    status, evidence = GoalVerifier().verify_goal(
        goal_frame=frame,
        observations=[{"call": "browser_read", "ok": True, "inputs": {},
                       "output": {"title": "Some Song", "paused": True}}],
        result=_Result(),
    )
    assert status != "VERIFIED_COMPLETE"
    assert "playback" in evidence.lower()


@pytest.mark.parametrize("utterance", [
    "Ek kaam karo mere liye ek achcha sa Bollywood song",
    "mere liye ek achcha sa silent song start kar do.",
    "मेरे लिए कोई अच्छा गाना चला दो",
    "Ek achcha sa Bollywood song play kar do.",
    ("मेरे को नहीं जानना कि तुम क्या कर रहे हो। मेरे को डायरेक्ट मेरे को "
     "सॉन्ग बजाना है तो मैं एक बॉलीवुड अच्छा सा सॉन्ग चला दूं।"),
])
def test_song_requests_route_to_the_verified_media_workflow(utterance):
    """The reproduced commands must never become a window-list mission."""
    from app.runtime.task_classifier import TaskClassifier

    profile = TaskClassifier().classify(utterance)
    assert profile.intent == "play_media", utterance
    assert profile.deterministic and profile.needs == {"tools"}


def test_media_intent_requires_real_playback_evidence():
    verifier = GoalVerifier()
    failed, _ = verifier.verify(
        intent="play_media", result=_Result(playing=False, title="YouTube"))
    passed, evidence = verifier.verify(
        intent="play_media", result=_Result(playing=True, title="A real song"))
    assert failed == "FAILED"
    assert passed == "VERIFIED_COMPLETE"
    assert "A real song" in evidence


@pytest.mark.parametrize("utterance", [
    "what tasks can you perform?",
    "what can you do?",
    "You have the personal memory?",
    "और अब तुम मेरे लिए कौन से कौन से टास्क परफॉर्म कर सकती हो?",
])
def test_self_capability_questions_never_go_to_a_model(utterance):
    from app.runtime.task_classifier import TaskClassifier

    profile = TaskClassifier().classify(utterance)
    assert profile.intent == "capability_query"
    assert profile.deterministic and profile.needs == {"tools"}


def test_normalised_browser_tab_list_reaches_the_real_tab_reader():
    from app.runtime.task_classifier import TaskClassifier

    assert TaskClassifier().classify("browser tabs dikhao").intent == "browser_tab_list"


def test_browser_audio_marker_is_playback_evidence(monkeypatch):
    from app.input_control.accessibility import NativeAccessibilityController

    controller = NativeAccessibilityController()
    monkeypatch.setattr(controller, "list_browser_tabs", lambda: [{
        "title": "A real song - YouTube - Audio playing - Memory usage - 200 MB"
    }])
    state = controller.browser_media_state()
    assert state["playing"] is True
    assert state["source"] == "browser-tab-audio-state"
    assert state["title"] == "A real song - YouTube"


def test_youtube_first_result_prefers_video_title_over_home_logo(monkeypatch):
    from types import SimpleNamespace

    from app.input_control.accessibility import NativeAccessibilityController

    class Element:
        def __init__(self, automation_id):
            self.element_info = SimpleNamespace(automation_id=automation_id)
            self.clicked = False

        def click_input(self):
            self.clicked = True

    class Window:
        def set_focus(self):
            return None

    logo = Element("logo")
    video = Element("video-title")
    controller = NativeAccessibilityController()
    monkeypatch.setattr(controller, "browser_window", lambda: Window())
    monkeypatch.setattr(controller, "_page_elements", lambda _window: [
        ("YouTube Home", "Hyperlink", logo),
        ("A real song with a sufficiently long title", "Hyperlink", video),
    ])
    result = controller.browser_first_result()
    assert result.success is True
    assert video.clicked is True and logo.clicked is False


def test_browser_launch_binds_followup_actions_to_the_changed_chrome_window():
    """A URL launch may reuse one of several Chrome windows. The old bug
    returned the first wrapper (ChatGPT) even though YouTube opened in a
    different window, so the click and verification ran in the wrong place.
    """
    from types import SimpleNamespace

    from app.desktop.controller import DesktopController

    class Window:
        def __init__(self, handle, title, active):
            self.handle = handle
            self.title = title
            self.active = active
            self.focused = False

        def window_text(self):
            return self.title

        def is_active(self):
            return self.active

        def set_focus(self):
            self.focused = True

    unrelated = Window(10, "ChatGPT - Google Chrome", False)
    youtube = Window(20, "Bollywood song - YouTube - Google Chrome", True)
    accessibility = SimpleNamespace(
        browser_windows=lambda: [unrelated, youtube],
        intended_window_handle=None,
    )
    controller = DesktopController.__new__(DesktopController)
    controller.accessibility = accessibility

    selected = controller._bind_launched_browser_window(
        "https://www.youtube.com/results?search_query=Bollywood+song",
        {
            10: ("ChatGPT - Google Chrome", True),
            20: ("Deep relax song - YouTube - Google Chrome", False),
        },
        fallback=unrelated,
        timeout=0.1,
    )
    assert selected is youtube
    assert accessibility.intended_window_handle == 20
    assert youtube.focused is True


def test_long_hindi_media_transcript_extracts_the_song_not_the_complaint():
    from app.execution.action_engine import ActionEngine

    request = ("मेरे को नहीं जानना कि तुम क्या कर रहे हो। मेरे को डायरेक्ट मेरे को "
               "सॉन्ग बजाना है तो मैं एक बॉलीवुड अच्छा सा सॉन्ग चला दूं।")
    query = ActionEngine._extract_media_query(request)
    assert "बॉलीवुड" in query and "सॉन्ग" in query
    assert "क्या कर" not in query
    assert "मेरे को" not in query
    assert "बजाना" not in query and "चला" not in query


@pytest.mark.asyncio
async def test_media_workflow_searches_clicks_and_verifies_before_success(monkeypatch):
    from types import SimpleNamespace

    from app.execution.action_engine import ActionEngine
    from app.schemas.tasks import Task

    calls = []

    class FakeExecutor:
        async def invoke(self, tool, inputs, context):
            calls.append((tool, dict(inputs)))
            action = inputs["action"]
            if action == "app_open":
                return SimpleNamespace(
                    success=True, error=None,
                    structured_output={"url": inputs["url"], "tabs_before": 1,
                                       "tabs_after": 2, "windows_before": 1,
                                       "windows_after": 1},
                )
            if action == "browser_page_type":
                return SimpleNamespace(
                    success=True, error=None,
                    structured_output={"success": True, "summary": "Navigated to search",
                                       "value": inputs["value"],
                                       "title_after": "silent song - YouTube"},
                )
            if action == "browser_first_result":
                return SimpleNamespace(
                    success=True, error=None,
                    structured_output={"success": True, "summary": "Opened first result",
                                       "title_after": "A real song - YouTube"},
                )
            phase = "after" if any(item[1]["action"] == "browser_first_result"
                                   for item in calls) else "before"
            return SimpleNamespace(
                success=True, error=None,
                structured_output=(
                    {"playing": True, "title": "A real song - YouTube",
                     "source": "browser-tab-audio-state",
                     "playing_tabs": ["A real song - YouTube - Audio playing"]}
                    if phase == "after" else
                    {"playing": False, "title": "", "source": "unobservable",
                     "playing_tabs": []}
                ),
            )

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr("app.execution.action_engine.asyncio.sleep", no_sleep)
    engine = ActionEngine.__new__(ActionEngine)
    engine.executor = FakeExecutor()
    result = await engine._play_media(
        Task(goal="play a song", user_request="mere liye Bollywood song start kar do"),
        context=object(),
    )
    assert result.structured_data["playing"] is True
    assert [inputs["action"] for _, inputs in calls] == [
        "browser_media_state", "app_open", "browser_page_type", "browser_first_result",
        "browser_media_state",
    ]
    assert "youtube.com/results?search_query=" in calls[1][1]["url"]


def test_a_conversational_utterance_declares_no_world_effect():
    """Conversation must be untouched by goal verification."""
    assert not derive_goal_frame("you can hear me?")
    assert not derive_goal_frame("यह ड्यूल ऑडियो क्यों आ रही है?")
    status, _ = GoalVerifier().verify_goal(
        goal_frame=derive_goal_frame("you can hear me?"), observations=[], result=_Result())
    assert status == "NOT_APPLICABLE"


# ======================================================================
# Durable memory: one slot, one fact
# ======================================================================

def test_a_multi_fact_utterance_does_not_contaminate_the_name_slot():
    """The exact utterance that corrupted the live store at 16:10:12.

    Written: User name = 'गुंजन शाह। मेरा जो वेबसाइट है वह है लक्स' - the
    name fused with the start of the NEXT sentence and truncated
    mid-word at the pattern's 40-character ceiling, because the danda
    (U+0964) sits inside the Devanagari range used for values."""
    said = ("सबसे पहली बात मेरा नाम है गुंजन शाह। मेरा जो वेबसाइट है वह है "
            "लक्सोरा डिजाइंस।स्पेस बस और तुम एक काम करो क्रोम पर जाकर सर्च करो।")
    facts = {fact["title"]: fact["value"] for fact in extract_durable_facts(said)}
    assert facts.get("User name") == "गुंजन शाह"
    assert "।" not in facts.get("User name", "")
    assert "वेबसाइट" not in facts.get("User name", "")


def test_two_facts_in_one_sentence_land_in_separate_slots():
    facts = {fact["title"]: fact["value"]
             for fact in extract_durable_facts(
                 "Mera naam Gunjan Shah hai aur meri website test.example hai.")}
    assert facts["User name"] == "Gunjan Shah"
    assert facts["User website"] == "test.example"


def test_a_domain_is_not_split_on_its_dot():
    """Splitting clauses on every '.' stored the website as 'test'."""
    assert "test.example" in split_clauses("my website is test.example")[0]
    facts = {fact["title"]: fact["value"]
             for fact in extract_durable_facts("My name is Gunjan Shah and my website is test.example")}
    assert facts["User website"] == "test.example"


def test_a_negation_is_never_stored_as_a_value():
    """'old-example meri website nahi hai. Correct website X hai.'

    The negated half matched the same shape as an assertion and stored
    the word 'nahi' as the user's website."""
    facts = extract_durable_facts(
        "old-example meri website nahi hai. Correct website luxora-designs.example hai.")
    values = {fact["value"] for fact in facts}
    assert "nahi" not in values
    assert "luxora-designs.example" in values
    assert all(fact["correction"] for fact in facts), "this is a correction, not a fresh fact"


def test_a_question_stores_nothing():
    assert extract_durable_facts("Mera naam kya hai?") == []


def test_open_my_website_is_a_command_not_a_fact():
    """The physical command must never persist its trailing verb as truth."""
    assert extract_durable_facts("meri website kholo") == []
    assert extract_durable_facts("open my website") == []


def test_spoken_whitespace_inside_a_domain_is_normalised():
    facts = extract_durable_facts("meri website luxora designs.space hai")
    assert [(fact["title"], fact["value"]) for fact in facts] == [
        ("User website", "luxoradesigns.space")
    ]


# ======================================================================
# What the user hears is never internal bookkeeping
# ======================================================================

@pytest.mark.parametrize("payload,forbidden", [
    ({"app_id": "chrome", "running": True, "pid": 22276,
      "window_title": "Untitled - Google Chrome", "target": "https://www.youtube.com"}, "22276"),
    ({"window": {"title": "New Tab - Google Chrome", "class_name": "Chrome_WidgetWin_1",
                 "process_id": 22276, "handle": 4915714, "focused": True}}, "4915714"),
])
def test_a_tool_payload_is_never_read_out_verbatim(payload, forbidden):
    """Both of these were spoken to the user, pids and window handles
    included, as the final answer to a voice command."""
    spoken = humanise_observation(payload)
    assert not spoken.startswith("{")
    assert forbidden not in spoken
    assert "pid" not in spoken.lower()
    assert "handle" not in spoken.lower()


# ======================================================================
# One task, one terminal event
# ======================================================================

@pytest.mark.asyncio
async def test_a_task_terminalises_exactly_once(tmp_path):
    """task_completed was published TWICE for the same task_id - once by
    MissionLoop and again by _finish_result, 25-38ms apart with identical
    payloads. The UI rendered the result twice and TTS spoke it twice.

    Observed in vyom-trace.jsonl for 2 of 2 traced tasks."""
    from app.schemas.events import EventType
    from app.schemas.tasks import Task, TaskCreate

    from .helpers import build_runtime

    harness = await build_runtime(tmp_path / "terminal.db")
    runtime = harness.runtime

    task = Task.from_create(TaskCreate(user_request="a task that finishes"))
    await harness.task_store.save(task)

    # Two independent completion paths, exactly as the runtime had.
    await runtime._emit(task, EventType.TASK_COMPLETED, "done", {})
    await runtime._emit(task, EventType.TASK_COMPLETED, "done", {})
    # A cancelled/superseded task must not be able to complete afterwards.
    await runtime._emit(task, EventType.TASK_FAILED, "late failure", {})

    seen = [event.type.value for event in harness.event_bus.history]
    assert seen.count("task_completed") == 1, "the result was published more than once"
    assert "task_failed" not in seen, "a terminalised task emitted a second terminal event"


@pytest.mark.asyncio
async def test_a_superseded_task_cannot_speak_after_cancellation(tmp_path):
    """A revision of the same utterance cancels the in-flight task. The
    cancelled task must never publish a completion afterwards."""
    from app.schemas.events import EventType
    from app.schemas.tasks import Task, TaskCreate

    from .helpers import build_runtime

    harness = await build_runtime(tmp_path / "superseded.db")
    task = Task.from_create(TaskCreate(user_request="superseded utterance"))
    await harness.task_store.save(task)

    await harness.runtime._emit(task, EventType.TASK_CANCELLED, "superseded", {})
    await harness.runtime._emit(task, EventType.TASK_COMPLETED, "I finished anyway", {})

    seen = [event.type.value for event in harness.event_bus.history]
    assert seen.count("task_cancelled") == 1
    assert "task_completed" not in seen, "a cancelled task spoke a completion"


# ======================================================================
# Browser profile: the user's real profile is routable
# ======================================================================

def test_a_mistranscribed_profile_name_still_resolves():
    """'Okay. Chrome pe Woolly AI OS open karo.'

    The account is "Golly AiOs"; speech-to-text produced "Woolly AI OS".
    Word-by-word matching scored golly/woolly at 0.73 and aios against the
    split "ai"/"os" at 0.67, so both fell under the threshold and VYOM
    opened a generic Chrome window instead of the user's profile.

    Skipped where Chrome is not installed - this reads REAL profiles."""
    from app.desktop.app_launcher import ApplicationRegistry

    profiles = ApplicationRegistry.browser_profiles()
    if not profiles:
        pytest.skip("no Chrome profiles on this machine")
    target = next((item for item in profiles
                   if "golly" in item["account"].lower().replace(" ", "")), None)
    if target is None:
        pytest.skip("the Golly AiOs profile is not present on this machine")

    for spoken in ("Okay. Chrome pe Woolly AI OS open karo.",
                   "Open Goli AIOS profile.",
                   "Chrome pe Golly AI OS profile open karo"):
        resolved = ApplicationRegistry.resolve_browser_profile(spoken)
        assert resolved is not None, f"{spoken!r} did not resolve to any profile"
        assert resolved["directory"] == target["directory"], spoken


def test_a_profile_named_without_the_word_profile_still_routes_there():
    """'Chrome pe Woolly AI OS open karo.'

    Routing required the literal word "profile", so this became a generic
    app_launch and the user got an empty Chrome window - then said
    "मेरे को नहीं दिख रहा कि गोली प्रोफाइल ओपन हुई है"."""
    from app.desktop.app_launcher import ApplicationRegistry
    from app.runtime.task_classifier import TaskClassifier

    if not ApplicationRegistry.browser_profiles():
        pytest.skip("no Chrome profiles on this machine")
    classifier = TaskClassifier()
    for spoken in ("Okay. Chrome pe Woolly AI OS open karo.",
                   "Chrome pe Golly AI OS open karo"):
        assert classifier.classify(spoken).intent == "browser_profile_open", spoken


@pytest.mark.parametrize("utterance", [
    "Chrome open karo",                                  # no profile named
    "Open the Chrome.",
    "Chrome pe YouTube open karo",                       # a destination, not an identity
    "chrome me luxoradesigns.space kholo",               # a URL
    "Open the Chrome browser and search Luxora Designs", # a search
])
def test_a_plain_browser_launch_is_not_a_profile_open(utterance):
    """The profile check must not swallow ordinary browser launches."""
    from app.runtime.task_classifier import TaskClassifier

    assert TaskClassifier().classify(utterance).intent != "browser_profile_open"


def test_an_unrelated_sentence_resolves_to_no_profile():
    """Generic Chrome requests must not be pulled into a profile."""
    from app.desktop.app_launcher import ApplicationRegistry

    if not ApplicationRegistry.browser_profiles():
        pytest.skip("no Chrome profiles on this machine")
    assert ApplicationRegistry.resolve_browser_profile("Chrome open karo") is None
    assert ApplicationRegistry.resolve_browser_profile("open the calculator") is None


# ======================================================================
# ActiveContext: a pronoun points at the conversation, not the store
# ======================================================================

def _context_runtime(**fields):
    from app.runtime.cognitive_runtime import ActiveContext, CognitiveRuntime

    runtime = CognitiveRuntime.__new__(CognitiveRuntime)
    runtime.active = ActiveContext(**fields)
    return runtime


@pytest.mark.parametrize("utterance", [
    "to open kijiye usko.", "usko open karo", "isko dikhao",
    "ise open karo", "इसको खोलो", "उसको ओपन करो",
])
def test_a_hindi_pronoun_is_recognised_as_a_follow_up(utterance):
    """'to open kijiye usko' resolved to a Zoho workflow from an old
    memory record, because the follow-up markers were English-only and
    the sentence was never treated as a follow-up at all."""
    runtime = _context_runtime(last_url="https://luxoradesigns.space")
    assert runtime.resolve_reference(utterance) == "https://luxoradesigns.space"


def test_the_active_mission_outranks_durable_memory():
    """Priority order: active mission > last observation > memory."""
    runtime = _context_runtime(
        last_url="https://luxoradesigns.space",
        last_verified_goal="Open my Zoho My Agency workflow",  # the old hit
    )
    assert runtime.resolve_reference("to open kijiye usko.") == "https://luxoradesigns.space"


def test_a_pronoun_falls_back_to_the_last_observation_before_memory():
    runtime = _context_runtime(
        last_screen={"active": "Luxora Designs - Google Chrome", "all": []},
        last_verified_goal="Open my Zoho My Agency workflow",
    )
    assert "Luxora" in runtime.resolve_reference("ye kya hai?")


def test_a_command_with_no_pronoun_resolves_nothing():
    runtime = _context_runtime(last_url="https://example.test")
    assert runtime.resolve_reference("open calculator") is None


def test_an_observation_is_recorded_from_what_actually_happened():
    """ActiveContext was only ever fed from memory hits, so it never knew
    what VYOM had just done."""
    from types import SimpleNamespace

    runtime = _context_runtime()
    result = SimpleNamespace(structured_data={"observations": [
        {"call": "desktop_launch", "ok": True,
         "inputs": {"app_id": "chrome", "url": "https://luxoradesigns.space"},
         "output": {"running": True}},
        {"call": "desktop_window_list", "ok": True, "inputs": {}, "output": {"windows": [
            {"title": "Luxora Designs - Google Chrome", "focused": True},
            {"title": "Calculator", "focused": False},
        ]}},
    ]})
    task = SimpleNamespace(user_request="open luxoradesigns.space",
                           status=SimpleNamespace(value="completed"), error=None)
    runtime.record_observation(task=task, result=result)

    assert runtime.active.last_url == "https://luxoradesigns.space"
    assert runtime.active.last_app == "chrome"
    assert runtime.active.last_screen["active"] == "Luxora Designs - Google Chrome"
    assert runtime.active.last_screen_at is not None
    assert runtime.active.screen_age_seconds(runtime.active.last_screen_at + 5) == 5


def test_a_resolved_pronoun_supplies_the_launch_target():
    """The referent has to reach EXECUTION, not just be computed.

    'to open kijiye usko' names no destination, so target extraction
    returned None and the planner opened an unrelated URL from memory."""
    from app.execution.action_engine import ActionEngine

    engine = ActionEngine.__new__(ActionEngine)
    # No target in the words themselves.
    assert engine._extract_launch_target("to open kijiye usko.", "chrome") is None
    # With the referent, the destination is the thing just discussed.
    assert engine._extract_launch_target(
        "to open kijiye usko.", "chrome",
        referent="https://luxoradesigns.space") == "https://luxoradesigns.space"


@pytest.mark.parametrize("utterance,expected", [
    ("to open kijiye usko.", True), ("usko kholo", True),
    ("isko dikhao", True), ("usko band karo", False),
    ("ye kya hai", False),
])
def test_only_an_open_instruction_is_referent_routed(utterance, expected):
    """A pronoun in a CLOSE instruction must not become a launch."""
    from app.runtime.task_runtime import TaskRuntime

    assert TaskRuntime._is_open_command(utterance) is expected


# ======================================================================
# Screen questions need fresh evidence
# ======================================================================

@pytest.mark.parametrize("utterance", [
    "यह क्या है?", "ye kya hai?", "Yeh kya hai",
    "abhi jo screen open ki hai woh dikh rahi hai?",
    "already I you can show my screen.",
    "screen pe abhi kya open hai?",
])
def test_a_screen_question_demands_a_fresh_reading(utterance):
    """'यह क्या है?' was answered from durable business memory ("your
    website is Luxora") twenty seconds after a real window reading had
    been taken and discarded."""
    from app.runtime.task_classifier import TaskClassifier

    assert TaskClassifier().classify(utterance).intent == "screen_observe"


@pytest.mark.parametrize("utterance", [
    "ye API kya hai?", "yeh Luxora Designs kya hai", "what is a REST API",
])
def test_a_question_with_its_own_subject_is_not_a_screen_question(utterance):
    """Only a BARE demonstrative points at the screen."""
    from app.runtime.task_classifier import TaskClassifier

    assert TaskClassifier().classify(utterance).intent != "screen_observe"


def test_observations_render_as_plain_sentences():
    assert humanise_observation(
        {"app_id": "calculator", "closed": True}) == "Calculator is closed."
    assert humanise_observation(
        {"profile": {"directory": "Profile 1", "name": "Business Luxora",
                     "account": "Golly AiOs"}}
    ) == "Chrome is open in the Business Luxora profile (Golly AiOs)."


# ======================================================================
# The bus itself refuses a second terminal (2026-08-19 pass)
# ======================================================================
#
# task_runtime._emit's own guard was correct, but MissionLoop published
# through a DIFFERENT path (_cognitive_emit -> event_bus.publish), so the
# guard never saw the duplicate. The invariant must hold at the one point
# every publisher shares.

@pytest.mark.asyncio
async def test_the_event_bus_refuses_a_second_terminal_from_any_publisher(tmp_path):
    """Two distinct publishers, both calling bus.publish directly - the
    exact shape of the 16:39/17:54 duplicate completions (38ms apart)."""
    from app.runtime.event_bus import EventBus
    from app.schemas.events import BrainEvent, EventType

    bus = EventBus()
    for _ in range(3):
        await bus.publish(BrainEvent(task_id="task_x", type=EventType.TASK_COMPLETED,
                                     human_readable_message="done",
                                     structured_payload={"response": "done"}))
    await bus.publish(BrainEvent(task_id="task_x", type=EventType.TASK_FAILED,
                                 human_readable_message="late failure",
                                 structured_payload={}))
    # Different task, different story: unaffected.
    await bus.publish(BrainEvent(task_id="task_y", type=EventType.TASK_COMPLETED,
                                 human_readable_message="other task",
                                 structured_payload={}))

    delivered = [event for event in bus.history]
    terminals_x = [event for event in delivered
                   if event.task_id == "task_x" and event.type != EventType.TASK_PROGRESS]
    assert len(terminals_x) == 1, "a second terminal from another publisher got through"
    # Two extra completions + the late failure were all refused.
    assert bus.duplicate_terminal_suppressed == 3


@pytest.mark.asyncio
async def test_a_cancelled_task_cannot_complete_at_the_bus_level():
    from app.runtime.event_bus import EventBus
    from app.schemas.events import BrainEvent, EventType

    bus = EventBus()
    await bus.publish(BrainEvent(task_id="task_c", type=EventType.TASK_CANCELLED,
                                 human_readable_message="superseded",
                                 structured_payload={}))
    await bus.publish(BrainEvent(task_id="task_c", type=EventType.TASK_COMPLETED,
                                 human_readable_message="I finished anyway",
                                 structured_payload={"response": "I finished anyway"}))
    assert [event.type for event in bus.history] == [EventType.TASK_CANCELLED], (
        "a cancelled task spoke a completion"
    )


# ======================================================================
# MissionLoop reports, TaskRuntime terminalizes (2026-08-19 pass)
# ======================================================================

class _SpyPlanner:
    """next_action always returns prose that refuses to use a tool."""

    class _Decision:
        tool_calls = []
        text = "I'm sorry, I cannot perform that action."

    async def next_action(self, goal, history, tools):
        return _SpyPlanner._Decision()

    def relevant_tools(self, goal):
        return []


@pytest.mark.asyncio
async def test_mission_loop_never_emits_a_terminal_event(tmp_path):
    """MissionLoop emitted its own task_completed/task_failed - and it did
    so BEFORE TaskRuntime's goal verification had run, so the bus could
    carry COMPLETED for a goal the verifier was about to reject. The
    mission reports outcomes as progress; the ONE terminal comes from
    TaskRuntime, after verification."""
    from app.schemas.events import EventType
    from app.runtime.mission_loop import MissionLoop
    from app.memory.resolution import ResolutionChain  # noqa: F401  (import path check)

    emitted: list = []

    async def spy_emit(mission_id, event_type, message, payload):
        emitted.append(event_type)

    class _FakeExecutor:
        async def execute(self, *args, **kwargs):
            return None

        async def commit(self):
            return None

    class _FakeDatabase:
        def require_connection(self):
            return _FakeExecutor()

    from app.reliability.checkpoints import CheckpointStore as _CPS

    loop = MissionLoop(
        cognitive=None,
        planner=None,
        checkpoint_store=_CPS(_FakeDatabase()),
        emit=spy_emit,
    )

    async def execute_call(call):
        return {"ok": True, "output": "x" * 200}

    mission = await loop.run_adaptive(
        "review the competitor landscape",          # fresh-evidence goal
        planner=_SpyPlanner(),
        execute_call=execute_call,
        require_tool_use=True,                       # what TaskRuntime now always passes
    )
    assert mission.status == "failed", (
        "prose that refuses to act completed an actionable goal"
    )
    from app.schemas.events import EventType as _ET
    terminals = {EventType.TASK_COMPLETED, EventType.TASK_FAILED, EventType.TASK_CANCELLED}
    assert not (set(emitted) & terminals), (
        f"MissionLoop emitted terminal events itself: "
        f"{sorted(t.value for t in set(emitted) & terminals)}"
    )


# ======================================================================
# STT noise is gated, not answered (2026-08-19 pass)
# ======================================================================

@pytest.mark.parametrize("utterance,expected", [
    ("guerra rua", True),                    # the exact logged garbage
    ("xyzzy plugh", True),
    ("q", True),
    ("novio on desktop my pc", False),       # 'on', 'desktop', 'my', 'pc' are audible
    ("open chrome", False),
    ("25 guna 18 karo", False),              # numbers carry content
    ("mera naam kya hai", False),            # a question is never discarded unread
    ("what is my status today", False),
])
def test_unparseable_noise_is_gated_not_answered(utterance, expected):
    """'guerra rua' got a model call and a confident invented answer about
    the user's business. A transcript with no audible word in it is
    honestly re-asked, at zero model cost."""
    from app.runtime.task_classifier import looks_like_stt_noise

    assert looks_like_stt_noise(utterance) is expected


# ======================================================================
# The response boundary sanitises everything (2026-08-19 pass)
# ======================================================================

def test_a_raw_dict_response_is_never_read_out():
    """'open abhi jo promo open' was answered with the literal text
    "{'app_id': 'chrome', 'running': True, 'pid': 22276, ...}". Whatever
    any engine produces, the boundary renders structure as meaning."""
    from app.runtime.error_messages import sanitise_user_response

    cleaned = sanitise_user_response(
        "{'app_id': 'chrome', 'running': True, 'pid': 22276, "
        "'window_title': 'Untitled - Google Chrome', "
        "'target': 'https://www.google.com'}")
    assert not cleaned.startswith("{")
    assert "pid" not in cleaned.lower()
    assert "chrome" in cleaned.lower()


def test_pid_narration_and_internal_paths_are_stripped():
    from app.runtime.error_messages import sanitise_user_response

    cleaned = sanitise_user_response(
        "Chrome was launched and verified running (pid 16596); config at "
        r"C:\VYOM Project\services\brain\config\models.yaml")
    assert "pid" not in cleaned.lower()
    assert "16596" not in cleaned
    assert "C:\\" not in cleaned and "VYOM Project" not in cleaned
    assert "models.yaml" in cleaned, "the file NAME is useful; the path is not"


def test_a_clean_sentence_passes_through_untouched():
    from app.runtime.error_messages import sanitise_user_response

    sentence = "Chrome is open in the Business Luxora profile (Golly AiOs)."
    assert sanitise_user_response(sentence) == sentence


# ======================================================================
# The planner observes the world before touching the repo (2026-08-19)
# ======================================================================

def test_the_default_shortlist_looks_at_the_world_not_the_repository():
    """'on my screen open Hermes.bat file click and open.' was answered
    with 'VYOM Project contains 38 top-level entries' because
    filesystem_list sat in the planner's DEFAULT tool set. An unknown goal
    now starts by observing windows, memory and the browser - never the
    directory."""
    from app.runtime.planner import GeneralPlanner

    names = [tool.name for tool in GeneralPlanner(model_router=None, providers={}).relevant_tools(
        "frobnicate the quux widget")]
    assert "filesystem_list" not in names
    assert "desktop_active_window" in names


def test_profile_and_tab_goals_reach_their_real_capabilities():
    """The browser-profile and tab capabilities existed and worked when
    called directly, but the planner had no contract for them - so a
    goal phrased outside the deterministic vocabulary fell back to a
    generic Chrome launch."""
    from app.runtime.planner import GeneralPlanner

    planner = GeneralPlanner(model_router=None, providers={})
    profile_tools = [tool.name for tool in planner.relevant_tools(
        "Chrome pe Golly AI OS profile kholo")]
    tab_tools = [tool.name for tool in planner.relevant_tools(
        "YouTube wala tab band karo, Chrome nahi")]
    assert "browser_open_profile" in profile_tools
    assert "browser_close_tab" in tab_tools


def test_profile_and_tab_calls_get_real_postconditions():
    """Choosing the capability is not enough - the call must map to the
    postcondition that proves the user-visible effect (profile window,
    one tab gone with the browser alive)."""
    from app.runtime.task_runtime import TaskRuntime

    kind, context = TaskRuntime._postcondition_for(
        "browser_open_profile", {"profile": "golly"},
        {"profile": {"directory": "Profile 1", "name": "Business Luxora",
                     "account": "Golly AiOs"}, "window_title": "Chrome"})
    assert kind == "profile_open"
    assert context["profile"]["directory"] == "Profile 1"

    kind, context = TaskRuntime._postcondition_for(
        "browser_close_tab", {"target": "youtube"},
        {"success": True, "tabs_before": 3, "tabs_after": 2,
         "remaining": ["Gmail"], "browser_still_running": True})
    assert kind == "tab_closed"
    assert context["browser_still_running"] is True
    assert context["tabs_after"] < context["tabs_before"]


# ======================================================================
# Gate order and screen routing (2026-08-19 replay findings)
# ======================================================================

def test_noise_outranks_conversation():
    """'guerra rua' is conversational by every word-shape test (short, no
    verb), so the noise check must run BEFORE the conversational branch -
    otherwise garbage reaches a model and comes back as a confident
    invented answer."""
    from app.runtime.planner import is_conversational
    from app.runtime.task_classifier import looks_like_stt_noise

    assert is_conversational("guerra rua") is True, (
        "precondition of the bug: garbage looks conversational"
    )
    assert looks_like_stt_noise("guerra rua") is True


@pytest.mark.parametrize("utterance", [
    "Screen pe abhi kya hai?",         # the exact replayed utterance
    "screen par abhi kya hai",
    "abhi screen me kya hai",
    "स्क्रीन पे अभी क्या है?",
])
def test_a_screen_question_takes_the_fresh_reading_route(utterance):
    """Replayed live: 'Screen pe abhi kya hai?' was answered by a model
    from memory with no window read - the ABHI between 'screen pe' and
    'kya' broke the phrase match. The classifier must send every one of
    these to the deterministic screen observation, and even if a phrasing
    slips past it, it must never count as conversation."""
    from app.runtime.planner import is_conversational
    from app.runtime.task_classifier import TaskClassifier, is_screen_question

    assert is_screen_question(utterance), utterance
    assert TaskClassifier().classify(utterance).intent == "screen_observe", utterance
    assert is_conversational(utterance) is False, utterance


# ======================================================================
# 2026-08-19 physical session: unsolicited actions, memory dumps, tabs
# ======================================================================

@pytest.mark.parametrize("utterance", [
    "I cannot show on the calculator this is clear.",   # launched Calculator
    "I cannot show on the calculator this is clear. No. Why again and again you speech to my uh uh dialogues? Why?",
    "But maine bola hi nahi. Kyun open kiya?",          # after a profile opened unasked
    "You are not a perfect.",                            # recited name+business
])
def test_complaints_are_feedback_not_actions(utterance):
    """Each of these was routed to the general planner in the physical
    session; the planner 'helpfully' launched Calculator or the model
    recited the user's business. A complaint is feedback about the work
    in flight, answered from runtime state - never an action request."""
    from app.runtime.task_classifier import TaskClassifier

    assert TaskClassifier().classify(utterance).intent == "user_feedback", utterance


@pytest.mark.parametrize("utterance,expected", [
    ("अभी जो क्रोम की प्रोफाइल ओपन है उसमें लाइक जो मैं कैलकुलेशन बोल रहा हूं वह", False),
    ("I cannot show on the calculator this is clear.", False),
    ("But maine bola hi nahi. Kyun open kiya?", False),
    ("Chrome kholo.", True),
    ("Open calculator.", True),
    ("Calculator band karo.", True),
    ("open a new tab and search youtube", True),
])
def test_only_imperatives_request_external_actions(utterance, expected):
    """'The profile that IS open' is a description of state, not a
    command. The gate that decides whether effect capabilities may be
    offered at all must agree."""
    from app.runtime.task_classifier import requests_external_action

    assert requests_external_action(utterance) is expected, utterance


def test_a_descriptive_open_requires_no_app_launch():
    """The Hindi fragment required an app_launch effect in its GoalFrame;
    the planner satisfied it by opening a profile nobody asked for."""
    frame = derive_goal_frame(
        "अभी जो क्रोम की प्रोफाइल ओपन है उसमें लाइक जो मैं कैलकुलेशन बोल रहा हूं वह")
    assert [e["kind"] for e in frame.effects] == [], (
        "a mid-sentence description of browser state demanded a world effect"
    )


def test_the_new_tab_request_now_requires_tab_and_search_effects():
    frame = derive_goal_frame(
        "अभी जो मेरी Chrome की प्रोफाइल ओपन है, उसमें न्यू टैब ओपन करो और YouTube सर्च करो।")
    kinds = [e["kind"] for e in frame.effects]
    assert "new_tab" in kinds, "न्यू टैब was not recognized as a tab requirement"
    assert "search_performed" in kinds, "सर्च करो was not recognized as a search requirement"


def test_new_tab_utterance_routes_to_the_tab_capability():
    from app.runtime.task_classifier import TaskClassifier

    assert TaskClassifier().classify(
        "अभी जो मेरी Chrome की प्रोफाइल ओपन है, उसमें न्यू टैब ओपन करो और YouTube सर्च करो।"
    ).intent == "browser_tab_open"


def test_a_complaint_is_offered_no_effect_capabilities():
    """The planner's tool shortlist for a complaint must not contain a
    single capability that can change what the user sees."""
    from app.runtime.planner import GeneralPlanner

    names = [tool.name for tool in GeneralPlanner(
        model_router=None, providers={}).relevant_tools(
        "I cannot show on the calculator this is clear.")]
    assert not (set(names) & GeneralPlanner.EFFECT_CONTRACTS), names
    # Observation stays available - grounding is how the complaint gets a
    # truthful answer.
    assert "desktop_active_window" in names or "desktop_window_list" in names


@pytest.mark.parametrize("utterance,reason", [
    ("Hello.", None),
    ("Can you hear me properly?", None),
    ("Sorry. This is the clear first.", None),
    ("You are not a perfect.", None),
    ("Open calculator.", None),
    ("Mera naam kya hai?", "EXACT_SLOT_REQUIRED"),
    ("meri website kholo", "EXACT_SLOT_REQUIRED"),
    ("Client report banao for the meeting", "SEMANTICALLY_RELEVANT"),
    ("meri website galat hai, correct website luxora.design hai", "EXACT_SLOT_REQUIRED"),
])
def test_memory_enters_only_with_a_reason(utterance, reason):
    """'Understood, Gunjan Shah. I have noted that your business is...'
    was the answer to 'Sorry. This is the clear first.' Profile memory
    now requires a recorded reason to enter a mission at all."""
    from app.runtime.task_classifier import memory_relevance_reason

    assert memory_relevance_reason(utterance) == reason, utterance


def test_a_chain_calculation_is_not_truncated_to_its_first_pair():
    """'So 9 * 8 * 6 * 5 * 4 * 3 * 1 * 9 * 3 =' was answered '9 times 8 is
    72'. The chain parser must take every operand and fold left to
    right, the way sequential calculator presses do."""
    from app.runtime.task_classifier import evaluate_chain, parse_arithmetic_chain

    segments = parse_arithmetic_chain("So 9 * 8 * 6 * 5 * 4 * 3 * 1 * 9 * 3 =")
    assert segments is not None, "the chain was not parsed at all"
    assert len(segments) == 9
    assert evaluate_chain(segments) == 699840.0
    # Binary behaviour is unchanged for real two-operand requests.
    assert parse_arithmetic_chain("27 guna 43 karo") is None


def test_a_new_window_fails_the_new_tab_postcondition():
    """Same-context constraint: when a browser window existed, the window
    count must not grow - that is the 'new Chrome instance' failure the
    physical session reported, and it may never verify as a tab."""
    verifier = GoalVerifier()
    status, evidence = verifier.verify(
        intent="browser_tab_open",
        result=_Result(tabs_before=3, tabs_after=4, windows_before=1, windows_after=2),
    )
    assert status == "FAILED", "a second Chrome window passed as a new tab"
    assert "window" in evidence.lower()


def test_a_tab_in_the_existing_window_verifies():
    verifier = GoalVerifier()
    status, evidence = verifier.verify(
        intent="browser_tab_open",
        result=_Result(tabs_before=3, tabs_after=4, windows_before=1, windows_after=1),
    )
    assert status == "VERIFIED_COMPLETE"


@pytest.mark.asyncio
async def test_an_effect_without_an_owning_task_is_denied():
    """The provenance gate: a desktop effect arriving with no task behind
    it - a stray debug call, a future background tick - is refused before
    anything on screen can change."""
    from pathlib import Path

    from app.schemas.approvals import PermissionLevel
    from app.tools.context import ToolContext
    from app.tools.errors import ToolPermissionError
    from app.tools_builtin.desktop import DesktopTool

    tool = DesktopTool(controller=object())  # never reached: refused first
    context = ToolContext(
        task_id=None, permission_level=PermissionLevel.L2, allowed_roots=(Path("."),))
    with pytest.raises(ToolPermissionError):
        await tool.execute({"action": "app_open", "app_id": "chrome"}, context)


def test_the_window_title_is_valid_tab_evidence_when_the_strip_lags():
    """Chrome's UIA tab strip is not exposed the instant a tab is born;
    the replayed new-tab goal failed 0->0 on tab counts even though the
    page loaded. Chrome's window title IS the active tab's title, so it
    proves the tab - but only when no window was created."""
    verifier = GoalVerifier()
    status, evidence = verifier.verify(
        intent="browser_tab_open",
        result=_Result(tabs_before=0, tabs_after=0, windows_before=1, windows_after=1,
                       tab_title="YouTube - Google Chrome"),
    )
    assert status == "VERIFIED_COMPLETE", evidence
    # A title with a NEW window behind it is still the old failure.
    status, _ = verifier.verify(
        intent="browser_tab_open",
        result=_Result(tabs_before=0, tabs_after=0, windows_before=1, windows_after=2,
                       tab_title="YouTube - Google Chrome"),
    )
    assert status == "FAILED"


# ======================================================================
# Gate B: the visible-browser page operator (2026-08-19)
# ======================================================================

@pytest.mark.parametrize("utterance,intent", [
    ("Search box me sonu nigam likho", "browser_page_type"),
    ("search box me \"luxora designs\" type karo", "browser_page_type"),
    ("Pehla result kholo.", "browser_first_result"),
    ("First result kholo", "browser_first_result"),
    ("Scroll down karo", "browser_page_scroll"),
    ("page ko neeche scroll karo", "browser_page_scroll"),
    ("Page pe kya hai?", "browser_page_read"),
    ("Is page pe kya dikh raha hai?", "browser_page_read"),
    ("Contact link pe click karo", "browser_page_click"),
    ("Submit button dabao", "browser_page_click"),
])
def test_page_operations_route_to_the_page_capabilities(utterance, intent):
    from app.runtime.task_classifier import TaskClassifier

    assert TaskClassifier().classify(utterance).intent == intent, utterance


def test_page_actions_are_imperatives_and_offered_only_then():
    from app.runtime.planner import GeneralPlanner
    from app.runtime.task_classifier import requests_external_action

    assert requests_external_action("Pehla result kholo.") is True
    names = [t.name for t in GeneralPlanner(model_router=None, providers={}).relevant_tools(
        "Pehla result kholo.")]
    assert "browser_first_result" in names
    # And a page QUESTION is still observation-only.
    names = [t.name for t in GeneralPlanner(model_router=None, providers={}).relevant_tools(
        "Page pe kya hai?")]
    assert not (set(names) & GeneralPlanner.EFFECT_CONTRACTS), names


def test_a_click_with_a_changed_title_verifies_and_a_missing_one_does_not():
    verifier = GoalVerifier()
    status, evidence = verifier.verify(
        intent="browser_first_result",
        result=_Result(summary="Opened the first result: 'Sonu Nigam top songs'",
                       title_before="sonu nigam - YouTube - Google Chrome",
                       title_after="Sonu Nigam Top Songs - YouTube - Google Chrome"),
    )
    assert status == "VERIFIED_COMPLETE", evidence
    status, _ = verifier.verify(
        intent="browser_page_click",
        result=_Result(),  # no summary, no titles: nothing was observed
    )
    assert status == "PARTIAL"


def test_a_page_reading_requires_real_observed_content():
    verifier = GoalVerifier()
    status, _ = verifier.verify(
        intent="browser_page_read",
        result=_Result(links=["Home", "Search"], observed=2, windows=[{"title": "x"}]),
    )
    assert status == "VERIFIED_COMPLETE"
    status, evidence = verifier.verify(
        intent="browser_page_read",
        result=_Result(),  # nothing was read
    )
    assert status != "VERIFIED_COMPLETE"

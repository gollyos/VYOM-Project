import pytest

from app.runtime.task_classifier import TaskClassifier
from app.schemas.events import BrainEvent, EventType
from app.schemas.tasks import TaskDomain
from app.security.permission_engine import PermissionEngine


def test_deterministic_classification_and_complexity():
    classifier = TaskClassifier()
    status = classifier.classify("What is my status today?")
    plan = classifier.classify("Plan my work for today.")
    coding = classifier.classify("Fix the TypeScript bug in this repository")
    close = classifier.classify("Close everything")

    assert status.intent == "daily_status" and status.complexity == 2
    assert plan.domain == TaskDomain.PLANNING and plan.complexity == 3
    assert coding.domain == TaskDomain.CODING and coding.complexity == 4
    assert close.deterministic and close.intent == "close_everything"


def test_permission_levels():
    engine = PermissionEngine()
    assert engine.classify("Explain today's status").value == "L0"
    assert engine.classify("Create a local work plan").value == "L1"
    assert engine.classify("Send email to the client").value == "L2"
    assert engine.classify("Transfer money for this payment").value == "L3"
    assert engine.requires_approval(engine.classify("Deploy the application"))


def test_event_schema_round_trip():
    event = BrainEvent(
        task_id="task_test",
        type=EventType.TASK_PROGRESS,
        human_readable_message="Running verification",
        structured_payload={"progress": 0.5},
    )
    restored = BrainEvent.model_validate_json(event.model_dump_json())
    assert restored.schema_version == 1
    assert restored.event_id.startswith("evt_")
    assert restored.type == EventType.TASK_PROGRESS
    assert restored.structured_payload["progress"] == 0.5



# ======================================================================
# Native operating layer: deterministic routing and goal verification
# ======================================================================
#
# Reconstructed from the 2026-08-17 voice session, where "Stop ho ja.
# Close kar do app." reached the general planner and was answered by
# OPENING Windows Terminal, Chrome and Notepad, and where completion was
# reported from tool counters rather than from the world.

def test_pc_control_commands_route_deterministically_with_no_model():
    """LAW 4: simple deterministic operations must bypass the model.

    Every one of these resolves to a registered tool intent, so the task
    runs on the local tool planner and costs zero model calls."""
    from app.runtime.task_classifier import TaskClassifier

    classifier = TaskClassifier()
    expected = {
        "Calculator kholo": "app_launch",
        "Bro calculator chala de": "app_launch",
        "Chrome kholo": "app_launch",
        "notepad kholo": "app_launch",
        "File Explorer me VYOM Project kholo": "app_launch",
        "Calculator me 27 guna 43 karo": "ui_interact",
        "Bluetooth settings kholo": "settings_open",
        "Settings kholo aur Bluetooth page dikhao": "settings_open",
        "Screen pe abhi kya open hai?": "screen_observe",
        "ye kya open hai": "screen_observe",
        "Ab Chrome band karo": "app_close",
        "Calculator band karo": "app_close",
    }
    for utterance, intent in expected.items():
        profile = classifier.classify(utterance)
        assert profile.intent == intent, f"{utterance!r} routed to {profile.intent}"
        assert profile.needs == {"tools"}, f"{utterance!r} must reach a real capability"


def test_unnamed_close_is_a_close_not_a_launch():
    """The exact utterance that made VYOM open three applications."""
    from app.runtime.task_classifier import TaskClassifier

    profile = TaskClassifier().classify("Stop ho ja. Close kar do app.")
    assert profile.intent == "app_close"


def test_naming_a_browser_means_the_visible_one_not_the_research_browser():
    """LAW 6. `web_browse` is a headless session the user cannot see;
    answering "Chrome me X kholo" with it and reporting success is a lie
    about what happened on their screen."""
    from app.runtime.task_classifier import TaskClassifier

    classifier = TaskClassifier()
    # A "new tab" request targets the browser already in use (the tab
    # capability), never a generic application launch - the 2026-08-19
    # physical session got a whole new Chrome window for every such
    # request. Updated from app_launch to browser_tab_open with that fix.
    assert classifier.classify("Isi Chrome me new tab kholo aur python.org kholo").intent == "browser_tab_open"
    assert classifier.classify("Chrome me youtube kholo").intent == "app_launch"
    # Pure information gathering still belongs to the research browser.
    assert classifier.classify("search the web for the latest python release").intent == "web_browse"


def test_spoken_arithmetic_is_parsed_without_a_model():
    from app.runtime.task_classifier import parse_arithmetic

    assert parse_arithmetic("Calculator me 27 guna 43 karo") == (27.0, "*", 43.0)
    assert parse_arithmetic("what is 12 plus 5") == (12.0, "+", 5.0)
    assert parse_arithmetic("100 divided by 4") == (100.0, "/", 4.0)
    assert parse_arithmetic("tell me about my business") is None


def test_only_a_real_world_postcondition_can_complete_a_goal():
    """LAW 1/2/3: a model's claim of success is not evidence, tool success
    is not goal success, and only a postcondition yields
    VERIFIED_COMPLETE."""
    from app.runtime.verifier import GoalVerifier
    from app.schemas.results import ExecutionResult
    from app.schemas.routing import UsageRecord

    def claimed(**data):
        return ExecutionResult(
            response="Done! I have completed that for you.", structured_data=data,
            evidence=["the model said so"], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    verifier = GoalVerifier()

    # A confident claim about an app that is not running cannot complete.
    status, _ = verifier.verify(
        intent="app_launch", result=claimed(app_id="vyom-app-never-running"))
    assert status == "FAILED"

    # A result with no evidence at all is PARTIAL - never a completion.
    status, _ = verifier.verify(intent="app_launch", result=claimed())
    assert status == "PARTIAL"

    # A calculation is complete only when the app's OWN display agrees.
    wrong, _ = verifier.verify(
        intent="ui_interact", result=claimed(expected="1161", display="Display is 42"))
    right, _ = verifier.verify(
        intent="ui_interact", result=claimed(expected="1161", display="Display is 1,161"))
    assert wrong == "FAILED" and right == "VERIFIED_COMPLETE"

    # A command that never reported an exit code has not been observed to
    # finish, however cheerful the response text is.
    status, _ = verifier.verify(intent="run_command", result=claimed())
    assert status == "FAILED"

    # Conversation has no world-effect and is not forced through this gate.
    status, _ = verifier.verify(intent="general", result=claimed())
    assert status == "NOT_APPLICABLE"


def test_rate_limit_opens_a_circuit_instead_of_retrying():
    """Section 18. The Brain log shows the same request id re-sent three
    times per model call across concurrent missions, all 429, no work
    completed. A rate limit now stops the caller."""
    from app.routing.provider_health import ProviderHealth

    health = ProviderHealth()
    assert health.available("google")

    health.record_rate_limit("google")
    assert not health.available("google"), "a rate-limited provider must not be called again"
    assert health.rate_limited("google")
    assert health.cooldown_remaining("google") > 0

    # An unrelated provider stays usable, so work can continue elsewhere.
    assert health.available("anthropic")

    # A later success clears the circuit.
    health.record_success("google")
    assert health.available("google")


def test_daily_quota_is_scoped_to_the_model_not_the_whole_provider():
    """Google meters the free tier as GenerateRequestsPerDayPerProjectPer
    MODEL. Blacklisting the whole provider when one model runs out would
    skip a sibling that still has allowance and fail work that could have
    succeeded - which is exactly what happened once the retry storm burned
    gemini-3.1-flash-lite's 500/day while gemini-flash-lite-latest was
    still answering normally."""
    from app.routing.provider_health import ProviderHealth

    health = ProviderHealth()
    health.record_rate_limit("google", "gemini-3.1-flash-lite", daily_quota=True)

    assert health.rate_limited("google", "gemini-3.1-flash-lite")
    assert not health.rate_limited("google", "gemini-flash-lite-latest"), (
        "a sibling model with its own quota must stay available"
    )
    # A daily quota does not come back in seconds; the backoff must be long
    # enough that the router genuinely moves on instead of busy-waiting.
    assert health.cooldown_remaining("google", "gemini-3.1-flash-lite") > 600

    # A provider-wide limit still implies every model beneath it.
    health.record_rate_limit("anthropic")
    assert health.rate_limited("anthropic", "claude-whatever")


def test_google_provider_distinguishes_daily_quota_from_a_burst_limit():
    """The two need opposite responses: wait briefly, versus change model."""
    import httpx

    from app.providers.google import _is_daily_quota

    def response(payload):
        return httpx.Response(429, json=payload)

    daily = response({"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
    burst = response({"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}]}})

    assert _is_daily_quota(daily) is True
    assert _is_daily_quota(burst) is False
    assert _is_daily_quota(response({})) is False


def test_background_health_events_are_tagged_so_they_stay_out_of_the_foreground():
    """LAW 8. Health telemetry reached the UI whenever no task was active -
    exactly when the user is looking at a calm screen - and painted
    CPU/RAM and "degraded" messages over it."""
    import asyncio

    from app.reliability.health import HealthAggregator, HealthState
    from app.schemas.events import EventType

    published = []

    class RecordingBus:
        async def publish(self, event):
            published.append(event)

    async def degraded_browser():
        return HealthState.DEGRADED

    aggregator = HealthAggregator(event_bus=RecordingBus())
    aggregator.register("browser", degraded_browser)
    asyncio.run(aggregator.assess())

    assert published, "a genuine degradation is still recorded internally"
    event = published[0]
    assert event.type == EventType.HEALTH_DEGRADED
    assert event.structured_payload["channel"] == "BACKGROUND_HEALTH"
    assert event.structured_payload["background"] is True


# ======================================================================
# Model-call amplification
# ======================================================================
#
# The 2026-08-17 voice session produced 30 tasks and 23 failures from 26
# utterances, because anything the classifier did not recognise reached a
# quota-exhausted model - including the user asking why it was failing.

def test_ordinary_pc_language_never_needs_a_model():
    """Section 13/15: the zero-model target for daily use."""
    from app.runtime.task_classifier import TaskClassifier

    zero_model_intents = {
        "app_launch", "app_close", "settings_open", "screen_observe", "ui_interact",
        "system_query", "profile_recall", "profile_statement", "runtime_introspection",
        "run_command", "run_tests", "fs_list",
        # Browser targets are distinct objects and each resolves locally.
        "browser_tab_close", "browser_tab_list", "browser_profile_open",
        "recover_visibility",
    }
    utterances = [
        "Calculator kholo", "Calculator खोलो", "the closer calculator",
        "Calculator band kar do", "Calculator बंद करो", "Chrome बंद करो",
        "इन पर मेरा Chrome ओपन है, उसमें YouTube ओपन है, उसको क्लोज कर दो।",
        "Bluetooth settings kholo", "स्क्रीन पर क्या ओपन है",
        "Python version bata", "Mere PC me sabse zyada RAM kaunsa process use kar raha hai?",
        "Mera naam kya hai?", "मेरा नाम क्या है?", "100 divided by 4",
        "Calculate 1036 * 1036.", "Git status bata",
    ]
    classifier = TaskClassifier()
    for utterance in utterances:
        profile = classifier.classify(utterance)
        assert profile.intent in zero_model_intents, (
            f"{utterance!r} routed to {profile.intent}, which costs a model call"
        )


def test_asking_why_something_failed_is_answered_from_local_state():
    """Section 11. VYOM was calling the rate-limited model to explain that
    the model was rate limited."""
    from app.runtime.task_classifier import TaskClassifier

    classifier = TaskClassifier()
    for question in (
        "Why this request is again and again failed?",
        "which provider is rate limited",
        "why is it taking so long",
        "abhi kya kar rahe ho?",
    ):
        profile = classifier.classify(question)
        assert profile.intent == "runtime_introspection"
        assert profile.needs == set(), "runtime diagnostics must not need a provider"


def test_devanagari_is_normalised_like_romanised_hinglish():
    """Gemini Live transcribes spoken Hindi in Devanagari. The romanised
    verb table never matched it, so plain instructions fell through."""
    from app.runtime.task_classifier import normalise_hinglish

    assert "close" in normalise_hinglish("Chrome बंद करो")
    assert "open" in normalise_hinglish("Calculator खोलो")
    assert "show" in normalise_hinglish("Bluetooth दिखाओ")


def test_the_operative_verb_in_hindi_is_the_last_one():
    """"मेरा Chrome ओपन है ... उसको क्लोज कर दो" states a fact and then
    gives an instruction. Hoisting every verb read it as a launch and
    opened Chrome again instead of closing it."""
    from app.runtime.task_classifier import TaskClassifier, normalise_hinglish

    utterance = "इन पर मेरा Chrome ओपन है, उसमें YouTube ओपन है, उसको क्लोज कर दो।"
    normalised = normalise_hinglish(utterance)
    assert normalised.startswith("close"), normalised
    # The object is the YouTube TAB, not the browser: the user described
    # Chrome as context and then named what to close inside it. Closing
    # Chrome would take every other tab with it.
    assert TaskClassifier().classify(utterance).intent == "browser_tab_close"
    # Naming only the browser still closes the browser.
    assert TaskClassifier().classify("Chrome बंद करो").intent == "app_close"


async def test_concurrent_missions_do_not_each_rediscover_the_same_429():
    """Section 14. Twenty simultaneous missions all found the circuit
    closed and all hit the same exhausted model. A bounded per-model
    concurrency budget means the first couple establish the truth."""
    import asyncio

    from app.providers.base import ProviderRateLimitError
    from app.routing.provider_health import ProviderHealth

    health = ProviderHealth()
    primary, fallback = ("google", "exhausted-model"), ("google", "healthy-model")
    calls = {"primary": 0, "fallback": 0}

    async def call(provider, model):
        if health.rate_limited(provider, model):
            raise ProviderRateLimitError("circuit open", daily_quota=True)
        async with health.slot(provider, model):
            if health.rate_limited(provider, model):
                raise ProviderRateLimitError("circuit open", daily_quota=True)
            await asyncio.sleep(0.01)
            if (provider, model) == primary:
                calls["primary"] += 1
                health.record_rate_limit(provider, model, daily_quota=True)
                raise ProviderRateLimitError("429", daily_quota=True)
            calls["fallback"] += 1
            return "ok"

    async def mission():
        for provider, model in (primary, fallback):
            try:
                return await call(provider, model)
            except ProviderRateLimitError:
                continue          # fallback, never a retry of the same target
        return "degraded"

    results = await asyncio.gather(*(mission() for _ in range(20)))

    assert results.count("ok") == 20, "a healthy model existed; no mission should fail"
    assert calls["primary"] <= health.MAX_CONCURRENT_PER_MODEL, (
        f"{calls['primary']} calls reached the exhausted model; the shared circuit did not hold"
    )
    assert health.rate_limited(*primary)
    assert not health.rate_limited(*fallback), "the sibling model must stay usable"


def test_a_browser_request_is_not_answered_with_a_directory_listing():
    """Section 10. "Open the Goli iOS profile" was answered with "VYOM
    Project contains 38 top-level entries" - a wrong-domain answer, which
    is worse than none because it looks like it worked."""
    from pathlib import Path

    from app.execution.action_engine import ActionEngine, CapabilityUnavailable
    from app.schemas.tasks import Task, TaskCreate, TaskDomain, TaskProfile

    engine = ActionEngine.__new__(ActionEngine)
    task = Task.from_create(TaskCreate(user_request="Open the Goli iOS profile in chrome"))
    profile = TaskProfile(domain=TaskDomain.CODING, complexity=2,
                          deterministic=True, intent="fs_list", needs={"tools"})
    with pytest.raises(CapabilityUnavailable):
        engine._reject_incompatible_capability(task, profile)

    # A genuine filesystem request is untouched.
    files = Task.from_create(TaskCreate(user_request="list the files in my project folder"))
    engine._reject_incompatible_capability(files, profile)

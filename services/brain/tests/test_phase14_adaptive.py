from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.adaptive import (
    AdaptiveConfig,
    AdaptiveContextService,
    AdaptiveLearner,
    AdaptivePolicyEngine,
    Experience,
    ExperienceStore,
    ProtectedPolicyError,
    ReuseAction,
    StrategyEngine,
    StrategyRecord,
    StrategyStatus,
    fingerprint,
    normalize_failure_signature,
    similarity,
)
from app.adaptive.evaluator import ExperimentationBudget, SelfEvaluator
from app.adaptive.context import resolve_reference
from app.adaptive.schemas import SOURCE_PRIORITY
from app.devices.schemas import utc_now
from app.persistence.database import Database


@pytest.fixture
async def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "p14.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
async def stack(database):
    store = ExperienceStore(database)
    strategies = StrategyEngine(database, AdaptiveConfig(minimum_strategy_sample=5))
    learner = AdaptiveLearner(store, strategies)
    return store, strategies, learner


def make_experience(goal: str, *, domain: str = "coding", success: bool = True,
                    verification: float = 0.9, environment: dict | None = None,
                    tools: list | None = None, conditions: dict | None = None,
                    failure: str | None = None, source: str = "experience",
                    correction: str | None = None) -> Experience:
    return Experience(
        goal=goal, domain=domain, success=success, verification_score=verification,
        task_fingerprint=fingerprint(goal), environment=environment or {"project": "vyom"},
        tools_used=tools or [], conditions=conditions or {},
        failure_signature=normalize_failure_signature(failure) if failure else None,
        failure_reason=failure, source=source, user_correction=correction,
    )


# --- 1/2: similar retrieval + irrelevant rejection --------------------------


async def test_similar_task_retrieval_and_irrelevant_rejection(stack):
    store, _, _ = stack
    await store.record(make_experience("Build the VYOM desktop application with Tauri and Vite"))
    await store.record(make_experience("Research competitor pricing for Finora", domain="research"))
    await store.record(make_experience("Prepare the weekly client report", domain="creative"))

    similar = await store.retrieve_similar("Add a new desktop workflow to the VYOM app", domain="coding")
    assert similar and "desktop" in " ".join(similar[0][0].task_fingerprint)
    scores = [score for _exp, score in similar]
    assert scores == sorted(scores, reverse=True)

    # An unrelated query must not return the coding experience as relevant.
    irrelevant = await store.retrieve_similar("Book a restaurant for Friday dinner", domain="research")
    assert all("desktop" not in " ".join(e.task_fingerprint) for e, _ in irrelevant)


async def test_memory_before_question_known_entity(stack):
    store, _, _ = stack
    await store.record(make_experience("Inspect the Finora client project structure"))
    assert await store.known_entity("finora") is not None
    assert await store.known_entity("unknown-client-xyz") is None


# --- 3: user corrections priority --------------------------------------------


async def test_user_correction_persists_and_outranks_inference(stack):
    store, _, learner = stack
    await store.record(make_experience("Summarize client research", source="model_inference",
                                        correction=None))
    correction = await learner.record_user_correction(
        goal="Summarize client research", domain="research",
        correction="Do not use provider X for sensitive client tasks",
    )
    retrieved = await store.retrieve_similar("Summarize client research", domain="research")
    sources = {e.source for e, _ in retrieved}
    assert "user_instruction" in sources
    winner = AdaptivePolicyEngine.resolve_conflict([e for e, _ in retrieved])
    assert winner.experience_id == correction.experience_id
    assert SOURCE_PRIORITY["user_instruction"] > SOURCE_PRIORITY["model_inference"]


async def test_user_correction_survives_restart(database):
    store = ExperienceStore(database)
    learner = AdaptiveLearner(store, StrategyEngine(database))
    await learner.record_user_correction(goal="Reports", domain="creative", correction="I prefer short reports")
    # Fresh instance on the same database = restart semantics.
    store2 = ExperienceStore(database)
    retrieved = await store2.retrieve_similar("Reports", domain="creative")
    assert any(e.user_correction == "I prefer short reports" for e, _ in retrieved)


# --- 4: reuse vs adapt vs replan ----------------------------------------------


async def test_reuse_when_conditions_match(stack):
    store, strategies, _ = stack
    record = StrategyRecord(domain="coding", name="vite-build-fix", conditions={"task_type": "build"},
                            actions=["check env", "install deps", "build"])
    await strategies.save(record)
    for _ in range(6):
        await strategies.record_outcome(record.strategy_id, success=True, score=1.0,
                                        conditions={"task_type": "build"})
    await store.record(make_experience("Build the project", verification=0.9))
    decision = await strategies.decide_reuse("Build the project again", "coding",
                                             {"project": "vyom"}, {"task_type": "build"}, store)
    assert decision.action == ReuseAction.REUSE
    assert decision.confidence > 0.5


async def test_adapt_when_environment_changed(stack):
    store, strategies, _ = stack
    record = StrategyRecord(domain="coding", name="vite-build-fix", conditions={"task_type": "build"})
    await strategies.save(record)
    for _ in range(6):
        await strategies.record_outcome(record.strategy_id, success=True, conditions={"task_type": "build"})
    await store.record(make_experience("Build the project", environment={"project": "vyom", "vite": "5"}))
    decision = await strategies.decide_reuse("Build the project", "coding",
                                             {"project": "vyom", "vite": "7"},  # framework changed
                                             {"task_type": "build"}, store)
    assert decision.action == ReuseAction.ADAPT
    assert any("environment changed" in reason for reason in decision.reasons)


async def test_replan_without_proven_strategy(stack):
    store, strategies, _ = stack
    await store.record(make_experience("Brand new kind of task", domain="creative"))
    decision = await strategies.decide_reuse("Another brand new task", "creative", {}, {}, store)
    assert decision.action == ReuseAction.REPLAN


# --- 5: environment change ------------------------------------------------------


async def test_environment_change_lowers_old_experience_ranking(stack):
    store, _, learner = stack
    await store.record(make_experience("Run the browser extraction", environment={"site_layout": "v1"},
                                       tools=["defuddle"]))
    await learner.detect_environment_change("site_layout", "v1", "v2", ["research"])
    ranked_before = await store.retrieve_similar("Run the browser extraction", environment={"site_layout": "v1"})
    ranked_after = await store.retrieve_similar("Run the browser extraction", environment={"site_layout": "v2"})
    assert ranked_before[0][1] > ranked_after[0][1]  # env mismatch decays retrieval confidence


# --- 6: failure lesson retrieval ---------------------------------------------------


async def test_failure_signature_and_lesson_retrieval(stack):
    store, _, _ = stack
    signature = normalize_failure_signature("Vite build failed: missing sidecar environment variable VYOM_ASSETS")
    assert "vite" in signature
    await store.record(make_experience("Build the desktop app", success=False, verification=0.0,
                                       failure="Vite build failed: missing sidecar environment variable"))
    failures = await store.retrieve_failures("Build the desktop app")
    assert failures and failures[0][0].failure_signature


# --- 7/8: model + tool performance learning -----------------------------------------


async def test_tool_routing_learns_from_evidence(stack):
    store, _, learner = stack
    for _ in range(3):
        await store.record(make_experience("Extract article content", domain="research", tools=["defuddle"],
                                           conditions={"site_type": "static"}, success=True))
    for _ in range(3):
        await store.record(make_experience("Extract dashboard data", domain="research", tools=["defuddle"],
                                           conditions={"site_type": "js_heavy"}, success=False,
                                           failure="defuddle empty content"))
    for _ in range(3):
        await store.record(make_experience("Extract dashboard data", domain="research", tools=["playwright"],
                                           conditions={"site_type": "js_heavy"}, success=True))
    preferred, evidence = await learner.preferred_tool(["defuddle", "playwright"], {"site_type": "js_heavy"})
    assert preferred == "playwright"
    assert "playwright" in evidence
    static_pick, _ = await learner.preferred_tool(["defuddle", "playwright"], {"site_type": "static"})
    assert static_pick == "defuddle"


async def test_model_performance_learning_by_domain(database, stack):
    from datetime import datetime, timezone

    store, _, learner = stack
    connection = database.require_connection()
    for model, domain, success in (
        ("model-a", "coding", 1), ("model-a", "coding", 1), ("model-a", "research", 0),
        ("model-b", "research", 1), ("model-b", "research", 1),
    ):
        await connection.execute(
            "INSERT INTO model_performance (model, provider, task_domain, complexity, success, verification_score, "
            "latency_ms, retries, fallback_used, usage_json, estimated_cost, created_at) "
            "VALUES (?, 'p', ?, 1, ?, 1.0, 100, 0, 0, '{}', 0.0, ?)",
            (model, domain, success, datetime.now(timezone.utc).isoformat()),
        )
    await connection.commit()
    performance = await learner.model_performance()
    assert performance["model-a"]["domains"]["coding"]["rate"] == 1.0
    assert performance["model-a"]["domains"]["research"]["rate"] == 0.0
    assert performance["model-b"]["domains"]["research"]["rate"] == 1.0  # best-for-context, not global


# --- 9-12: strategy context, decay, regime, low-sample -------------------------------


async def test_strategy_condition_matching_beats_aggregate(stack):
    _, strategies, _ = stack
    record = StrategyRecord(domain="trading", name="momentum")
    await strategies.save(record)
    # Strong in trending, weak in range — aggregate stays positive.
    for _ in range(8):
        await strategies.record_outcome(record.strategy_id, success=True, conditions={"regime": "trending_up"})
    for _ in range(6):
        await strategies.record_outcome(record.strategy_id, success=False, conditions={"regime": "range"})
    trending = strategies.evaluate(record, {"regime": "trending_up"})
    ranging = strategies.evaluate(record, {"regime": "range"})
    assert trending["score"] > ranging["score"]
    assert trending["by_regime"]["trending_up"]["rate"] == 1.0
    assert ranging["by_regime"]["range"]["rate"] == 0.0
    # Selection must NOT pick momentum in the range regime.
    other = StrategyRecord(domain="trading", name="range-fade")
    await strategies.save(other)
    for _ in range(8):
        await strategies.record_outcome(other.strategy_id, success=True, conditions={"regime": "range"})
    picked = await strategies.select("trading", {"regime": "range"})
    assert picked["strategy_id"] == other.strategy_id


async def test_strategy_decay_prefers_recent_performance(stack):
    _, strategies, _ = stack
    record = StrategyRecord(domain="coding", name="builder")
    await strategies.save(record)
    old_win = {"at": (utc_now() - timedelta(days=180)).isoformat(), "success": True}
    recent_loss = {"at": utc_now().isoformat(), "success": False}
    record.outcomes = [old_win] * 6 + [recent_loss] * 4
    await strategies.save(record)
    fresh = StrategyRecord(domain="coding", name="builder2")
    await strategies.save(fresh)
    fresh.outcomes = [{"at": (utc_now() - timedelta(days=180)).isoformat(), "success": False}] * 6 + \
                     [{"at": utc_now().isoformat(), "success": True}] * 4
    await strategies.save(fresh)
    assert strategies.evaluate(fresh, {})["decayed_rate"] > strategies.evaluate(record, {})["decayed_rate"]


async def test_low_sample_strategy_not_overtrusted(stack):
    _, strategies, _ = stack
    record = StrategyRecord(domain="coding", name="one-hit-wonder")
    await strategies.save(record)
    await strategies.record_outcome(record.strategy_id, success=True)  # n=1
    evaluation = strategies.evaluate(record, {})
    assert evaluation["sample_confidence"] < 0.3
    assert abs(evaluation["score"] - 0.5) < 0.25  # shrunk toward neutral


async def test_strategy_versioning_and_evidence_gate(stack):
    _, strategies, _ = stack
    record = StrategyRecord(domain="trading", name="momentum", version="1.0")
    await strategies.save(record)
    proposal = await strategies.propose_evolution(record.strategy_id, "drawdown in high volatility",
                                                  {"recent_loss_rate": 0.7})
    assert proposal.to_version == "1.1" and proposal.from_version == "1.0"
    rejected = StrategyEngine.evaluate_proposal(
        proposal,
        backtest={"current_metric": 1.2, "candidate_metric": 0.8},
        validation={"current_metric": 1.1, "candidate_metric": 0.9},
    )
    assert rejected.state == "rejected"  # weak evidence never replaces a working version
    promotable = StrategyEngine.evaluate_proposal(
        proposal,
        backtest={"current_metric": 1.0, "candidate_metric": 1.4},
        validation={"current_metric": 1.0, "candidate_metric": 1.3},
    )
    assert promotable.state == "promotable"
    assert promotable.approved_by_user is False  # promotion itself still needs the user


async def test_strategy_degradation_pauses_not_forever(stack):
    _, strategies, _ = stack
    record = StrategyRecord(domain="trading", name="fade", status=StrategyStatus.ACTIVE)
    await strategies.save(record)
    for _ in range(5):
        await strategies.record_outcome(record.strategy_id, success=False)
    reviewed = await strategies.review_status(record.strategy_id)
    # 100% failure escalates DEGRADED -> PAUSED: a broken strategy is
    # not kept running (rule 34).
    assert reviewed.status in (StrategyStatus.DEGRADED, StrategyStatus.PAUSED)
    assert reviewed.status == StrategyStatus.PAUSED


# --- 13: protected policies + risk immutability ------------------------------------


def test_risk_limits_cannot_be_autonomously_increased():
    engine = AdaptivePolicyEngine()
    with pytest.raises(ProtectedPolicyError):
        engine.apply_risk_change("max_risk_per_trade", current=0.02, proposed=0.05)
    with pytest.raises(ProtectedPolicyError):
        engine.apply_risk_change("max_drawdown", current=0.1, proposed=0.2)
    decrease = engine.apply_risk_change("max_risk_per_trade", current=0.02, proposed=0.01)
    assert decrease["applied"]


def test_no_security_policy_self_modification():
    engine = AdaptivePolicyEngine()
    for protected in ("permission_engine", "secret_store", "security_boundary", "l2_l3_requirements"):
        with pytest.raises(ProtectedPolicyError):
            engine.apply(protected, {"anything": True})
    assert engine.apply("model_preference", {"openai": +0.1})["applied"]
    assert engine.apply("strategy_ranking", {"momentum": -0.2})["applied"]


# --- 14: cross-session continuation ---------------------------------------------------


async def test_cross_session_continuation(stack):
    store, _, _ = stack
    await store.record(make_experience("Research Finora competitors", domain="research",
                                        success=True, verification=0.9))
    failed = make_experience("Draft outreach from the research", domain="research",
                             success=False, failure="provider disconnected")
    failed.created_at = utc_now() - timedelta(minutes=1)
    await store.record(failed)
    context = AdaptiveContextService(store)
    continuation = await context.continue_from_previous_session()
    assert continuation["can_continue"] is True
    assert continuation["last_verified"]["goal"] == "Research Finora competitors"
    assert continuation["unfinished"]["failure"] == failed.failure_signature


def test_reference_resolution():
    assert resolve_reference("Make a presentation from that", ["Research Finora competitors"]) == "Research Finora competitors"
    assert resolve_reference("Build the report", ["x"]) is None


# --- 15: unknown-task path + bounded experimentation ----------------------------------


async def test_unknown_task_triggers_capability_research_path(stack):
    """When no capability matches, the context service reports a replan
    decision — the unknown-task path then routes to the existing
    discovery/research engines instead of failing."""
    store, strategies, _ = stack
    context = AdaptiveContextService(store)
    built = await context.build_experience_context(
        "Convert audio to sheet music", "creative", {}, {},
        strategy_engine=strategies,
    )
    assert built.reuse_decision.action == ReuseAction.REPLAN
    assert built.similar_experiences == []


def test_bounded_experimentation():
    budget = ExperimentationBudget(exploration_rate=1.0, max_experiments=2,
                                   rng=__import__("random").Random(0))
    assert budget.should_explore(["a", "b"], risk="low") is not None
    assert budget.should_explore(["a", "b"], risk="low") is not None
    assert budget.should_explore(["a", "b"], risk="low") is None  # daily cap reached
    safe = ExperimentationBudget(exploration_rate=1.0, rng=__import__("random").Random(0))
    assert safe.should_explore(["a", "b"], risk="consequential") is None  # never on L3


# --- 16: evaluation + consolidation ------------------------------------------------------


def test_self_evaluation_deterministic_and_cheap():
    failed = make_experience("Build", success=False, verification=0.0, failure="env missing")
    result = SelfEvaluator.evaluate(failed)
    assert result["questions"]["completed"] is False
    assert result["questions"]["reusable_lesson"] is True
    assert "failure" in (result["improvement_hint"] or "")
    clean = make_experience("Status", success=True, verification=1.0)
    assert SelfEvaluator.should_evaluate(clean) is False  # trivial verified work skips evaluation


async def test_experience_consolidation(stack):
    store, _, _ = stack
    for index in range(6):
        experience = make_experience(f"Build the VYOM desktop app variant {index}")
        await store.record(experience)
    summaries = await store.consolidate(threshold=5)
    assert summaries and summaries[0]["sample_size"] == 6
    assert "generalized_lesson" in summaries[0]
    assert await store.get(summaries[0]["representative"]) is not None  # originals kept


# --- 17: live-task learning through the runtime -----------------------------------------


async def test_bridge_learning_from_real_task(database):
    from tests.helpers import build_runtime, close_harness
    from app.runtime.event_bus import EventBus
    from app.schemas.tasks import TaskCreate

    harness = await build_runtime(database.path.parent / "bridge.db")
    try:
        store = ExperienceStore(database)
        learner = AdaptiveLearner(store, StrategyEngine(database))
        from app.adaptive.learner import AdaptiveLearningBridge

        bridge = AdaptiveLearningBridge(harness.event_bus if hasattr(harness, "event_bus") else EventBus(), learner, harness.task_store)
        # The harness exposes the runtime's event bus through runtime; use it directly.
        bridge = AdaptiveLearningBridge(harness.runtime.event_bus, learner, harness.task_store)
        bridge.start()
        task = await harness.runtime.create_task(TaskCreate(user_request="What is my status today?"))
        from tests.helpers import wait_for_status

        await wait_for_status(harness.task_store, task.id, {"completed", "failed"}, timeout=10)
        import asyncio

        await asyncio.sleep(0.3)  # let the bridge consume the completion event
        await bridge.stop()
        experiences = await store._all()
        assert any(e.task_id == task.id for e in experiences)
    finally:
        await close_harness(harness)


def test_fingerprint_similarity_basics():
    left = fingerprint("Build the VYOM desktop application")
    right = fingerprint("Add a new desktop workflow")
    unrelated = fingerprint("Book a table at the restaurant")
    assert similarity(left, right) > similarity(left, unrelated)

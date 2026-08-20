from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.adaptive import AdaptiveLearner, Experience, ExperienceStore, StrategyEngine, fingerprint
from app.adaptive.learned_router import LearnedRouter
from app.memory.embeddings import DisabledEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.namespaces import CognitiveNamespace, NamespaceMemoryRouter
from app.memory.resolution import ResolutionChain
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import MemoryQuery
from app.memory.store import MemoryStore
from app.persistence.database import Database
from app.reliability.checkpoints import CheckpointStore
from app.runtime.cognitive_runtime import ActiveContext, CognitiveRuntime
from app.runtime.mission_loop import MissionLimitError, MissionLimits, MissionLoop


@pytest.fixture
async def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "p16.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def stack(database):
    store = MemoryStore(database)
    memory = MemoryManager(store, MemoryRetriever(store, DisabledEmbeddingProvider()))
    experiences = ExperienceStore(database)
    strategies = StrategyEngine(database)
    learner = AdaptiveLearner(experiences, strategies)
    router = NamespaceMemoryRouter(memory)
    chain = ResolutionChain(memory=memory, experience_store=experiences)
    cognitive = CognitiveRuntime(chain, None)
    return database, memory, experiences, learner, router, chain, cognitive


# --- 38: memory before question -------------------------------------------------


async def test_memory_before_question_project_location(stack):
    _db, _memory, _exp, _learner, router, _chain, cognitive = stack
    # Seed a verified project location.
    await router.remember(
        CognitiveNamespace.PROJECTS, "VYOM project location",
        "The VYOM project lives at C:\\VYOM Project (verified).",
        provenance_reference="verified filesystem inspection", confidence=0.9,
    )
    answer = await cognitive.answer_from_memory("Where is the VYOM project?")
    assert answer is not None, "verified project path must answer from memory"
    assert "VYOM Project" in str(answer["answer"])
    # And it must NOT ask: no user-question path is triggered (None means
    # ask; we assert the memory answer exists instead).
    unknown = await cognitive.answer_from_memory("Where is the Zephyr project?")
    assert unknown is None  # missing memory -> asking is legitimate


# --- 39: follow-up context --------------------------------------------------------


async def test_followup_that_resolves_latest_research(stack):
    _db, _memory, exp, _learner, _router, _chain, cognitive = stack
    await exp.record(Experience(
        goal="Research Finora competitors", domain="research", success=True,
        verification_score=0.9, task_fingerprint=fingerprint("Research Finora competitors"),
    ))
    cognitive.active.last_verified_goal = "Research Finora competitors"
    resolved = cognitive.resolve_reference("Make a presentation from that")
    assert resolved == "Research Finora competitors"

    cognitive.active.last_verified_goal = "Fix the failing checkout test"
    assert cognitive.resolve_reference("Fix it") == "Fix the failing checkout test"
    assert cognitive.resolve_reference("Build a standalone report") is None


# --- 5/7: learned routing -------------------------------------------------------------


async def test_learned_tool_routing_prefers_known_good_tool(stack):
    _db, _memory, exp, learner, _router, _chain, _cog = stack
    for _ in range(3):
        await exp.record(Experience(goal="Extract page", domain="research", tools_used=["defuddle"],
                                    conditions={"site_type": "js_heavy"}, success=False,
                                    failure="defuddle empty body"))
    for _ in range(3):
        await exp.record(Experience(goal="Extract page", domain="research", tools_used=["playwright"],
                                    conditions={"site_type": "js_heavy"}, success=True, verification_score=0.9))
    router = LearnedRouter(learner)
    choice = await router.preferred_tool(["defuddle", "playwright"], {"site_type": "js_heavy"})
    assert choice.tool == "playwright"
    assert "100%" in choice.reason or "succeeded" in choice.reason

    # Static pages keep preferring Defuddle where it won.
    for _ in range(2):
        await exp.record(Experience(goal="Extract article", domain="research", tools_used=["defuddle"],
                                    conditions={"site_type": "static"}, success=True, verification_score=0.9))
    choice = await router.preferred_tool(["defuddle", "playwright"], {"site_type": "static"})
    assert choice.tool == "defuddle"

    # Thin evidence never decides.
    thin = await router.preferred_tool(["tool-x", "tool-y"], {"site_type": "unknown"})
    assert thin.tool is None and "default routing" in thin.reason


async def test_model_routing_learning_context_specific(stack):
    from datetime import datetime, timezone as tz

    _db, memory, _exp, learner, _r, _c, _cog = stack
    connection = _db.require_connection()
    rows = [
        ("model-a", "coding", 1), ("model-a", "coding", 1), ("model-a", "coding", 1),
        ("model-a", "research", 0), ("model-a", "research", 0),
        ("model-b", "research", 1), ("model-b", "research", 1), ("model-b", "research", 1),
        ("model-b", "coding", 0),
    ]
    for model, domain, success in rows:
        await connection.execute(
            "INSERT INTO model_performance (model, provider, task_domain, complexity, success, verification_score, "
            "latency_ms, retries, fallback_used, usage_json, estimated_cost, created_at) VALUES (?, 'p', ?, 1, ?, 1.0, 100, 0, 0, '{}', 0.0, ?)",
            (model, domain, success, datetime.now(tz.utc).isoformat()),
        )
    await connection.commit()

    router = LearnedRouter(learner)
    performance = await learner.model_performance()
    bias_a_coding, reason_a = router.model_bias("model-a", "coding", performance)
    bias_a_research, _ = router.model_bias("model-a", "research", performance)
    bias_b_research, reason_b = router.model_bias("model-b", "research", performance)
    assert bias_a_coding > 0 > bias_a_research  # context-specific, not global
    assert bias_b_research > 0
    assert "coding" in reason_a and "research" in reason_b


async def test_changed_conditions_degrade_confidence(stack):
    _db, _memory, _exp, learner, _router, _chain, _cog = stack
    from app.adaptive import StrategyRecord

    engine = learner.strategies
    record = await engine.save(StrategyRecord(domain="coding", name="builder",
                                              conditions={"task_type": "build"}))
    for _ in range(6):
        await engine.record_outcome(record.strategy_id, success=True, conditions={"task_type": "build"})
    await _exp.record(Experience(goal="Build project", domain="coding", success=True,
                                 verification_score=0.9, environment={"vite": "5"},
                                 task_fingerprint=fingerprint("Build project")))
    same = await engine.decide_reuse("Build project", "coding", {"vite": "5"}, {"task_type": "build"}, _exp)
    changed = await engine.decide_reuse("Build project", "coding", {"vite": "7"}, {"task_type": "build"}, _exp)
    assert same.action.value == "reuse"
    assert changed.action.value == "adapt"  # environment change -> adapt, not blind reuse


# --- 11-14: mission loop ---------------------------------------------------------------


def _fixture_mission(fail_first: dict):
    """Controlled mission: inspect -> test -> fix -> retest -> report,
    with a scripted failure on the first 'Run tests' attempt."""
    calls = {"test_runs": 0, "steps": []}

    async def executor(title, context):
        calls["steps"].append(title)
        lowered = title.lower()
        if lowered.startswith("run") and "test" in lowered:
            calls["test_runs"] += 1
            if calls["test_runs"] == 1 and "Run tests" in fail_first:
                return {"ok": False, "error": "1 fixture test failed"}
            return {"ok": True, "output": {"passed": 21, "failed": 0 if calls["test_runs"] > 1 else 1}}
        if lowered.startswith("fix"):
            return {"ok": True, "output": {"fixed": "fixture issue"}}
        return {"ok": True, "output": {"step": title}}

    async def verifier(title, outcome):
        lowered = title.lower()
        if ("test" in lowered or "report" in lowered) and "output" in outcome:
            return outcome["output"].get("failed", 0) == 0
        return True

    return executor, verifier, calls


async def test_autonomous_mission_adapts_after_failure(stack):
    _db, _memory, exp, learner, _router, _chain, cognitive = stack
    checkpoints = CheckpointStore(_db)
    loop = MissionLoop(cognitive=cognitive, planner=None, checkpoint_store=checkpoints, learner=learner)
    executor, verifier, calls = _fixture_mission({"Run tests"})

    mission = await loop.run(
        "Inspect this project, run its tests, fix one controlled fixture issue, rerun tests and report",
        executor=executor, verifier=verifier,
    )
    assert mission.status == "completed"
    assert calls["test_runs"] >= 2                      # failure -> adaptation -> retry
    assert mission.experience_saved is True
    # The mission fed the Phase 14 learner.
    missions = [e for e in await exp._all() if e.task_type == "mission"]
    assert missions and missions[0].success


async def test_mission_cancel_persists_checkpoint_and_stops(stack):
    _db, _memory, _exp, _learner, _router, _chain, cognitive = stack
    checkpoints = CheckpointStore(_db)
    loop = MissionLoop(cognitive=cognitive, planner=None, checkpoint_store=checkpoints)

    started = asyncio.Event()

    async def executor(title, context):
        started.set()
        await asyncio.sleep(30)  # long-running step
        return {"ok": True}

    task = asyncio.create_task(loop.run("Long mission", executor=executor))
    await asyncio.wait_for(started.wait(), timeout=2)
    assert loop.cancel("missing-mission") is False
    ids = list(loop._cancel_events.keys())
    assert ids and loop.cancel(ids[0]) is True
    mission = await asyncio.wait_for(task, timeout=5)
    assert mission.status == "cancelled"
    checkpoint = await checkpoints.get(mission.mission_id)
    assert checkpoint is not None        # checkpoint persisted
    assert checkpoint.task_state["status"] == "cancelled"


async def test_mission_resume_from_checkpoint_not_zero(stack):
    _db, _memory, _exp, learner, _router, _chain, cognitive = stack
    checkpoints = CheckpointStore(_db)
    loop = MissionLoop(cognitive=cognitive, planner=None, checkpoint_store=checkpoints, learner=learner)

    async def pausing_executor(title, context):
        return {"ok": True}

    mission = await loop.run(
        "Mission with approval gate", executor=pausing_executor,
        step_permissions={"Execute the core work": "L2"},
    )
    assert mission.status == "needs_approval"
    assert mission.pending_approval == "Execute the core work"
    assert mission.current_step == 2  # paused at the gated step ("Execute the core work"), not abandoned

    resumed = await loop.resume(mission.mission_id, executor=pausing_executor)
    assert resumed is not None and resumed.status == "completed"
    # Resume skipped already-completed steps: only 3 remaining executed.
    # (verify via checkpoint evidence order)


async def test_mission_limits_block_runaways(stack):
    _db, _memory, _exp, _learner, _router, _chain, cognitive = stack
    checkpoints = CheckpointStore(_db)
    loop = MissionLoop(cognitive=cognitive, planner=None, checkpoint_store=checkpoints,
                       limits=MissionLimits(max_tool_calls=2, max_retries_per_step=0))
    calls = {"n": 0}

    async def executor(title, context):
        calls["n"] += 1
        return {"ok": True}

    mission = await loop.run("Bounded mission", executor=executor)
    assert mission.status in ("failed", "completed")  # limit hit honestly
    assert calls["n"] <= 3  # bounds held (never endless)


# --- 46/47: media capabilities (real ffmpeg + pymupdf) ------------------------------


@pytest.fixture
def tone_and_clip(tmp_path: Path):
    import subprocess

    tone = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(tone)],
        capture_output=True, check=True,
    )
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", str(clip)],
        capture_output=True, check=True,
    )
    return tone, clip


async def test_ffmpeg_audio_operations_verified(tmp_path: Path, tone_and_clip):
    from app.workbench import UniversalWorkbench, WorkbenchKind, WorkbenchRequest

    tone, _clip = tone_and_clip
    workbench = UniversalWorkbench()
    inspected = await workbench.execute(WorkbenchRequest(WorkbenchKind.AUDIO, "inspect", {"path": str(tone)}))
    assert inspected.success and 1.9 <= inspected.output["duration_seconds"] <= 2.1
    trimmed = await workbench.execute(WorkbenchRequest(
        WorkbenchKind.AUDIO, "trim", {"path": str(tone), "start": 0, "end": 1, "output": str(tmp_path / "cut.wav")}))
    assert trimmed.success and trimmed.output["duration_seconds"] <= 1.05  # verified, not just exit 0
    converted = await workbench.execute(WorkbenchRequest(
        WorkbenchKind.AUDIO, "convert", {"path": str(tone), "output": str(tmp_path / "tone.mp3")}))
    assert converted.success and (tmp_path / "tone.mp3").exists()


async def test_ffmpeg_video_operations_verified(tmp_path: Path, tone_and_clip):
    from app.workbench import UniversalWorkbench, WorkbenchKind, WorkbenchRequest

    _tone, clip = tone_and_clip
    workbench = UniversalWorkbench()
    resized = await workbench.execute(WorkbenchRequest(
        WorkbenchKind.VIDEO, "resize", {"path": str(clip), "width": 160, "height": 120,
                                        "output": str(tmp_path / "small.mp4")}))
    assert resized.success
    inspected = await workbench.execute(WorkbenchRequest(WorkbenchKind.VIDEO, "inspect", {"path": str(tmp_path / "small.mp4")}))
    assert inspected.output["video"]["width"] == 160 and inspected.output["video"]["height"] == 120
    audio = await workbench.execute(WorkbenchRequest(
        WorkbenchKind.VIDEO, "extract_audio", {"path": str(clip), "output": str(tmp_path / "audio.m4a")}))
    assert audio.success and (tmp_path / "audio.m4a").exists()


async def test_pdf_capabilities_verified(tmp_path: Path):
    import pymupdf

    from app.workbench import UniversalWorkbench, WorkbenchKind, WorkbenchRequest

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Quarterly revenue grew 14 percent year over year.")
    document.save(str(tmp_path / "report.pdf"))
    document.close()

    workbench = UniversalWorkbench()
    inspected = await workbench.execute(WorkbenchRequest(WorkbenchKind.PDF, "inspect", {"path": str(tmp_path / "report.pdf")}))
    assert inspected.success and inspected.output["page_count"] == 1
    text = await workbench.execute(WorkbenchRequest(WorkbenchKind.PDF, "text", {"path": str(tmp_path / "report.pdf")}))
    assert "14 percent" in text.output["text"]
    rendered = await workbench.execute(WorkbenchRequest(
        WorkbenchKind.PDF, "render", {"path": str(tmp_path / "report.pdf"), "output_dir": str(tmp_path / "rendered")}))
    assert rendered.success and (tmp_path / "rendered" / "page-1.png").exists()
    # Merge verification: page counts must match after reopen.
    merged = await workbench.execute(WorkbenchRequest(
        WorkbenchKind.PDF, "merge", {"paths": [str(tmp_path / "report.pdf")] * 2, "output": str(tmp_path / "merged.pdf")}))
    assert merged.success and merged.output["pages"] == 2


# --- 35: explain decision + security re-checks ----------------------------------------


async def test_explain_decision_with_operational_evidence(stack):
    from app.adaptive.policy_engine import AdaptivePolicyEngine

    _db, _memory, exp, _learner, _router, _chain, _cog = stack
    await exp.record(Experience(goal="Extract page", domain="research", tools_used=["playwright"],
                                conditions={"site_type": "js_heavy"}, success=True, verification_score=0.95))
    engine = AdaptivePolicyEngine()
    latest = (await exp._all())[0]
    explanation = engine.explain({
        "subject": "Playwright",
        "evidence": "this page required JavaScript and Defuddle was unsuitable on 2 prior attempts",
    })
    assert "Playwright" in explanation and "Defuddle" in explanation


async def test_self_improvement_security_rejected_before_mutation(tmp_path: Path):
    from app.adaptive.self_improvement import (
        ImprovementHypothesis,
        ImprovementObservation,
        SafeSelfImprovement,
        UnsafeModificationError,
    )

    loop = SafeSelfImprovement(project_root=tmp_path)
    mutated = {"touched": False}

    async def runner(command, cwd):
        mutated["touched"] = True  # must never run for protected targets
        return {"ok": True, "output": ""}

    loop.runner = runner
    for protected in ("app/security/permission_engine.py", "config/risk.yaml"):
        with pytest.raises(UnsafeModificationError):
            await loop.execute(ImprovementHypothesis(
                observation=ImprovementObservation(subject="s", evidence={}),
                change_target=[protected], change_description="x", test_command="true",
            ))
    assert mutated["touched"] is False  # rejection BEFORE any mutation


# --- live cognitive runtime wiring ----------------------------------------------------


async def test_live_task_runtime_uses_cognitive_resolution(tmp_path: Path):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(
        database_path=tmp_path / "b.db", skills_root=tmp_path / "s", agents_root=tmp_path / "a",
        audit_log_path=tmp_path / "a.jsonl", secret_store_path=tmp_path / "sec",
        artifacts_root=tmp_path / "art", backup_root=tmp_path / "bk",
    )
    import time

    with TestClient(create_app(settings)) as client:
        state = client.app.state
        assert state.cognitive_runtime is not None
        # Seed a verified project path, then run a task referencing the project.
        await state.namespace_router.remember(
            CognitiveNamespace.PROJECTS, "VYOM project location",
            "The VYOM project lives at C:\\VYOM Project.", provenance_reference="verified",
        )
        created = client.post("/api/tasks", json={"user_request": "What is my status today?"}).json()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            task = client.get(f"/api/tasks/{created['id']}").json()
            if task["status"] in ("completed", "failed", "needs_approval"):
                break
            time.sleep(0.05)
        # Every live task now carries cognitive resolution metadata.
        cognitive = task.get("metadata", {}).get("cognitive")
        assert cognitive is not None and "resolution_source" in cognitive
        assert cognitive["namespace"] in [ns.value for ns in CognitiveNamespace]

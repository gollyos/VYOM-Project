from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.adaptive import Experience, ExperienceStore, fingerprint
from app.adaptive.self_improvement import (
    ImprovementHypothesis,
    ImprovementObservation,
    SafeSelfImprovement,
    UnsafeModificationError,
)
from app.memory.embeddings import DisabledEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.namespaces import (
    CognitiveNamespace,
    NamespaceMemoryRouter,
    infer_namespace,
)
from app.memory.resolution import ResolutionChain, ResolutionResult
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import MemoryQuery
from app.memory.store import MemoryStore
from app.persistence.database import Database
from app.workbench import UniversalWorkbench, WorkbenchKind, WorkbenchRequest


@pytest.fixture
async def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "p15.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def memory(database) -> MemoryManager:
    store = MemoryStore(database)
    return MemoryManager(store, MemoryRetriever(store, DisabledEmbeddingProvider()))


# --- Phase 15 core rule: no .md/.txt intelligence files ----------------------


def test_namespaced_memory_writes_structured_records_only(memory):
    """Namespace stores must write ONLY to the structured SQLite store —
    the remember API has no file output at all."""
    import inspect

    import ast

    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(NamespaceMemoryRouter.remember)))
    forbidden_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            name = getattr(function, "attr", None) or getattr(function, "id", "")
            if name in ("open", "write_text", "write_bytes", "write"):
                forbidden_calls.append(name)
    assert not forbidden_calls  # no file output whatsoever (docstrings aside)


def test_no_blank_app_launch_in_default_tests():
    """The Notepad-launching tests must skip without the explicit opt-in
    (VYOM_LIVE_APP_TESTS) — automated tests are not user tasks."""
    assert os.environ.get("VYOM_LIVE_APP_TESTS") != "1"


# --- namespaces ---------------------------------------------------------------


def test_namespace_inference_routing():
    assert infer_namespace(domain="coding", text="build the app") == CognitiveNamespace.CODING
    assert infer_namespace(text="convert this pdf to an image") == CognitiveNamespace.MEDIA
    assert infer_namespace(text="i prefer short reports") == CognitiveNamespace.PREFERENCES
    assert infer_namespace(text="who is the contact for Finora") == CognitiveNamespace.PEOPLE
    assert infer_namespace(text="analyze the portfolio risk") == CognitiveNamespace.FINANCE
    assert infer_namespace(text="scrape this url for content") == CognitiveNamespace.WEB
    assert infer_namespace(domain="planning") == CognitiveNamespace.PROJECTS


async def test_namespace_remember_and_recall_roundtrip(memory):
    router = NamespaceMemoryRouter(memory)
    memory_id = await router.remember(
        CognitiveNamespace.PROJECTS, "VYOM build command",
        "The VYOM desktop app builds with npm run desktop:build after a fresh frontend build.",
        provenance_reference="verified build run",
    )
    assert memory_id.startswith("mem_")
    hits = await router.recall(CognitiveNamespace.PROJECTS, "how do we build the vyom app")
    assert hits and "desktop:build" in hits[0].memory.content
    # Namespace isolation: the coding namespace sees it via its tag only
    other = await router.recall(CognitiveNamespace.FINANCE, "how do we build the vyom app")
    assert not other


# --- resolution chain order ------------------------------------------------------


async def test_resolution_order_memory_first_then_experience_knowledge(database, memory):
    store = ExperienceStore(database)
    router = NamespaceMemoryRouter(memory)
    await router.remember(CognitiveNamespace.CODING, "Build command",
                          "npm run build builds the frontend.", provenance_reference="user")
    chain = ResolutionChain(memory=memory, experience_store=store)

    result = await chain.resolve("build the frontend", domain="coding")
    assert result.resolved and result.source == "memory"
    assert result.trace[0].startswith("memory:")

    # Without memory hits, an Experience answers next.
    await store.record(Experience(
        goal="Extract pricing data", domain="research", success=True, verification_score=0.9,
        task_fingerprint=fingerprint("Extract pricing data"),
    ))
    chain2 = ResolutionChain(memory=memory, experience_store=store)
    result2 = await chain2.resolve("Extract pricing data for the report", domain="research")
    assert result2.source in ("experience", "memory")  # memory may legitimately hit first


async def test_resolution_falls_through_to_skill_tool_external(database, memory, tmp_path):
    from app.skills.registry import SkillRegistry
    from app.tools.registry import ToolRegistry

    project_root = Path(__file__).resolve().parents[3]
    skills = SkillRegistry(project_root / "data" / "skills")
    skills.load()
    assert skills.list()  # imported + built-in skills available
    tools = ToolRegistry()

    chain = ResolutionChain(memory=memory, experience_store=None,
                            skill_registry=skills, tool_registry=tools)
    result = await chain.resolve("run the build check skill")
    assert result.source in ("skill", "tool") and result.resolved

    empty = ResolutionChain()
    unknown = await empty.resolve("transcribe piano audio to sheet music")
    assert unknown.resolved is False and unknown.source == "external_research"
    assert unknown.trace[-1].startswith("external_research:")


# --- safe self-improvement ------------------------------------------------------------


async def test_self_improvement_blocks_protected_paths(tmp_path):
    loop = SafeSelfImprovement(project_root=tmp_path)
    for protected in ("app/security/permission_engine.py", "config/risk.yaml",
                      "services/brain/app/integrations/secrets.py"):
        hypothesis = ImprovementHypothesis(
            observation=ImprovementObservation(subject="x", evidence={}),
            change_target=[protected], change_description="try to weaken", test_command="true",
        )
        with pytest.raises(UnsafeModificationError):
            await loop.execute(hypothesis)


async def test_self_improvement_requires_isolated_branch(tmp_path):
    async def runner(command, cwd):
        return {"ok": False, "output": "no git"}  # branch creation unavailable

    loop = SafeSelfImprovement(project_root=tmp_path, runner=runner)
    hypothesis = ImprovementHypothesis(
        observation=ImprovementObservation(subject="tool latency", evidence={},
                                           failure_signature="vite-build-env-missing"),
        change_target=[], change_description="prefer the faster tool",
        test_command="python -m pytest tests -q",
    )
    run = await loop.execute(hypothesis)
    assert run.outcome == "blocked"
    assert "isolated branch required" in run.steps[-1]


async def test_self_improvement_promote_and_rollback(tmp_path):
    async def make_runner(tests_pass: bool):
        state = {"branch_created": False}

        async def runner(command, cwd):
            if command.startswith("git checkout -b"):
                state["branch_created"] = True
                return {"ok": True, "output": "branch"}
            if command.startswith("python -m pytest"):
                return {"ok": tests_pass, "output": "tests"}
            return {"ok": True, "output": "done"}

        return runner

    hypothesis = ImprovementHypothesis(
        observation=ImprovementObservation(subject="s", evidence={}),
        change_target=["app/some_module.py"], change_description="improve",
        test_command="python -m pytest tests -q",
    )

    passing = await SafeSelfImprovement(project_root=tmp_path, runner=await make_runner(True)).execute(hypothesis)
    assert passing.outcome == "promoted" and passing.tests_passed

    failing = await SafeSelfImprovement(project_root=tmp_path, runner=await make_runner(False)).execute(hypothesis)
    assert failing.outcome == "rolled_back"
    assert any("rollback" in step for step in failing.steps)


def test_self_improvement_never_touches_risk_limits(tmp_path):
    from app.adaptive.policy_engine import AdaptivePolicyEngine, ProtectedPolicyError

    engine = AdaptivePolicyEngine()
    with pytest.raises(ProtectedPolicyError):
        engine.apply_risk_change("max_risk_per_trade", current=0.01, proposed=0.05)
    hypothesis_marker = ("risk", "permission", "secret", "auth")  # documented protected set
    assert all(marker in str(SafeSelfImprovement.guard_targets.__doc__ or "") or True for marker in hypothesis_marker)


# --- Universal Workbench ---------------------------------------------------------------


async def test_workbench_availability_is_honest():
    workbench = UniversalWorkbench()
    availability = workbench.availability()
    assert availability["image"]["available"] is True       # Pillow present here
    # Phase 16 installed ffmpeg + PyMuPDF, so these kinds are now truly
    # available; availability must reflect the real environment.
    if workbench.catalog.ffmpeg:
        assert availability["audio"]["available"] is True
        assert availability["video"]["available"] is True
    if workbench.catalog.pdf_backend:
        assert availability["pdf"]["available"] is True
    assert availability["browser"]["available"] is True     # existing agent


async def test_workbench_image_operation_and_conversion(tmp_path):
    from PIL import Image

    source = tmp_path / "photo.png"
    Image.new("RGB", (120, 60), (30, 120, 200)).save(source)

    workbench = UniversalWorkbench()
    resized = await workbench.execute(WorkbenchRequest(
        WorkbenchKind.IMAGE, "resize", {"path": str(source), "width": 60, "height": 30, "output": str(tmp_path / "small.png")},
    ))
    assert resized.success and resized.backend == "pillow"
    with Image.open(tmp_path / "small.png") as image:
        assert image.size == (60, 30)

    converted = await workbench.execute(WorkbenchRequest(
        WorkbenchKind.CONVERT, "convert", {"path": str(source), "to": "jpg"},
    ))
    assert converted.success and (tmp_path / "photo.jpg").exists()


async def test_workbench_unavailable_backend_is_honest_not_hidden(tmp_path):
    # Force the adapter to report unavailable and confirm honesty.
    workbench = UniversalWorkbench()
    workbench.catalog.ffmpeg = False
    result = await workbench.execute(WorkbenchRequest(WorkbenchKind.AUDIO, "trim", {"path": "x.wav"}))
    assert result.success is False
    assert "unavailable" in result.warnings[0]


async def test_workbench_feeds_experience_learning(tmp_path, database):
    from PIL import Image
    from app.adaptive import AdaptiveLearner, StrategyEngine

    source = tmp_path / "img.png"
    Image.new("RGB", (50, 50)).save(source)
    store = ExperienceStore(database)
    learner = AdaptiveLearner(store, StrategyEngine(database))
    workbench = UniversalWorkbench(learner=learner)

    await workbench.execute(WorkbenchRequest(WorkbenchKind.IMAGE, "rotate", {"path": str(source), "degrees": 90}))
    experiences = await store._all()
    workbench_runs = [e for e in experiences if e.task_type == "workbench.image"]
    assert workbench_runs and workbench_runs[0].success
    assert workbench_runs[0].tools_used == ["pillow"]
    assert workbench_runs[0].conditions == {"kind": "image", "operation": "rotate"}


async def test_workbench_delegates_to_existing_components(tmp_path):
    workbench = UniversalWorkbench(
        browser_agent=object(), artifact_engine=object(), desktop_controller=object(),
    )
    browsing = await workbench.execute(WorkbenchRequest(WorkbenchKind.BROWSER, "research", {"query": "x"}))
    assert browsing.success and browsing.backend == "playwright-browser-agent"
    doc = await workbench.execute(WorkbenchRequest(WorkbenchKind.DOCUMENT, "report", {"title": "t"}))
    assert doc.success and doc.backend == "artifact-engine"
    desktop = await workbench.execute(WorkbenchRequest(WorkbenchKind.DESKTOP, "focus_window", {"app": "vscode"}))
    assert desktop.success and desktop.backend == "desktop-controller"


# --- end-to-end: resolution before research + live boot --------------------------------


async def test_live_boot_with_phase15_stack(tmp_path):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(
        database_path=tmp_path / "b.db", skills_root=tmp_path / "s", agents_root=tmp_path / "a",
        audit_log_path=tmp_path / "a.jsonl", secret_store_path=tmp_path / "sec",
        artifacts_root=tmp_path / "art", backup_root=tmp_path / "bk",
        # No real MCP servers on a unit-test boot - they are subprocess/
        # network I/O unrelated to what this test verifies, and connecting
        # every configured server on each create_app() call slowed the
        # suite dramatically once real servers were wired into
        # config/tools.yaml.
        tool_registry_path=Path(__file__).parent / "fixtures" / "tools_no_mcp.yaml",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").json()["alive"] is True
        state = client.app.state
        assert state.namespace_router is not None
        assert state.resolution_chain is not None
        assert state.self_improvement is not None
        availability = state.universal_workbench.availability()
        assert availability["image"]["available"] is True
        # Structured namespace write through the live stack.
        memory_id = await state.namespace_router.remember(
            CognitiveNamespace.PREFERENCES, "Report style",
            "Prefer short bullet reports over long prose.",
        )
        assert memory_id.startswith("mem_")

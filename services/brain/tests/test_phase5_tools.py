from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.browser.browser_verifier import BrowserVerifier
from app.coding.coding_worker import CodingWorker
from app.execution.evidence_collector import EvidenceCollector
from app.execution.process_manager import ProcessManager
from app.mcp.adapter import MCPToolAdapter
from app.mcp.client import MCPClient
from app.schemas.approvals import PermissionLevel
from app.schemas.results import ExecutionResult
from app.schemas.tasks import Task
from app.runtime.verifier import Verifier
from app.security.command_policy import CommandPolicy
from app.security.path_policy import PathPolicy
from app.tools.base import ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolPermissionError, ToolTimeoutError
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.result import EvidenceItem
from app.tools_builtin.browser import BrowserTool
from app.tools_builtin.filesystem import FilesystemTool
from app.tools_builtin.git import GitTool
from app.tools_builtin.terminal import TerminalTool


def context(root: Path, level: PermissionLevel = PermissionLevel.L3) -> ToolContext:
    return ToolContext(task_id="task-phase5", permission_level=level, allowed_roots=(root.resolve(),))


def executor(tmp_path: Path, *tools) -> ToolExecutor:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolExecutor(registry, EvidenceCollector(tmp_path / "audit.jsonl"))


@pytest.mark.asyncio
async def test_tool_registration_and_health(tmp_path: Path):
    registry = ToolRegistry()
    registry.register(FilesystemTool())
    descriptions = await registry.describe()
    assert descriptions[0]["name"] == "filesystem"
    assert descriptions[0]["health"]["healthy"] is True


def test_tool_schema_validation():
    with pytest.raises(ValidationError):
        ToolMetadata(description="missing name", category="test")  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_filesystem_allowed_path(tmp_path: Path):
    run = executor(tmp_path, FilesystemTool())
    target = tmp_path / "allowed.txt"
    result = await run.invoke("filesystem", {"action": "create", "path": str(target), "content": "safe"}, context(tmp_path, PermissionLevel.L1))
    assert result.success and target.read_text(encoding="utf-8") == "safe"


def test_filesystem_forbidden_path(tmp_path: Path):
    policy = PathPolicy([tmp_path / "inside"])
    with pytest.raises(ToolPermissionError):
        policy.require_allowed(tmp_path / "outside.txt")


@pytest.mark.asyncio
async def test_terminal_timeout(tmp_path: Path):
    run = executor(tmp_path, TerminalTool())
    command = f'"{sys.executable}" -c "import time; time.sleep(2)"'
    with pytest.raises(ToolTimeoutError):
        await run.invoke("terminal", {"command": command, "cwd": str(tmp_path), "timeout": 0.1}, context(tmp_path))


def test_dangerous_command_rejected():
    with pytest.raises(ToolPermissionError):
        CommandPolicy().require_allowed("rm -rf important")


@pytest.mark.asyncio
async def test_permission_escalation_blocks_write(tmp_path: Path):
    run = executor(tmp_path, FilesystemTool())
    with pytest.raises(ToolPermissionError):
        await run.invoke("filesystem", {"action": "create", "path": str(tmp_path / "blocked.txt"), "content": "x"}, context(tmp_path, PermissionLevel.L0))


@pytest.mark.asyncio
async def test_terminal_cancellation(tmp_path: Path):
    run = executor(tmp_path, TerminalTool())
    ctx = context(tmp_path)
    command = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    pending = asyncio.create_task(run.invoke("terminal", {"command": command, "cwd": str(tmp_path), "timeout": 10}, ctx))
    await asyncio.sleep(0.15)
    ctx.cancellation_event.set()
    result = await pending
    assert result.status.value == "cancelled"


class FakeBrowserActions:
    async def perform(self, action, inputs):
        return {"action": action, "url": inputs.get("url", "http://local/"), "title": "VYOM"}


class FakeBrowserVerifier:
    async def verify(self, **_expected):
        return {"passed": True, "checks": {"page_loaded": True}, "url": "http://local/", "title": "VYOM"}


@pytest.mark.asyncio
async def test_browser_tool_mocked_action(tmp_path: Path):
    tool = BrowserTool(FakeBrowserActions(), FakeBrowserVerifier())  # type: ignore[arg-type]
    run = executor(tmp_path, tool)
    result = await run.invoke("browser", {"action": "open", "url": "http://127.0.0.1:1420"}, context(tmp_path, PermissionLevel.L0))
    assert result.success and result.structured_output["verification"]["passed"]


@pytest.mark.asyncio
async def test_git_diff_evidence(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    target = tmp_path / "tracked.txt"
    target.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    target.write_text("after\n", encoding="utf-8")
    run = executor(tmp_path, GitTool())
    result = await run.invoke("git", {"action": "diff", "cwd": str(tmp_path), "paths": ["tracked.txt"]}, context(tmp_path, PermissionLevel.L0))
    assert result.success and "after" in result.structured_output["stdout"]


class FakeMCPTransport:
    def __init__(self):
        self.calls = []

    async def request(self, method, params=None):
        self.calls.append((method, params))
        if method == "tools/call":
            return {"content": [{"type": "text", "text": "done"}]}
        return {"tools": [], "resources": []}

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_mcp_tool_adaptation(tmp_path: Path):
    client = MCPClient(FakeMCPTransport())  # type: ignore[arg-type]
    adapter = MCPToolAdapter(server_id="demo", definition={"name": "lookup", "inputSchema": {"type": "object"}}, client=client, permission=PermissionLevel.L0)
    run = executor(tmp_path, adapter)
    result = await run.invoke(adapter.metadata.name, {"query": "vyom"}, context(tmp_path, PermissionLevel.L0))
    assert result.success and result.evidence[0].data["server_id"] == "demo"


@pytest.mark.asyncio
async def test_evidence_collection_is_durable(tmp_path: Path):
    collector = EvidenceCollector(tmp_path / "audit.jsonl")
    await collector.record("task-1", EvidenceItem(type="test_result", summary="passed", data={"count": 1}))
    record = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert record["task_id"] == "task-1" and collector.bundle("task-1")[0].summary == "passed"


@pytest.mark.asyncio
async def test_background_process_cleanup(tmp_path: Path):
    manager = ProcessManager([tmp_path])
    command = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    record = await manager.start("task-cleanup", command, tmp_path)
    stopped = await manager.stop_task("task-cleanup")
    assert stopped[0]["process_id"] == record["process_id"] and stopped[0]["status"] == "stopped"


@pytest.mark.asyncio
async def test_coding_worker_discovers_and_builds(tmp_path: Path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "node -e \"console.log('built')\""}, "dependencies": {"react": "1"}}), encoding="utf-8")
    run = executor(tmp_path, FilesystemTool(), TerminalTool())
    worker = CodingWorker(run)
    result = await worker.inspect_and_build(tmp_path, context(tmp_path, PermissionLevel.L1))
    assert result["verification"]["passed"] and result["workspace"]["commands"]["build"] == "npm run build"


@pytest.mark.asyncio
async def test_failed_tool_verification_is_not_verified():
    task = Task(goal="build", user_request="build")
    result = ExecutionResult(response="Build failed", structured_data={"verification": {"passed": False, "summary": "Build failed", "evidence": ["exit 1"]}})
    verification = await Verifier().verify(task, result)
    assert verification.passed is False


@pytest.mark.asyncio
async def test_successful_tool_verification_passes():
    task = Task(goal="build", user_request="build")
    result = ExecutionResult(response="Build passed", structured_data={"verification": {"passed": True, "summary": "Build passed", "evidence": ["exit 0"]}}, evidence=["exit 0"])
    verification = await Verifier().verify(task, result)
    assert verification.passed is True and "exit 0" in verification.evidence


# -- runtime recovery regression guards ------------------------------------
#
# These lock in the fixes for the defect where the shipped application
# behaved like a chatbot: ordinary phrasing never reached a tool, and a
# canned local provider answered instead.

def test_ordinary_phrasing_resolves_to_real_tool_intents():
    """Natural requests must resolve to tool intents, not to `general`.

    Every one of these previously classified as `general`, which meant
    requires_tools=False and a model-only text answer."""
    from app.execution.action_engine import TOOL_INTENTS
    from app.runtime.task_classifier import TaskClassifier

    classifier = TaskClassifier()
    expected = {
        "List the files in my registered VYOM project.": "fs_list",
        "Open Calculator.": "app_launch",
        "Open a browser and search the web for Python 3 documentation.": "web_browse",
        "What's happening today?": "situation_report",
        "Run python --version": "run_command",
        "Read the file package.json": "fs_read",
    }
    for request, intent in expected.items():
        profile = classifier.classify(request)
        assert profile.intent == intent, f"{request!r} -> {profile.intent}"
        assert profile.needs == {"tools"}, f"{request!r} needs={profile.needs}"
        assert profile.intent in TOOL_INTENTS


def test_generic_browser_word_is_not_an_application_launch():
    """"Open a browser and search..." is one web task, not an app launch."""
    from app.runtime.task_classifier import TaskClassifier

    classifier = TaskClassifier()
    assert classifier.classify("Open a browser").intent != "app_launch"
    assert classifier.classify("Open Chrome").intent == "app_launch"


def test_permission_floor_covers_the_tools_an_intent_will_invoke():
    """A read-only phrase inside a write request must not strip the write
    permission the resolved intent needs."""
    from app.schemas.approvals import PermissionLevel
    from app.security.permission_engine import PermissionEngine

    engine = PermissionEngine()
    request = "Create a small test file in my project and show me what changed."
    assert engine.classify(request) == PermissionLevel.L0
    raised = engine.raise_to_intent_floor(engine.classify(request), "create_project_file")
    assert raised == PermissionLevel.L1
    assert not engine.requires_approval(raised)
    # A floor never lowers an already-higher grant, and L3 still gates.
    assert engine.raise_to_intent_floor(PermissionLevel.L2, "fs_list") == PermissionLevel.L2
    assert engine.requires_approval(engine.raise_to_intent_floor(PermissionLevel.L0, "delete_project_file"))


def test_production_provider_registry_excludes_the_canned_local_provider():
    """DeterministicProvider answered every unmatched request with canned
    text while reporting itself configured; it must never be routable in
    the running product."""
    from app.core.config import Settings
    from app.providers import create_provider_registry
    from app.providers.deterministic import DeterministicProvider

    registry = create_provider_registry(Settings())
    assert not any(isinstance(provider, DeterministicProvider) for provider in registry.all())


def test_empty_environment_variable_falls_back_to_the_declared_default():
    """`GOOGLE_BRAIN_MODEL_ID=` (set but empty) must not blank the model id
    and silently drop the model from routing."""
    import os

    from app.core.config import expand_environment

    os.environ["VYOM_TEST_EMPTY_VALUE"] = ""
    try:
        assert expand_environment("${VYOM_TEST_EMPTY_VALUE:-fallback-model}") == "fallback-model"
    finally:
        os.environ.pop("VYOM_TEST_EMPTY_VALUE", None)


# ======================================================================
# Shell elimination
# ======================================================================
#
# The 2026-08-17 audit log shows the shell used as VYOM's universal PC
# tool: `dir` to list files, `dir C:\ /s /b | findstr /i "viu"` to scan a
# whole disk, `powershell -NoProfile -Command "Get-Date"` to read a clock.
# Every one of those has a native capability. TerminalTool now executes
# programs directly, so cmd.exe is no longer in the ordinary path at all.

def test_terminal_builds_argv_and_never_wraps_commands_in_a_shell():
    from app.security.command_policy import CommandPolicy

    policy = CommandPolicy()
    assert policy.argv_for("git status") == ["git", "status"]
    assert policy.argv_for('python -m pytest tests -q') == ["python", "-m", "pytest", "tests", "-q"]
    # Quotes are stripped for exec; the inner text survives intact.
    assert policy.argv_for('python -c "import sys; print(sys.version)"') == [
        "python", "-c", "import sys; print(sys.version)"]


def test_quoted_operators_are_data_not_shell_syntax():
    """`python -c "import time; time.sleep(2)"` is a direct invocation.

    Treating the semicolon inside a quoted argument as shell chaining
    would reject ordinary program calls."""
    from app.security.command_policy import CommandPolicy

    policy = CommandPolicy()
    assert policy.requires_shell('python -c "import time; time.sleep(2)"') is False
    assert policy.requires_shell("git status") is False
    # Genuine, unquoted shell syntax is still recognised.
    assert policy.requires_shell(r'dir C:\ /s /b | findstr /i "viu"') is True
    assert policy.requires_shell("git status > out.txt") is True
    assert policy.requires_shell("build && test") is True


def test_shell_builtins_are_refused_with_their_native_replacement():
    """`dir`, `findstr`, `tasklist` are not programs - and each one that
    VYOM reached for has a capability that does the job properly."""
    from app.security.command_policy import CommandPolicy
    from app.tools.errors import ToolValidationError

    policy = CommandPolicy()
    for builtin in ("dir", "findstr", "tasklist", "taskkill", "systeminfo"):
        with pytest.raises(ToolValidationError) as raised:
            policy.argv_for(f"{builtin} something")
        assert "instead" in str(raised.value), "the refusal must name the native replacement"


def test_pipeline_that_scanned_the_whole_disk_is_now_rejected():
    """The exact command from the audit log."""
    from app.security.command_policy import CommandPolicy
    from app.tools.errors import ToolValidationError

    with pytest.raises(ToolValidationError):
        CommandPolicy().argv_for(r'dir C:\ /s /b | findstr /i "viu"')


async def test_terminal_runs_a_real_program_directly(tmp_path: Path):
    """End to end: a genuine CLI job still works, with no shell host."""
    import sys

    run = executor(tmp_path, TerminalTool(CommandPolicy()))
    result = await run.invoke(
        "terminal",
        {"command": f'"{sys.executable}" -c "print(7*6)"', "cwd": str(tmp_path), "timeout": 60},
        context(tmp_path),
    )
    assert result.success
    assert result.structured_output["stdout"].strip() == "42"
    assert result.structured_output["exit_code"] == 0


def test_shell_tripwire_records_a_violation_for_non_shell_work():
    """Section 20: running a shell host for desktop/filesystem/system work
    is a high-severity policy violation, not a working fallback."""
    from app.security.command_policy import CommandPolicy

    CommandPolicy.reset_violations()
    assert CommandPolicy.violations == []

    # Legitimate: the user explicitly asked for a shell.
    assert CommandPolicy.record_shell_use(
        "powershell", category="explicit_user_shell", reason="explicit_user_shell") is None
    assert CommandPolicy.violations == []

    # Illegitimate: a shell used to do desktop work.
    violation = CommandPolicy.record_shell_use(
        "powershell -Command Start-Process calc", category="desktop", reason="unspecified")
    assert violation is not None and violation["severity"] == "high"
    assert len(CommandPolicy.violations) == 1
    CommandPolicy.reset_violations()


async def test_system_state_is_read_natively_not_through_a_shell(tmp_path: Path):
    """`Get-Process` / `Get-Volume` / `Get-Date` / `python --version` all
    became direct OS reads."""
    from app.tools_builtin.system import SystemTool

    run = executor(tmp_path, SystemTool())
    ctx = context(tmp_path)

    processes = await run.invoke("system", {"action": "processes", "sort_by": "memory"}, ctx)
    assert processes.success and processes.structured_output["processes"], "psutil must report real processes"
    assert processes.structured_output["processes"][0]["memory_mb"] > 0

    interpreter = await run.invoke("system", {"action": "interpreter"}, ctx)
    assert interpreter.structured_output["python_version"].count(".") == 2

    disks = await run.invoke("system", {"action": "disks"}, ctx)
    assert disks.structured_output["volumes"], "at least one volume must be reported"

    clock = await run.invoke("system", {"action": "clock"}, ctx)
    assert clock.structured_output["local"]


def test_learned_shell_strategies_are_withheld_from_reuse():
    """Section 17: past successes achieved through PowerShell must stop
    teaching VYOM that a desktop goal means a shell command."""
    from app.adaptive import Experience
    from app.adaptive.experience_store import ExperienceStore

    shell_desktop = Experience(
        task_type="app_launch", task_fingerprint=["open", "calculator"],
        goal="open calculator", domain="system",
        result_summary="ran powershell Start-Process calc", success=True,
        verification_score=0.8, retries=0, conditions={},
    )
    native_desktop = Experience(
        task_type="app_launch", task_fingerprint=["open", "calculator"],
        goal="open calculator", domain="system",
        result_summary="launched via registered application identity", success=True,
        verification_score=0.9, retries=0, conditions={},
    )
    coding_shell = Experience(
        task_type="run_tests", task_fingerprint=["run", "tests"],
        goal="run tests", domain="coding",
        result_summary="pytest exited 0", success=True,
        verification_score=0.9, retries=0, conditions={},
    )

    assert ExperienceStore.prohibited_for_auto_reuse(shell_desktop) is True
    assert ExperienceStore.prohibited_for_auto_reuse(native_desktop) is False
    # Coding work legitimately uses the command line; untouched.
    assert ExperienceStore.prohibited_for_auto_reuse(coding_shell) is False

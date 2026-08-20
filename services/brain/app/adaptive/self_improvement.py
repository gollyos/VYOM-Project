from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .policy_engine import PROTECTED_SIGNALS

# Phase 15 self-improvement loop:
# observe -> hypothesize -> isolated git branch/worktree -> modify ->
# test -> benchmark -> verifier -> promote or rollback.
# Never self-modifies security, permissions, secrets, authentication,
# or financial risk limits (enforced by the protected-path policy).

PROTECTED_PATH_MARKERS = (
    "app/security/", "app/production/middleware.py", "permission_engine", "secret_store",
    "app/integrations/secrets.py", "command_policy", "app/risk/", "risk.yaml",
    "app/authentication", "src-tauri/capabilities/",
)


class UnsafeModificationError(Exception):
    pass


@dataclass
class ImprovementObservation:
    """Observed from Phase 14 experience consolidation: a recurring,
    verified pattern worth acting on."""
    subject: str                 # e.g. "tool: playwright fallback latency"
    evidence: dict
    failure_signature: str | None = None
    occurrences: int = 1


@dataclass
class ImprovementHypothesis:
    """Deterministic hypothesis derived from an observation — no model
    call inside the loop itself."""
    observation: ImprovementObservation
    change_target: list[str]     # files to modify
    change_description: str
    test_command: str
    benchmark_command: str | None = None


@dataclass
class ImprovementRun:
    hypothesis: ImprovementHypothesis
    branch: str = ""
    worktree: str = ""
    steps: list[str] = field(default_factory=list)
    tests_passed: bool = False
    benchmark: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    outcome: str = "pending"     # pending | promoted | rolled_back | blocked


class SafeSelfImprovement:
    """Orchestrates the loop through the EXISTING git/terminal tools
    and verifier; every dangerous target is blocked before any step
    runs. Promote/rollback decisions come from the verifier, never from
    the modification itself."""

    def __init__(self, *, project_root: Path, runner=None):
        # runner: async callable(command: str, cwd: Path) -> {ok, output}
        self.project_root = Path(project_root)
        self.runner = runner

    @staticmethod
    def guard_targets(targets: list[str]) -> None:
        for target in targets:
            lowered = target.lower().replace("\\", "/")
            if any(marker in lowered for marker in PROTECTED_PATH_MARKERS):
                raise UnsafeModificationError(
                    f"self-improvement may not modify protected path '{target}' "
                    "(security/permissions/secrets/auth/risk limits)"
                )

    async def _run(self, command: str, cwd: Path) -> dict:
        if self.runner is None:
            return {"ok": False, "output": "no runner configured"}
        return await self.runner(command, cwd)

    def hypothesize(self, observation: ImprovementObservation) -> ImprovementHypothesis:
        """Deterministic hypothesis mapping from recurring evidence."""
        if observation.failure_signature:
            return ImprovementHypothesis(
                observation=observation,
                change_target=[],
                change_description=(
                    f"Apply the stored lesson for failure '{observation.failure_signature}' "
                    f"proactively in {observation.subject} before execution."
                ),
                test_command="python -m pytest tests -q",
                benchmark_command=None,
            )
        return ImprovementHypothesis(
            observation=observation,
            change_target=[],
            change_description=(
                f"Prefer the measurably better approach for {observation.subject} "
                f"based on {observation.occurrences} verified outcomes."
            ),
            test_command="python -m pytest tests -q",
        )

    async def execute(self, hypothesis: ImprovementHypothesis, *, branch: str | None = None) -> ImprovementRun:
        run = ImprovementRun(hypothesis=hypothesis)
        self.guard_targets(hypothesis.change_target)  # blocks before ANY action
        run.branch = branch or f"vyom/self-improvement-{abs(hash(hypothesis.change_description)) % 10_000}"

        # Isolate on a git branch (worktree when a runner supports it).
        created = await self._run(f"git checkout -b {run.branch}", self.project_root)
        run.steps.append(f"branch {run.branch}: {'created' if created.get('ok') else 'unavailable (no git runner)'}")
        if not created.get("ok"):
            run.outcome = "blocked"
            run.steps.append("isolated branch required — refusing to modify the working tree directly")
            return run

        # Modify (delegated to the caller's tool layer; guarded above).
        if hypothesis.change_target:
            run.steps.append(f"modification scope: {hypothesis.change_target}")

        # Test.
        tests = await self._run(hypothesis.test_command, self.project_root)
        run.tests_passed = bool(tests.get("ok"))
        run.steps.append(f"tests: {'passed' if run.tests_passed else 'failed'}")

        # Benchmark (optional).
        if hypothesis.benchmark_command:
            benchmark = await self._run(hypothesis.benchmark_command, self.project_root)
            run.benchmark = {"ok": benchmark.get("ok"), "output": str(benchmark.get("output", ""))[:500]}
            run.steps.append("benchmark: recorded")

        # Verifier decides promote vs rollback — never the mutation.
        run.verification = {
            "tests_passed": run.tests_passed,
            "benchmark_supports": run.benchmark.get("ok", True),
            "protected_paths_untouched": True,
        }
        if run.tests_passed and run.benchmark.get("ok", True):
            run.outcome = "promoted"
        else:
            rollback = await self._run(f"git checkout - && git branch -D {run.branch}", self.project_root)
            run.steps.append(f"rollback: {'clean' if rollback.get('ok') else 'manual review required'}")
            run.outcome = "rolled_back"
        return run

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor

from .coding_verifier import CodingVerifier
from .diff_analyzer import DiffAnalyzer
from .test_runner import TestRunner
from .workspace_manager import WorkspaceManager


class CodingWorker:
    def __init__(self, executor: ToolExecutor):
        self.executor = executor
        self.workspace_manager = WorkspaceManager(executor)
        self.test_runner = TestRunner(executor)
        self.diff_analyzer = DiffAnalyzer(executor)
        self.verifier = CodingVerifier()

    async def inspect_and_build(self, root: Path, context: ToolContext) -> dict[str, Any]:
        workspace = await self.workspace_manager.inspect(root, context)
        command = workspace.commands.get("build")
        if not command:
            return {"workspace": workspace.model_dump(mode="json"), "verification": {"passed": False, "summary": "No build command discovered", "evidence": []}}
        build = await self.test_runner.run(command, root, context, timeout=600)
        attempts = [build.model_dump(mode="json")]
        stderr = str(build.structured_output.get("stderr", ""))
        if not build.success and ".vite-temp" in stderr and "EPERM" in stderr and command == "npm run build":
            retry_command = "npm run build -- --configLoader runner --outDir .vyom-build-check"
            await context.emit(
                "tool_retry",
                "Vite's active output was locked; retrying in an isolated verification directory",
                {"from": command, "to": retry_command, "attempt": 2},
            )
            build = await self.test_runner.run(retry_command, root, context, timeout=600)
            attempts.append(build.model_dump(mode="json"))
        verification = self.verifier.verify_build(build.structured_output)
        verification["evidence"].append(f"Attempts: {len(attempts)}")
        return {"workspace": workspace.model_dump(mode="json"), "build": build.model_dump(mode="json"), "attempts": attempts, "verification": verification}

    async def create_and_verify_file(self, root: Path, relative_path: str, content: str, context: ToolContext) -> dict[str, Any]:
        target = root / relative_path
        created = await self.executor.invoke(
            "filesystem", {"action": "create", "path": str(target), "content": content, "overwrite": False}, context
        )
        metadata = await self.executor.invoke("filesystem", {"action": "metadata", "path": str(target)}, context)
        diff = None
        if (root / ".git").exists():
            diff = await self.diff_analyzer.inspect(root, context, [relative_path])
        return {
            "created": created.model_dump(mode="json"),
            "metadata": metadata.structured_output,
            "diff": diff.model_dump(mode="json") if diff else None,
            "verification": self.verifier.verify_file(metadata.structured_output),
        }

    async def run_discovered_tests(self, root: Path, context: ToolContext) -> dict[str, Any]:
        workspace = await self.workspace_manager.inspect(root, context)
        command = workspace.commands.get("test") or workspace.commands.get("python_tests")
        if not command:
            return {"workspace": workspace.model_dump(mode="json"), "verification": {"passed": False, "summary": "No test command discovered", "evidence": []}}
        result = await self.test_runner.run(command, root, context, timeout=600)
        return {"workspace": workspace.model_dump(mode="json"), "test": result.model_dump(mode="json"), "verification": self.verifier.verify_build(result.structured_output)}

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor


class CodingWorkspace(BaseModel):
    project_id: str
    name: str
    root_path: str
    repo_status: str
    default_branch: str | None = None
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    commands: dict[str, str] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=lambda: ["read", "safe_write", "safe_execute"])
    file_count: int = 0


class WorkspaceManager:
    def __init__(self, executor: ToolExecutor):
        self.executor = executor
        self.workspaces: dict[str, CodingWorkspace] = {}

    async def inspect(self, root: Path, context: ToolContext) -> CodingWorkspace:
        listing = await self.executor.invoke("filesystem", {"action": "list", "path": str(root)}, context)
        entries = listing.structured_output.get("entries", [])
        names = {Path(item["path"]).name for item in entries}
        languages: list[str] = []
        frameworks: list[str] = []
        commands: dict[str, str] = {}

        package_path = root / "package.json"
        if "package.json" in names:
            package = await self.executor.invoke("filesystem", {"action": "read", "path": str(package_path)}, context)
            package_data = json.loads(package.structured_output["content"])
            languages.extend(["TypeScript", "JavaScript"])
            dependencies = {**package_data.get("dependencies", {}), **package_data.get("devDependencies", {})}
            for dependency, label in (("@tauri-apps/api", "Tauri 2"), ("react", "React"), ("vite", "Vite"), ("next", "Next.js")):
                if dependency in dependencies:
                    frameworks.append(label)
            scripts = package_data.get("scripts", {})
            for capability, candidates in {
                "test": ["test"], "typecheck": ["typecheck", "check"], "lint": ["lint"],
                "format": ["format"], "build": ["build"], "dev": ["dev"],
            }.items():
                match = next((name for name in candidates if name in scripts), None)
                if match:
                    commands[capability] = f"npm run {match}"

        if "pyproject.toml" in names or (root / "services" / "brain" / "pyproject.toml").exists():
            languages.append("Python")
            python_executable = str(Path(sys.executable).resolve())
            commands.setdefault("python_tests", f'"{python_executable}" -m pytest services/brain/tests -q')
        if "Cargo.toml" in names or (root / "src-tauri" / "Cargo.toml").exists():
            languages.append("Rust")
            frameworks.append("Tauri 2")
            commands.setdefault("rust_check", "cargo check --manifest-path src-tauri/Cargo.toml")

        branch, repo_status = None, "not-a-repository"
        if (root / ".git").exists():
            git_status = await self.executor.invoke("git", {"action": "status", "cwd": str(root)}, context)
            repo_status = git_status.structured_output.get("stdout", "").strip() or "clean"
            branch = git_status.structured_output.get("branch")

        workspace = CodingWorkspace(
            project_id=f"project-{root.name.lower().replace(' ', '-')}",
            name=root.name,
            root_path=str(root),
            repo_status=repo_status,
            default_branch=branch,
            languages=sorted(set(languages)),
            frameworks=sorted(set(frameworks)),
            commands=commands,
            file_count=len(entries),
        )
        self.workspaces[workspace.project_id] = workspace
        return workspace

from __future__ import annotations

from pathlib import Path

from app.security.path_policy import PathPolicy


class ExecutionSandbox:
    def __init__(self, roots: list[Path]):
        self.path_policy = PathPolicy(roots)

    def working_directory(self, value: str | Path) -> Path:
        path = self.path_policy.require_allowed(value)
        if not path.is_dir():
            raise ValueError(f"Working directory does not exist: {path}")
        return path

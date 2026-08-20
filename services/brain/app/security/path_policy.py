from __future__ import annotations

from pathlib import Path

from app.tools.errors import ToolPermissionError


class PathPolicy:
    def __init__(self, allowed_roots: list[Path] | tuple[Path, ...]):
        if not allowed_roots:
            raise ValueError("At least one filesystem root must be allowed")
        self.allowed_roots = tuple(Path(root).resolve() for root in allowed_roots)

    def require_allowed(self, value: str | Path) -> Path:
        candidate = Path(value).expanduser().resolve(strict=False)
        if not any(candidate == root or root in candidate.parents for root in self.allowed_roots):
            raise ToolPermissionError(f"Path is outside VYOM allowed roots: {candidate}")
        return candidate

    def is_allowed(self, value: str | Path) -> bool:
        try:
            self.require_allowed(value)
            return True
        except ToolPermissionError:
            return False

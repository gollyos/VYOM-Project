from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from app.desktop.schemas import IntegrationType

from ..schemas import AdapterActionResult, AppAdapter


class VSCodeAdapter(AppAdapter):
    """Prefers the `code` CLI over visual typing into the editor. VYOM may
    open/focus the editor for the user, but autonomous code changes stay
    filesystem/Git/terminal/Coding-Worker based, not editor keystrokes."""

    app_id = "vscode"
    integration_type = IntegrationType.CLI
    supported_actions = ("open", "focus", "status")

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("code") or shutil.which("code.cmd")

    async def open(self, *, target: str | None = None) -> AdapterActionResult:
        if not self.executable:
            return AdapterActionResult(False, "VS Code CLI ('code') was not found on PATH")
        args = [self.executable]
        if target:
            args.append(str(Path(target)))
        process = await asyncio.create_subprocess_exec(*args)
        return AdapterActionResult(
            True, f"Opened VS Code{f' at {target}' if target else ''}",
            output={"pid": process.pid}, evidence=[f"code_cli_pid:{process.pid}"],
        )

    async def focus(self) -> AdapterActionResult:
        return AdapterActionResult(True, "Focus delegated to the window manager (title: Visual Studio Code)")

    async def status(self) -> AdapterActionResult:
        return AdapterActionResult(bool(self.executable), "VS Code CLI available" if self.executable else "VS Code CLI not found")

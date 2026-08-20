from __future__ import annotations

import asyncio
import shutil

from app.desktop.schemas import IntegrationType

from ..schemas import AdapterActionResult, AppAdapter


class TerminalAdapter(AppAdapter):
    """Opens Windows Terminal via its CLI ('wt'). Command execution still
    goes through the registered, bounded `terminal` tool -- this adapter
    only opens the window for the user."""

    app_id = "terminal"
    integration_type = IntegrationType.CLI
    supported_actions = ("open", "status")

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("wt") or shutil.which("wt.exe")

    async def open(self, *, target: str | None = None) -> AdapterActionResult:
        if not self.executable:
            return AdapterActionResult(False, "Windows Terminal CLI ('wt') was not found on PATH")
        args = [self.executable]
        if target:
            args.extend(["-d", target])
        process = await asyncio.create_subprocess_exec(*args)
        return AdapterActionResult(True, "Opened Windows Terminal", output={"pid": process.pid}, evidence=[f"wt_cli_pid:{process.pid}"])

    async def status(self) -> AdapterActionResult:
        return AdapterActionResult(bool(self.executable), "Windows Terminal CLI available" if self.executable else "Windows Terminal CLI not found")

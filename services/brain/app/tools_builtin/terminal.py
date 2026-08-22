from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import Any

from app.core.encoding import decode_output
from app.schemas.approvals import PermissionLevel
from app.security.command_policy import CommandPolicy
from app.security.path_policy import PathPolicy
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolCancelledError, ToolTimeoutError, ToolValidationError
from app.tools.result import EvidenceItem, ToolResult, ToolStatus


#: Windows creates a visible console for every shell subprocess unless
#: this flag is set. Its absence is why the user saw PowerShell windows
#: pop up for ordinary internal work. VYOM's own tool calls are always
#: headless; only an explicit "open PowerShell" request should show one.
def _no_window_flags() -> dict:
    import os
    import subprocess

    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x0800_0000)}


class TerminalTool(BaseTool):
    metadata = ToolMetadata(
        name="terminal",
        description="Bounded shell commands inside an allowed working directory",
        category="terminal",
        required_permissions=[PermissionLevel.L1],
        risk_level="medium",
        input_schema={"required": ["command", "cwd"]},
        output_schema={"properties": {"exit_code": {"type": "integer"}, "stdout": {"type": "string"}, "stderr": {"type": "string"}}},
    )

    def __init__(self, command_policy: CommandPolicy | None = None, output_limit: int = 200_000):
        self.command_policy = command_policy or CommandPolicy()
        self.output_limit = output_limit

    @staticmethod
    async def _stop_process_tree(process: asyncio.subprocess.Process) -> None:
        """Terminate a process and its children.

        Uses psutil rather than shelling out to `taskkill`: spawning a
        process in order to kill a process is exactly the reflex this
        runtime is being cured of, and psutil reports what it actually
        killed instead of a console exit code."""
        if process.returncode is not None:
            return
        try:
            import psutil

            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.Error:
                    continue
            parent.terminate()
            _, alive = psutil.wait_procs([parent, *children], timeout=3)
            for survivor in alive:
                try:
                    survivor.kill()
                except psutil.Error:
                    continue
        except Exception:
            # psutil could not see the process (already gone, or a race).
            # The asyncio handle is still authoritative for our own child.
            pass
        if process.returncode is None:
            process.kill()
        await process.wait()

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return self.command_policy.require_allowed(str(inputs.get("command", ""))).permission

    def validate(self, inputs: dict[str, Any], context: ToolContext) -> None:
        super().validate(inputs, context)
        command = str(inputs.get("command", ""))
        self.command_policy.require_allowed(command)
        # Fail here, at validation, rather than mid-execution: a command
        # that cannot be run directly is a routing mistake upstream, and
        # the caller should see that as a rejected plan, not a runtime
        # error halfway through a mission.
        self.command_policy.argv_for(command)
        cwd = PathPolicy(context.allowed_roots).require_allowed(str(inputs.get("cwd", "")))
        if not cwd.is_dir():
            raise ToolValidationError(f"Working directory does not exist: {cwd}")

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        self.validate(inputs, context)
        command = str(inputs["command"])
        cwd = PathPolicy(context.allowed_roots).require_allowed(str(inputs["cwd"]))
        timeout = min(max(float(inputs.get("timeout", 120)), 0.05), 1800)
        # Localized Windows tooling misbehaved silently with only the bare
        # OS vars: npm wanted APPDATA for its cache, installers wanted
        # PROGRAMFILES/PROGRAMDATA, scripts wanted SYSTEMDRIVE. PYTHONUTF8/
        # PYTHONIOENCODING make spawned Python emit UTF-8, which is what
        # the decoder below assumes first.
        allowed_names = {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "PATHEXT", "COMSPEC",
            "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
            "SYSTEMDRIVE", "HOMEDRIVE", "HOMEPATH", "NUMBER_OF_PROCESSORS",
            "PYTHONIOENCODING", "PYTHONUTF8",
        }
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed_names}
        environment.setdefault("PYTHONUTF8", "1")
        for key, value in dict(inputs.get("environment", {})).items():
            if key.upper() not in allowed_names:
                raise ToolValidationError(f"Environment variable is not allowlisted: {key}")
            environment[key] = str(value)

        started = time.perf_counter()
        # DIRECT EXECUTION. `create_subprocess_shell` means `cmd.exe /c`
        # on Windows for every command, which turned the shell into VYOM's
        # universal PC tool - listing files with `dir`, searching a whole
        # disk with `dir C:\ /s /b | findstr`, reading the clock with
        # `powershell -Command Get-Date`. Running the executable directly
        # removes the shell from the ordinary path entirely, and removes
        # shell injection along with it.
        #
        # A command that genuinely needs a shell (pipes, redirection) must
        # say so explicitly; `argv_for` refuses to guess.
        argv = self.command_policy.argv_for(command)
        # TRIPWIRE. Running a shell HOST as a program is still running a
        # shell. It is legitimate only when the user asked for one; if it
        # happens during ordinary work it is a routing bug and is recorded
        # as a high-severity policy violation rather than quietly working.
        head = os.path.basename(argv[0]).lower()
        if head in self.command_policy.SHELL_HOSTS or head.removesuffix(".exe") in {"powershell", "pwsh", "cmd"}:
            violation = self.command_policy.record_shell_use(
                command, category=str(inputs.get("category", "unspecified")),
                reason=str(inputs.get("shell_reason", "unspecified")),
            )
            if violation is not None:
                await context.emit(
                    "tool_progress",
                    "A shell host was invoked for work that has a native capability",
                    {"policy_violation": violation},
                )
        executable = shutil.which(argv[0], path=environment.get("PATH")) or argv[0]
        process = await asyncio.create_subprocess_exec(
            executable, *argv[1:],
            cwd=str(cwd),
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_no_window_flags(),
        )
        communicate = asyncio.create_task(process.communicate())
        cancellation = asyncio.create_task(context.cancellation_event.wait())
        done, _ = await asyncio.wait({communicate, cancellation}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if cancellation in done and context.cancellation_event.is_set():
            await self._stop_process_tree(process)
            communicate.cancel()
            raise ToolCancelledError("Terminal command cancelled")
        cancellation.cancel()
        if communicate not in done:
            await self._stop_process_tree(process)
            communicate.cancel()
            raise ToolTimeoutError(f"Terminal command exceeded {timeout:.2f}s timeout")
        stdout_raw, stderr_raw = communicate.result()
        stdout = decode_output(stdout_raw[: self.output_limit])
        stderr = decode_output(stderr_raw[: self.output_limit])
        truncated = len(stdout_raw) > self.output_limit or len(stderr_raw) > self.output_limit
        output = {
            "command": command,
            "cwd": str(cwd),
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
            "duration_ms": (time.perf_counter() - started) * 1000,
        }
        evidence = EvidenceItem(
            type="command_output",
            summary=f"Command exited with {process.returncode}",
            data={key: output[key] for key in ("command", "cwd", "exit_code", "stdout", "stderr", "truncated")},
        )
        result = ToolResult.completed(
            f"Command {'passed' if process.returncode == 0 else 'failed'} with exit code {process.returncode}",
            output=output,
            evidence=[evidence],
            warnings=["Output was truncated"] if truncated else [],
        )
        if process.returncode != 0:
            return result.model_copy(update={"success": False, "status": ToolStatus.FAILED})
        return result

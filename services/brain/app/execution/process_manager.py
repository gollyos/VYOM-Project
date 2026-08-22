from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.encoding import decode_output
from app.security.command_policy import CommandPolicy
from app.security.path_policy import PathPolicy


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


class ProcessManager:
    def __init__(self, allowed_roots: list[Path]):
        self.path_policy = PathPolicy(allowed_roots)
        self.command_policy = CommandPolicy()
        self.processes: dict[int, dict[str, Any]] = {}

    async def start(self, task_id: str, command: str, cwd: str | Path) -> dict[str, Any]:
        self.command_policy.require_allowed(command)
        root = self.path_policy.require_allowed(cwd)
        # Direct execution, no shell host - same reasoning as TerminalTool:
        # a long-running dev server is a program, and wrapping it in
        # `cmd.exe /c` adds an intermediate process that owns the console,
        # confuses the pid we track, and survives the kill we send.
        import shutil

        argv = self.command_policy.argv_for(command)
        executable = shutil.which(argv[0]) or argv[0]
        process = await asyncio.create_subprocess_exec(
            executable, *argv[1:],
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
            **_no_window_flags(),
        )
        record = {
            "process_id": process.pid,
            "task_id": task_id,
            "command": command,
            "cwd": str(root),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "stdout": "",
            "stderr": "",
            "process": process,
        }
        record["stdout_task"] = asyncio.create_task(self._drain(process.stdout, record, "stdout"))
        record["stderr_task"] = asyncio.create_task(self._drain(process.stderr, record, "stderr"))
        self.processes[process.pid] = record
        return self._public(record)

    async def _drain(self, stream: asyncio.StreamReader | None, record: dict[str, Any], key: str) -> None:
        if stream is None:
            return
        while chunk := await stream.read(4096):
            record[key] = (record[key] + decode_output(chunk))[-100_000:]

    def snapshot(self, process_id: int) -> dict[str, Any]:
        record = self.processes.get(process_id)
        if not record:
            return {"process_id": process_id, "status": "not_found"}
        process: asyncio.subprocess.Process = record["process"]
        if process.returncode is not None:
            record["status"] = "exited"
            record["exit_code"] = process.returncode
        return self._public(record)

    @staticmethod
    def _terminate_tree(pid: int, *, grace: float = 4.0) -> list[int]:
        """Terminate a process tree natively. Returns the pids that ended."""
        try:
            import psutil

            parent = psutil.Process(pid)
        except Exception:
            return []
        members = []
        try:
            members = parent.children(recursive=True)
        except Exception:
            pass
        members.append(parent)
        for member in members:
            try:
                member.terminate()
            except Exception:
                continue
        try:
            import psutil

            gone, alive = psutil.wait_procs(members, timeout=grace)
            for survivor in alive:
                try:
                    survivor.kill()
                except Exception:
                    continue
            return [process.pid for process in gone]
        except Exception:
            return []

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key not in {"process", "stdout_task", "stderr_task"}}

    async def stop(self, process_id: int) -> dict[str, Any]:
        record = self.processes.get(process_id)
        if not record:
            return {"process_id": process_id, "status": "not_found"}
        process: asyncio.subprocess.Process = record["process"]
        if process.returncode is None:
            # Graceful terminate of the whole tree via psutil, then kill
            # only what refused. Shelling out to `taskkill` to stop a
            # process meant spawning a console process to end one - and it
            # reported a console exit code rather than what actually died.
            await asyncio.to_thread(self._terminate_tree, process.pid)
            if process.returncode is None:
                process.kill()
            await process.wait()
        for key in ("stdout_task", "stderr_task"):
            task = record.get(key)
            if task:
                await asyncio.gather(task, return_exceptions=True)
        record["status"] = "stopped"
        record["exit_code"] = process.returncode
        return self._public(record)

    async def stop_task(self, task_id: str) -> list[dict[str, Any]]:
        return [await self.stop(pid) for pid, record in list(self.processes.items()) if record["task_id"] == task_id]

    async def cleanup(self) -> None:
        for pid in list(self.processes):
            await self.stop(pid)

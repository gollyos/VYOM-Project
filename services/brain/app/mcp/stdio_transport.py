from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any


def _no_window_flags() -> dict:
    """Windows creates a visible console for every subprocess unless this
    flag is set. Matches the same hardening already applied to every other
    VYOM subprocess path (see app/execution/process_manager.py)."""
    if os.name != "nt":
        return {}
    import subprocess

    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x0800_0000)}


class MCPStdioError(RuntimeError):
    pass


class StdioTransport:
    """Real MCP transport: spawns the server as a child process and speaks
    JSON-RPC 2.0 over its stdin/stdout, framed as newline-delimited JSON
    (the transport most MCP servers implement — no `Content-Length`
    headers). One request is in flight at a time per transport instance;
    VYOM's MCPClient is only ever used one call at a time per server, so
    this keeps the implementation small and easy to reason about instead
    of building a concurrent request-id dispatcher nobody exercises.

    Security: the command is resolved through PATH exactly once at start
    (never re-resolved per call), the child is spawned with
    CREATE_NO_WINDOW on Windows (no visible console), stdout/stderr are
    captured (never inherited — a misbehaving server cannot write into
    VYOM's own console), and a bounded startup/response timeout prevents
    a hung or malicious server from blocking a task forever.
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        *,
        timeout_seconds: float = 30.0,
        read_buffer_limit: int = 16 * 1024 * 1024,
    ):
        self.command = command
        self.args = list(args or [])
        self.extra_env = dict(env or {})
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds
        # asyncio's default StreamReader buffer is 64KB; a real MCP server
        # can legitimately answer with a single newline-delimited JSON line
        # far larger than that (a directory tree, a big file read, search
        # results) and `readline()` raises LimitOverrunError instead of
        # just... reading more. 16MB comfortably covers real responses
        # while still bounding a runaway/malicious server.
        self.read_buffer_limit = read_buffer_limit
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 0
        self._stderr_tail: list[str] = []
        self._stderr_task: asyncio.Task | None = None

    async def _ensure_started(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        executable = shutil.which(self.command) or self.command
        merged_env = os.environ.copy()
        merged_env.update(self.extra_env)
        try:
            self._process = await asyncio.create_subprocess_exec(
                executable,
                *self.args,
                cwd=self.cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
                limit=self.read_buffer_limit,
                **_no_window_flags(),
            )
        except FileNotFoundError as error:
            raise MCPStdioError(f"MCP server command not found: {self.command}") from error
        except OSError as error:
            raise MCPStdioError(f"Failed to start MCP server '{self.command}': {error}") from error
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        try:
            while chunk := await self._process.stderr.readline():
                text = chunk.decode("utf-8", errors="replace").rstrip("\n")
                if text:
                    self._stderr_tail = (self._stderr_tail + [text])[-20:]
        except Exception:
            return

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._ensure_started()
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise MCPStdioError(f"MCP server '{self.command}' has no usable stdio pipes")
        self._next_id += 1
        request_id = self._next_id
        envelope = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        line = (json.dumps(envelope) + "\n").encode("utf-8")
        try:
            process.stdin.write(line)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise MCPStdioError(
                f"MCP server '{self.command}' closed its input ({self._exit_detail()})"
            ) from error

        try:
            raw = await asyncio.wait_for(self._read_matching_response(request_id), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as error:
            raise MCPStdioError(
                f"MCP server '{self.command}' did not respond to '{method}' within {self.timeout_seconds}s"
            ) from error

        if "error" in raw:
            error_payload = raw["error"] or {}
            message = error_payload.get("message", "unknown MCP error")
            raise MCPStdioError(f"MCP server '{self.command}' returned an error for '{method}': {message}")
        return raw.get("result", {})

    async def _read_matching_response(self, request_id: int) -> dict[str, Any]:
        process = self._process
        assert process is not None and process.stdout is not None
        while True:
            raw_line = await process.stdout.readline()
            if not raw_line:
                raise MCPStdioError(
                    f"MCP server '{self.command}' closed stdout ({self._exit_detail()})"
                )
            text = raw_line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # Servers occasionally log plain text to stdout by mistake;
                # skip non-JSON-RPC lines instead of hard-failing the call.
                continue
            if not isinstance(parsed, dict):
                continue
            if parsed.get("id") == request_id:
                return parsed
            # Notifications / responses to other in-flight ids (there are
            # none from this transport, but a server may still emit
            # unsolicited notifications) are silently skipped.

    def _exit_detail(self) -> str:
        if self._process is None:
            return "not started"
        code = self._process.returncode
        tail = "; ".join(self._stderr_tail[-3:])
        return f"exit={code}; stderr: {tail}" if tail else f"exit={code}"

    async def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except Exception:
                pass
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass
        self._process = None

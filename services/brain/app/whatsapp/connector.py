from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from .schemas import WhatsAppStatus


class WhatsAppConnectorError(RuntimeError):
    pass


class WhatsAppConnector:
    """Manages a real whatsapp-web.js session as a Node.js child process
    (services/brain/whatsapp_connector/connector.js), the same 'own
    dedicated wrapper' pattern this repo already uses elsewhere rather
    than depending on wweb-mcp's REST/MCP surface directly (that surface
    doesn't expose the QR code over HTTP at all — only to a console/log,
    which is unusable from a UI). Communicates over the child's
    stdin/stdout as newline-delimited JSON, matching Telegram's real-QR
    connect UX (RealTelegramProvider) but for WhatsApp's own-account,
    QR-scan-to-link flow.

    State machine: disconnected -> starting -> qr_pending -> (scan) ->
    authenticated -> ready. auth_failure/disconnected can occur at any
    point and are surfaced honestly, never silently retried forever."""

    def __init__(self, *, connector_dir: Path, auth_data_dir: Path, node_bin: str = "node") -> None:
        self.connector_dir = connector_dir
        self.auth_data_dir = auth_data_dir
        self.node_bin = node_bin
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._status = WhatsAppStatus(state="disconnected")
        self._lock = asyncio.Lock()

    @property
    def status(self) -> WhatsAppStatus:
        return self._status

    def _script_path(self) -> Path:
        return self.connector_dir / "connector.js"

    async def start(self) -> WhatsAppStatus:
        async with self._lock:
            if self._process is not None and self._process.returncode is None:
                return self._status
            if shutil.which(self.node_bin) is None:
                raise WhatsAppConnectorError(f"'{self.node_bin}' was not found on PATH — Node.js is required")
            script = self._script_path()
            if not script.exists():
                raise WhatsAppConnectorError(
                    f"WhatsApp connector script not found at {script} "
                    "(expected services/brain/whatsapp_connector/connector.js with npm install already run)"
                )
            self.auth_data_dir.mkdir(parents=True, exist_ok=True)
            env = {"VYOM_WA_AUTH_PATH": str(self.auth_data_dir)}
            import os

            full_env = {**os.environ, **env}
            self._process = await asyncio.create_subprocess_exec(
                self.node_bin, str(script),
                cwd=str(self.connector_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=full_env,
            )
            self._status = WhatsAppStatus(state="starting")
            self._reader_task = asyncio.create_task(self._read_events())
            return self._status

    async def _read_events(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            async for raw_line in self._process.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._apply_event(event)
        except asyncio.CancelledError:
            pass

    def _apply_event(self, event: dict[str, Any]) -> None:
        name = event.get("event")
        data = event.get("data")
        if name == "starting":
            self._status = WhatsAppStatus(state="starting")
        elif name == "qr":
            self._status = WhatsAppStatus(state="qr_pending", qr_data_url=data)
        elif name == "authenticated":
            self._status = WhatsAppStatus(state="authenticated")
        elif name == "ready":
            info = data or {}
            self._status = WhatsAppStatus(
                state="ready", pushname=info.get("pushname"), wid=info.get("wid"),
            )
        elif name == "disconnected":
            self._status = WhatsAppStatus(state="disconnected", detail=str(data) if data else None)
        elif name == "auth_failure":
            self._status = WhatsAppStatus(state="auth_failure", detail=str(data) if data else None)
        elif name == "error":
            self._status = WhatsAppStatus(state=self._status.state, detail=str(data))

    async def send_message(self, to: str, body: str) -> None:
        if self._process is None or self._process.returncode is not None or self._process.stdin is None:
            raise WhatsAppConnectorError("WhatsApp is not connected")
        recipient = to if "@" in to else f"{to}@c.us"
        payload = json.dumps({"cmd": "send", "to": recipient, "body": body}) + "\n"
        self._process.stdin.write(payload.encode("utf-8"))
        await self._process.stdin.drain()

    async def disconnect(self) -> None:
        async with self._lock:
            if self._reader_task is not None:
                self._reader_task.cancel()
                self._reader_task = None
            if self._process is not None and self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self._process.kill()
            self._process = None
            self._status = WhatsAppStatus(state="disconnected")

    async def health(self) -> tuple[bool, str | None]:
        if self._status.state == "ready":
            return True, None
        return False, f"WhatsApp state: {self._status.state}" + (f" ({self._status.detail})" if self._status.detail else "")

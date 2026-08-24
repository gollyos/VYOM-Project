from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger("vyom.browser_extension")

DEFAULT_TIMEOUT_SECONDS = 15.0


class ExtensionUnavailableError(RuntimeError):
    """No Chrome extension is connected, it disconnected mid-call, or it
    never answered in time. This is a real, reportable state - callers
    must treat it exactly like "no capability", never invent a result."""


class ExtensionCallError(RuntimeError):
    """The extension received the command and reported a genuine failure
    executing it (no matching element, tab closed mid-call, ...)."""


class ExtensionBridge:
    """One live WebSocket connection to the paired Chrome extension.

    One user, one desktop, one paired browser - the same assumption every
    other part of VYOM's runtime makes. A second connection (the extension
    reloading, or the user restarting Chrome) REPLACES the first rather
    than queueing behind it, so a fresh connection always wins over a
    stale one instead of silently going unused."""

    def __init__(self, *, default_timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self._socket: Any = None
        self._pending: dict[str, asyncio.Future] = {}
        self._default_timeout = default_timeout
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._socket is not None

    async def attach(self, websocket: Any) -> None:
        async with self._lock:
            previous, self._socket = self._socket, websocket
        if previous is not None:
            logger.info("extension reconnected; replacing previous connection")
            try:
                await previous.close()
            except Exception:
                pass

    async def detach(self, websocket: Any) -> None:
        async with self._lock:
            if self._socket is websocket:
                self._socket = None
        # Nothing still waiting on this connection can ever be answered now.
        for request_id, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(ExtensionUnavailableError("extension disconnected mid-call"))
            self._pending.pop(request_id, None)

    def resolve(self, message: dict[str, Any]) -> None:
        """Called by the WS receive loop for every frame FROM the
        extension. Matches it to the call() awaiting it by request id.
        An unrecognised or duplicate id is dropped, never raised - a
        malformed or replayed frame must not crash the connection."""
        request_id = message.get("id")
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        if message.get("ok"):
            future.set_result(message.get("result"))
        else:
            future.set_exception(
                ExtensionCallError(str(message.get("error") or "extension reported failure"))
            )

    async def call(self, command: str, params: dict[str, Any] | None = None,
                    *, timeout: float | None = None) -> Any:
        if self._socket is None:
            raise ExtensionUnavailableError("no Chrome extension is connected")
        request_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._socket.send_json({"id": request_id, "cmd": command, "params": params or {}})
        except Exception as error:
            self._pending.pop(request_id, None)
            raise ExtensionUnavailableError(f"failed to send to extension: {error}") from error
        bound = self._default_timeout if timeout is None else timeout
        try:
            return await asyncio.wait_for(future, timeout=bound)
        except asyncio.TimeoutError:
            raise ExtensionUnavailableError(
                f"extension did not answer '{command}' within {bound:.0f}s"
            ) from None
        finally:
            self._pending.pop(request_id, None)

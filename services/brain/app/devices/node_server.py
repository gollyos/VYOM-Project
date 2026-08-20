from __future__ import annotations

from datetime import datetime, timezone

from .schemas import DeviceCapability, DeviceCommand


class MockLocalDeviceNode:
    """A local, in-process mock secondary device node for Phase 9 testing
    and demos. Executes a small set of safe capabilities deterministically
    so pairing/authentication/heartbeat/command-routing/verification can
    be exercised end-to-end without a second physical machine.

    A real remote node would instead receive `DeviceCommand` over an
    authenticated network transport (WebSocket/HTTPS); that transport is
    explicitly future work once the local protocol foundation is proven
    (see docs/DEVICE_NODE_PROTOCOL.md)."""

    def __init__(self):
        self.received_commands: list[DeviceCommand] = []

    async def execute(self, command: DeviceCommand) -> DeviceCommand:
        self.received_commands.append(command)
        if command.capability == DeviceCapability.NOTIFICATIONS_SEND:
            command.result = {"delivered": True, "title": command.payload.get("title")}
        elif command.capability == DeviceCapability.FILE_READ:
            command.result = {"exists": False, "note": "mock node has no real filesystem"}
        elif command.capability == DeviceCapability.APP_OPEN:
            command.result = {"opened": True, "app_id": command.payload.get("app_id")}
        else:
            command.result = {"note": "mock execution: no real device action performed"}
        command.status = "completed"
        command.completed_at = datetime.now(timezone.utc)
        return command

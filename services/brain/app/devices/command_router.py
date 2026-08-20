from __future__ import annotations

from .authentication import AuthenticationError, DevicePairingService
from .registry import DeviceRegistry
from .schemas import DeviceCapability, DeviceCommand, DeviceOnlineStatus, DeviceTrustLevel


class DeviceCommandError(Exception):
    pass


class DeviceCommandRouter:
    """resolve target node -> check online -> check capability -> check
    trust/authentication -> send. A remote node never receives unlimited
    authority: every command still needs the node in the explicit
    capability allow-list, TRUSTED status, and a valid token, on top of
    the same Permission Engine / Tool Registry / audit boundary every
    other VYOM action passes through."""

    def __init__(self, registry: DeviceRegistry, pairing: DevicePairingService):
        self.registry = registry
        self.pairing = pairing

    def route(self, node_id: str, capability: DeviceCapability, payload: dict, *, token: str) -> DeviceCommand:
        node = self.registry.get(node_id)
        if node is None:
            raise DeviceCommandError(f"Unknown device node: {node_id}")
        if node.trust_level != DeviceTrustLevel.TRUSTED:
            raise DeviceCommandError(f"Device '{node_id}' is not trusted (trust_level={node.trust_level.value})")
        if not self.pairing.authenticate(node_id, token):
            raise AuthenticationError("Device authentication failed")
        if node.online != DeviceOnlineStatus.ONLINE:
            raise DeviceCommandError(f"Device '{node_id}' is not online (status={node.online.value})")
        if capability not in node.capabilities:
            raise DeviceCommandError(f"Device '{node_id}' does not have capability '{capability.value}'")
        return DeviceCommand(node_id=node_id, capability=capability, payload=payload, status="sent")

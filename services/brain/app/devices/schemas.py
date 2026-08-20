from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceType(str, Enum):
    DESKTOP_PC = "desktop_pc"
    LAPTOP = "laptop"
    MOBILE = "mobile"
    HOME_SERVER = "home_server"


class DeviceTrustLevel(str, Enum):
    UNPAIRED = "unpaired"
    PENDING = "pending"
    TRUSTED = "trusted"
    REVOKED = "revoked"


class DeviceOnlineStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


class DeviceCapability(str, Enum):
    SCREEN_CAPTURE = "screen.capture"
    NOTIFICATIONS_SEND = "notifications.send"
    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    APP_OPEN = "app.open"
    LOCATION_READ = "location.read"
    CAMERA_CAPTURE = "camera.capture"
    MICROPHONE = "microphone"
    # Phase 12 execution-node capabilities.
    RESEARCH = "task.research"
    ARTIFACTS = "task.artifacts"
    AUTOMATIONS = "task.automations"
    EMAIL = "task.email"
    CALENDAR = "task.calendar"
    CODING = "task.coding"
    TERMINAL = "task.terminal"
    BROWSER = "task.browser"
    GPU = "compute.gpu"
    VOICE = "input.voice"


class NodeRole(str, Enum):
    BRAIN_COORDINATOR = "brain_coordinator"
    EXECUTION_NODE = "execution_node"
    CLIENT_DEVICE = "client_device"
    WORKER_NODE = "worker_node"


class NodePresence(BaseModel):
    """Voluntary, minimal presence metadata. VYOM never continuously
    collects location or device telemetry; fields are populated only when
    the node itself reports them with its heartbeat."""

    battery_percent: int | None = None
    on_battery: bool | None = None
    network_type: str | None = None  # e.g. "wifi", "ethernet", "cellular"
    busy: bool = False
    idle: bool = False


class NodeVersionInfo(BaseModel):
    app_version: str = "0.1.0"
    protocol_version: str = "1"
    schema_version: str = "1"


class DeviceNode(BaseModel):
    node_id: str = Field(default_factory=lambda: f"node_{uuid4().hex}")
    name: str
    device_type: DeviceType
    platform: str
    capabilities: list[DeviceCapability] = Field(default_factory=list)
    trust_level: DeviceTrustLevel = DeviceTrustLevel.UNPAIRED
    online: DeviceOnlineStatus = DeviceOnlineStatus.OFFLINE
    last_seen: datetime | None = None
    permissions: list[str] = Field(default_factory=list)
    version: str = "0.1.0"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    # -- Phase 12 extensions (all optional so existing nodes stay valid) --
    roles: list[NodeRole] = Field(default_factory=list)
    version_info: NodeVersionInfo = Field(default_factory=NodeVersionInfo)
    presence: NodePresence = Field(default_factory=NodePresence)
    runtime_health: str = "unknown"  # healthy | degraded | offline | unknown


class PairingRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: f"pair_{uuid4().hex}")
    name: str
    device_type: DeviceType
    platform: str
    requested_capabilities: list[DeviceCapability] = Field(default_factory=list)
    code: str
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime


class DeviceCommand(BaseModel):
    command_id: str = Field(default_factory=lambda: f"cmd_{uuid4().hex}")
    node_id: str
    capability: DeviceCapability
    payload: dict = Field(default_factory=dict)
    status: str = "pending"
    result: dict | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

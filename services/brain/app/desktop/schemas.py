from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationType(str, Enum):
    NATIVE_API = "native_api"
    CLI = "cli"
    ACCESSIBILITY = "accessibility"
    BROWSER = "browser"
    VISUAL_FALLBACK = "visual_fallback"


class ApplicationTrust(str, Enum):
    TRUSTED = "trusted"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class ApplicationHealth(str, Enum):
    AVAILABLE = "available"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


class ApplicationRecord(BaseModel):
    app_id: str
    name: str
    executable: str | None = None
    launch_method: str = "native"
    supported_actions: list[str] = Field(default_factory=list)
    integration_type: IntegrationType = IntegrationType.VISUAL_FALLBACK
    permissions: list[str] = Field(default_factory=list)
    trust: ApplicationTrust = ApplicationTrust.UNKNOWN
    health: ApplicationHealth = ApplicationHealth.UNKNOWN
    #: Packaged (UWP/Store) application identity. Windows 11 ships
    #: Calculator, Settings and Notepad this way: `calc.exe` is a stub that
    #: hands off and exits, so a PID-based launch check reported "not
    #: running" for an app the user could plainly see. Launching through
    #: `shell:AppsFolder\<aumid>` is what the Start Menu itself does.
    aumid: str | None = None
    #: Protocol handler, for surfaces that have no executable at all
    #: (`ms-settings:bluetooth`). This is a NATIVE launch path -- it is
    #: what removes the need to drive Settings through a shell.
    uri: str | None = None
    #: Window title substring used to find this app's visible window.
    window_title: str | None = None
    #: Process image names this app produces once running.
    process_names: list[str] = Field(default_factory=list)


class AppStatus(BaseModel):
    app_id: str
    running: bool
    pid: int | None = None
    window_title: str | None = None


class WindowInfo(BaseModel):
    window_id: int
    title: str
    app_id: str | None = None
    display_id: int | None = None
    x: int
    y: int
    width: int
    height: int
    minimized: bool = False
    maximized: bool = False
    focused: bool = False


class DisplayInfo(BaseModel):
    display_id: int
    resolution: tuple[int, int]
    scale: float = 1.0
    position: tuple[int, int]
    primary: bool = False


class ClipboardEntry(BaseModel):
    content_type: str = "text"
    length: int = 0
    read_at: datetime = Field(default_factory=utc_now)


class NotificationRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"notif_{uuid4().hex}")
    title: str
    body: str
    urgency: str = "normal"
    category: str
    action_task_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class SystemStatus(BaseModel):
    cpu_percent: float
    memory_percent: float
    memory_total_gb: float
    disk_free_gb: float
    disk_total_gb: float
    battery_percent: float | None = None
    battery_plugged: bool | None = None
    network_connected: bool = True
    vyom_processes: int = 0
    generated_at: datetime = Field(default_factory=utc_now)


class StartupStatus(BaseModel):
    enabled: bool
    method: str
    detail: str = ""

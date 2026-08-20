from __future__ import annotations

from pydantic import BaseModel, Field

from app.devices.schemas import utc_now
from app.sync.journal import SyncJournal
from app.sync.schemas import SyncEntity

SENSITIVE_MARKERS = ("password", "token", "secret", "otp", "mfa", "client", "salary")


class RoutedNotification(BaseModel):
    notification_id: str
    title: str
    body: str
    priority: str = "normal"  # info | normal | urgent | critical
    destinations: list[str] = Field(default_factory=list)  # desktop | mobile | quiet_queue
    created_at: object = None


class RemoteNotificationRouter:
    """Routes notifications intelligently across devices with
    deduplicated read-state. Informational items go desktop-only or
    batch; urgent approvals hit mobile + desktop; critical hits every
    trusted active device. Push payloads carry a generic title —
    private content stays out of lock-screen previews."""

    def __init__(self, journal: SyncJournal):
        self.journal = journal

    @staticmethod
    def sanitize_for_push(title: str, body: str) -> tuple[str, str]:
        lowered = f"{title} {body}".lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            return title, "Details require unlocking VYOM."
        return title, body[:140]

    def route(self, title: str, body: str, priority: str = "normal", mobile_available: bool = True, quiet_mode: bool = False) -> RoutedNotification:
        destinations: list[str] = []
        if priority == "critical":
            destinations = ["desktop", "mobile"] if mobile_available else ["desktop"]
        elif priority == "urgent":
            if quiet_mode:
                destinations = ["quiet_queue"]
            else:
                destinations = ["desktop", "mobile"] if mobile_available else ["desktop"]
        elif priority == "normal":
            destinations = ["desktop"]
        else:  # info
            destinations = ["quiet_queue"] if quiet_mode else ["desktop"]
        sanitized_title, sanitized_body = self.sanitize_for_push(title, body)
        return RoutedNotification(
            notification_id=f"notif_{utc_now().timestamp():.0f}_{len(title)}",
            title=sanitized_title, body=sanitized_body, priority=priority, destinations=destinations,
            created_at=utc_now().isoformat(),
        )

    async def record_state(self, notification_id: str, state: str) -> None:
        """unread -> read -> acted_on/dismissed. State changes append to
        the sync journal so a notification read on mobile stops nagging
        on desktop."""
        if state not in {"unread", "read", "acted_on", "dismissed"}:
            raise ValueError(f"Invalid notification state {state!r}")
        await self.journal.record_state_change(
            SyncEntity.NOTIFICATION, notification_id, {"notification_id": notification_id, "state": state},
        )

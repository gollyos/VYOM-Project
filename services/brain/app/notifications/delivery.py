from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .priority import NotificationPriority
from .quiet_hours import QuietModeState
from .service import Notification, NotificationService


class NotificationRecordStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, notification: Notification, priority: NotificationPriority) -> None:
        connection = self.database.require_connection()
        now = datetime.now(timezone.utc).isoformat()
        await connection.execute(
            "INSERT INTO notification_records(id, priority, outcome, notification_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (notification.id, priority.value, None, notification.model_dump_json(), notification.created_at.isoformat(), now),
        )
        await connection.commit()


class NotificationDeliveryService:
    """The integration point every other Phase 11 module notifies
    through. Applies quiet-mode suppression before delivery (rule 33) —
    `critical` always bypasses it. Delivered notifications are recorded so
    `notifications/preferences.py`'s learning loop has real outcomes to
    read (rule 36)."""

    def __init__(self, service: NotificationService, quiet_mode: QuietModeState, record_store: NotificationRecordStore | None = None):
        self.service = service
        self.quiet_mode = quiet_mode
        self.record_store = record_store

    async def deliver(self, title: str, body: str, *, priority: NotificationPriority = NotificationPriority.NORMAL, action_task_id: str | None = None) -> Notification | None:
        if priority != NotificationPriority.CRITICAL and self.quiet_mode.is_active():
            return None  # suppressed; retained for later batch via the notification history the caller already tracks
        notification = Notification(title=title, body=body, urgency=priority.value, action_task_id=action_task_id)
        self.service.publish(notification)
        if self.record_store is not None:
            await self.record_store.save(notification, priority)
        return notification

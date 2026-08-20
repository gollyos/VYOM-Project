from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field
from uuid import uuid4


class Notification(BaseModel):
    id: str = Field(default_factory=lambda: f"notification_{uuid4().hex}")
    title: str
    body: str
    urgency: str = "normal"
    action_task_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationService:
    def __init__(self) -> None:
        self._items: list[Notification] = []

    def publish(self, notification: Notification) -> Notification:
        self._items.append(notification)
        self._items = self._items[-100:]
        return notification

    def list(self) -> list[Notification]:
        return list(reversed(self._items))

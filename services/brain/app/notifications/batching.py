from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from .priority import NotificationPriority
from .service import Notification


class BatchedNotification(BaseModel):
    title: str
    body: str
    item_count: int
    items: list[Notification] = Field(default_factory=list)


class NotificationBatcher:
    """Groups minor notifications instead of sending them one at a time
    (rule 35): "4 background tasks completed. One requires your
    attention." — expandable by the user, never silently dropped."""

    def __init__(self, *, batch_window_minutes: float = 15, min_items_to_batch: int = 3):
        self.batch_window_minutes = batch_window_minutes
        self.min_items_to_batch = min_items_to_batch

    def batch(self, pending: list[Notification], *, now: datetime | None = None) -> tuple[list[BatchedNotification], list[Notification]]:
        """Returns (batches, passthrough) — low/informational items within
        the window are batched when there are enough of them; anything
        `important` or above always passes through individually."""
        current_time = now or datetime.now(timezone.utc)
        window_start = current_time - timedelta(minutes=self.batch_window_minutes)

        minor: list[Notification] = []
        passthrough: list[Notification] = []
        for item in pending:
            priority = NotificationPriority(item.urgency) if item.urgency in {p.value for p in NotificationPriority} else NotificationPriority.NORMAL
            if priority.rank() <= NotificationPriority.LOW.rank() and item.created_at >= window_start:
                minor.append(item)
            else:
                passthrough.append(item)

        if len(minor) < self.min_items_to_batch:
            return [], passthrough + minor

        needing_attention = [item for item in minor if "requires your attention" in item.body.lower()]
        summary = f"{len(minor)} background item(s) completed."
        if needing_attention:
            summary += f" {len(needing_attention)} require(s) your attention."
        batch = BatchedNotification(title="Background updates", body=summary, item_count=len(minor), items=minor)
        return [batch], passthrough

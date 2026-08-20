from __future__ import annotations

from datetime import datetime, timezone

from .schemas import NotificationRequest

MEANINGFUL_CATEGORIES = {
    "approval_required", "reply_detected", "automation_completed", "task_failed",
    "meeting_soon", "coding_task_completed", "needs_intervention",
}


class NotificationPolicy:
    """Only meaningful categories are dispatched -- no periodic status
    spam. A minimum interval between notifications keeps bursts of Brain
    activity from flooding the user."""

    def __init__(self, meaningful_categories: set[str] | None = None, min_seconds_between: int = 5):
        self.meaningful_categories = meaningful_categories or MEANINGFUL_CATEGORIES
        self.min_seconds_between = min_seconds_between
        self._last_dispatch: datetime | None = None

    def should_dispatch(self, request: NotificationRequest) -> bool:
        if request.category not in self.meaningful_categories:
            return False
        now = datetime.now(timezone.utc)
        if self._last_dispatch and (now - self._last_dispatch).total_seconds() < self.min_seconds_between:
            return False
        self._last_dispatch = now
        return True


class NotificationDispatcher:
    """Builds and policy-filters notifications. Actual OS-level toast
    delivery happens in the Tauri/frontend layer -- the Brain has no
    window handle -- via a `notification_dispatched` event the frontend
    relays to the native notification plugin. Clicking a notification
    opens VYOM in the relevant context using `action_task_id`."""

    def __init__(self, policy: NotificationPolicy | None = None):
        self.policy = policy or NotificationPolicy()
        self.history: list[NotificationRequest] = []

    def dispatch(self, request: NotificationRequest) -> NotificationRequest | None:
        if not self.policy.should_dispatch(request):
            return None
        self.history.append(request)
        self.history = self.history[-200:]
        return request

    def recent(self, limit: int = 20) -> list[NotificationRequest]:
        return list(reversed(self.history))[:limit]

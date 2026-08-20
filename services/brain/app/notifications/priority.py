from __future__ import annotations

from enum import Enum

PRIORITY_ORDER = ["informational", "low", "normal", "important", "urgent", "critical"]


class NotificationPriority(str, Enum):
    INFORMATIONAL = "informational"
    LOW = "low"
    NORMAL = "normal"
    IMPORTANT = "important"
    URGENT = "urgent"
    CRITICAL = "critical"

    def rank(self) -> int:
        return PRIORITY_ORDER.index(self.value)


# Deterministic mapping from known event categories to priority (rule 34)
# — no model call needed to classify a known event type.
_EVENT_PRIORITY: dict[str, NotificationPriority] = {
    "agent_minor_research_completed": NotificationPriority.INFORMATIONAL,
    "automation_completed": NotificationPriority.INFORMATIONAL,
    "client_deadline_risk": NotificationPriority.IMPORTANT,
    "meeting_soon": NotificationPriority.URGENT,
    "security_critical_action": NotificationPriority.CRITICAL,
    "financial_critical_action": NotificationPriority.CRITICAL,
    "approval_required": NotificationPriority.IMPORTANT,
    "commitment_overdue": NotificationPriority.IMPORTANT,
    "risk_kill_switch_triggered": NotificationPriority.CRITICAL,
}


def classify(event_key: str, *, default: NotificationPriority = NotificationPriority.NORMAL) -> NotificationPriority:
    return _EVENT_PRIORITY.get(event_key, default)

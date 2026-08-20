from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ContextEvent(BaseModel):
    timestamp: datetime
    context: str   # e.g. a task domain, project id, or app name


class ContextSwitchReport(BaseModel):
    switch_count: int
    contexts: list[str]
    sample_size: int


class ContextSwitchTracker:
    """Counts context changes from real VYOM task/app events supplied by
    the caller (rule 22) — never inferred from raw screen surveillance.
    Callers source `ContextEvent`s from things VYOM already observes:
    task creation domains, focus-session goals, or Phase 9 app-focus
    events."""

    def analyze(self, events: list[ContextEvent]) -> ContextSwitchReport | None:
        if len(events) < 2:
            return None
        ordered = sorted(events, key=lambda event: event.timestamp)
        switches = sum(1 for i in range(1, len(ordered)) if ordered[i].context != ordered[i - 1].context)
        return ContextSwitchReport(switch_count=switches, contexts=sorted({event.context for event in ordered}), sample_size=len(ordered))

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.persistence.database import Database

from .rules import ProactiveSuggestion


class ProactiveSuggestionStore:
    """Persists surfaced suggestions so "has this already been surfaced?"
    and daily rate limits are answered from real records, not memory."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def record_surfaced(self, suggestion: ProactiveSuggestion) -> None:
        connection = self.database.require_connection()
        now = datetime.now(timezone.utc).isoformat()
        await connection.execute(
            "INSERT INTO proactive_suggestions(id, status, dedupe_key, suggestion_json, created_at, surfaced_at) VALUES (?, ?, ?, ?, ?, ?)",
            (suggestion.id, "surfaced", suggestion.compute_dedupe_key(), suggestion.model_dump_json(), suggestion.created_at.isoformat(), now),
        )
        await connection.commit()

    async def recently_surfaced(self, dedupe_key: str, *, within_hours: float) -> bool:
        connection = self.database.require_connection()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
        row = await (await connection.execute(
            "SELECT id FROM proactive_suggestions WHERE dedupe_key = ? AND surfaced_at >= ? LIMIT 1", (dedupe_key, cutoff)
        )).fetchone()
        return row is not None

    async def update_outcome(self, suggestion_id: str, outcome: str) -> None:
        connection = self.database.require_connection()
        await connection.execute("UPDATE proactive_suggestions SET status = ? WHERE id = ?", (outcome, suggestion_id))
        await connection.commit()

    async def outcomes_for_title(self, title: str) -> list[str]:
        connection = self.database.require_connection()
        rows = await (await connection.execute("SELECT status, suggestion_json FROM proactive_suggestions")).fetchall()
        return [row["status"] for row in rows if ProactiveSuggestion.model_validate_json(row["suggestion_json"]).title == title]

    async def count_low_priority_today(self) -> int:
        connection = self.database.require_connection()
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        rows = await (await connection.execute(
            "SELECT suggestion_json FROM proactive_suggestions WHERE surfaced_at >= ?", (start_of_day,)
        )).fetchall()
        count = 0
        for row in rows:
            suggestion = ProactiveSuggestion.model_validate_json(row["suggestion_json"])
            if suggestion.urgency in {"informational", "low"}:
                count += 1
        return count


class SuppressionResult:
    def __init__(self, allowed: bool, reason: str):
        self.allowed = allowed
        self.reason = reason


class SuppressionEngine:
    """Duplicate suppression + daily low-priority rate limiting
    (rule 35/36) — a genuinely critical suggestion is never suppressed by
    the rate limit (only `informational`/`low` count against it)."""

    def __init__(self, store: ProactiveSuggestionStore):
        self.store = store

    async def check(self, suggestion: ProactiveSuggestion, *, duplicate_window_hours: float, max_low_priority_per_day: int) -> SuppressionResult:
        dedupe_key = suggestion.compute_dedupe_key()
        if await self.store.recently_surfaced(dedupe_key, within_hours=duplicate_window_hours):
            return SuppressionResult(False, f"An equivalent suggestion was already surfaced within the last {duplicate_window_hours}h")
        if suggestion.urgency in {"informational", "low"}:
            count = await self.store.count_low_priority_today()
            if count >= max_low_priority_per_day:
                return SuppressionResult(False, f"Daily low-priority notification limit ({max_low_priority_per_day}) already reached")
        return SuppressionResult(True, "Not a duplicate; within daily limits")

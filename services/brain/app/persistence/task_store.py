from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.schemas.tasks import Task, TaskStatus

from .database import Database


class TaskStore:
    def __init__(self, database: Database):
        self.database = database

    async def save(self, task: Task) -> None:
        connection = self.database.require_connection()
        now = datetime.now(timezone.utc).isoformat()
        await connection.execute(
            """
            INSERT INTO tasks(id, status, task_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                task_json = excluded.task_json,
                updated_at = excluded.updated_at
            """,
            (
                task.id,
                task.status.value,
                json.dumps(task.model_dump(mode="json"), separators=(",", ":")),
                task.created_at.isoformat(),
                now,
            ),
        )
        await connection.commit()

    async def get(self, task_id: str) -> Task | None:
        connection = self.database.require_connection()
        cursor = await connection.execute("SELECT task_json FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        return Task.model_validate_json(row["task_json"]) if row else None

    async def list(self, limit: int = 100) -> list[Task]:
        connection = self.database.require_connection()
        cursor = await connection.execute(
            "SELECT task_json FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [Task.model_validate_json(row["task_json"]) for row in await cursor.fetchall()]

    async def search_history(
        self,
        *,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        text: str = "",
        exclude_task_id: str | None = None,
        limit: int = 20,
    ) -> list[Task]:
        """Search durable user requests, applying date/text filters before LIMIT.

        Tasks are the authoritative record of what the user actually said;
        a generated episodic summary is evidence of an outcome, not a safe
        substitute for the original statement.
        """
        clauses: list[str] = []
        parameters: list[object] = []
        if created_after:
            clauses.append("created_at >= ?")
            parameters.append(created_after.isoformat())
        if created_before:
            clauses.append("created_at < ?")
            parameters.append(created_before.isoformat())
        if exclude_task_id:
            clauses.append("id <> ?")
            parameters.append(exclude_task_id)

        stopwords = {
            "about", "client", "project", "regarding", "the", "a", "an",
            "ke", "ki", "ka", "bare", "baare", "me", "mein",
        }
        tokens = [
            token for token in re.findall(r"[\w.-]+", text.lower(), re.UNICODE)
            if len(token) > 1 and token not in stopwords
        ]
        for token in tokens[:8]:
            clauses.append("lower(json_extract(task_json, '$.user_request')) LIKE ?")
            parameters.append(f"%{token}%")

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(max(1, min(limit, 100)))
        cursor = await self.database.require_connection().execute(
            f"SELECT task_json FROM tasks{where} ORDER BY created_at DESC LIMIT ?",
            parameters,
        )
        return [Task.model_validate_json(row["task_json"]) for row in await cursor.fetchall()]

    async def list_by_status(self, statuses: set[TaskStatus]) -> list[Task]:
        if not statuses:
            return []
        connection = self.database.require_connection()
        values = [status.value for status in statuses]
        placeholders = ",".join("?" for _ in values)
        cursor = await connection.execute(
            f"SELECT task_json FROM tasks WHERE status IN ({placeholders}) ORDER BY created_at",
            values,
        )
        return [Task.model_validate_json(row["task_json"]) for row in await cursor.fetchall()]

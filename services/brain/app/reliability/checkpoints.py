from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.devices.schemas import utc_now


class TaskCheckpoint(BaseModel):
    """Durable progress snapshot for a long-running task. Contains
    only resumable operational state — task status, plan step,
    completed tool calls, evidence references, pending approval,
    budget consumed, artifacts. Hidden model reasoning is never
    persisted here."""

    task_id: str
    checkpoint_id: str = Field(default_factory=lambda: f"ckpt_{uuid4().hex}")
    task_state: dict = Field(default_factory=dict)
    current_plan_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    completed_tool_calls: list[dict] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)
    pending_approval: dict | None = None
    budget_consumed: dict = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class CheckpointStore:
    def __init__(self, database):
        self.database = database

    async def save(self, checkpoint: TaskCheckpoint) -> None:
        await self.database.require_connection().execute(
            """
            INSERT INTO task_checkpoints (task_id, checkpoint_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET checkpoint_json = excluded.checkpoint_json,
                created_at = excluded.created_at
            """,
            (checkpoint.task_id, checkpoint.model_dump_json(), checkpoint.created_at.isoformat()),
        )
        await self.database.require_connection().commit()

    async def get(self, task_id: str) -> TaskCheckpoint | None:
        cursor = await self.database.require_connection().execute(
            "SELECT checkpoint_json FROM task_checkpoints WHERE task_id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        return None if row is None else TaskCheckpoint.model_validate_json(row["checkpoint_json"])

    async def delete(self, task_id: str) -> None:
        await self.database.require_connection().execute(
            "DELETE FROM task_checkpoints WHERE task_id = ?", (task_id,)
        )
        await self.database.require_connection().commit()

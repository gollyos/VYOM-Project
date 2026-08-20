from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.schemas.tasks import Task

from .database import Database


class ModelPerformanceStore:
    def __init__(self, database: Database):
        self.database = database

    async def record(
        self,
        *,
        task: Task,
        model: str,
        provider: str,
        success: bool,
        latency_ms: float,
        retries: int,
        fallback_used: bool,
    ) -> None:
        connection = self.database.require_connection()
        usage = task.result.usage.model_dump(mode="json") if task.result else {}
        estimated_cost = task.result.usage.estimated_cost if task.result else None
        score = task.verification.score if task.verification else 0
        await connection.execute(
            """
            INSERT INTO model_performance(
                model, provider, task_domain, complexity, success, verification_score,
                latency_ms, retries, fallback_used, usage_json, estimated_cost, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model,
                provider,
                task.domain.value,
                task.complexity,
                int(success),
                score,
                latency_ms,
                retries,
                int(fallback_used),
                json.dumps(usage, separators=(",", ":")),
                estimated_cost,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await connection.commit()

    async def statistics(self, model: str, domain: str) -> dict[str, Any]:
        connection = self.database.require_connection()
        cursor = await connection.execute(
            """
            SELECT COUNT(*) AS samples,
                   AVG(success) AS success_rate,
                   AVG(verification_score) AS verification_score,
                   AVG(latency_ms) AS latency_ms
            FROM model_performance WHERE model = ? AND task_domain = ?
            """,
            (model, domain),
        )
        row = await cursor.fetchone()
        return {
            "samples": int(row["samples"] or 0),
            "success_rate": float(row["success_rate"] or 0),
            "verification_score": float(row["verification_score"] or 0),
            "latency_ms": float(row["latency_ms"] or 0),
        }


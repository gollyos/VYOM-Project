from __future__ import annotations

from collections import defaultdict

from app.schemas.routing import UsageRecord


class UsageTracker:
    def __init__(self):
        self.by_model: dict[str, list[UsageRecord]] = defaultdict(list)

    def record(self, model: str, usage: UsageRecord) -> None:
        self.by_model[model].append(usage)

    def summary(self, model: str) -> dict[str, float | int]:
        records = self.by_model.get(model, [])
        return {
            "requests": len(records),
            "tokens": sum(record.total_tokens or 0 for record in records),
            "estimated_cost": sum(record.estimated_cost or 0 for record in records),
        }


from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone


class CostTracker:
    """AI/API cost observability: tracks calls, usage, cost, failures,
    and retries by provider/model/day, complemented by the persisted
    `model_performance` rows. "How much did VYOM cost today?" returns
    real tracked data — never an estimate presented as a measurement."""

    def __init__(self, metrics, performance_store=None):
        self.metrics = metrics
        self.performance_store = performance_store
        self._live: dict[str, dict] = defaultdict(
            lambda: {"calls": 0, "input": 0, "output": 0, "cost": 0.0, "failures": 0, "retries": 0}
        )

    def record_call(
        self, provider: str, model: str, *, input_tokens: int = 0, output_tokens: int = 0,
        cost: float = 0.0, failed: bool = False, retried: bool = False,
    ) -> None:
        day = datetime.now(timezone.utc).date().isoformat()
        bucket = self._live[f"{day}|{provider}|{model}"]
        bucket["calls"] += 1
        bucket["input"] += input_tokens
        bucket["output"] += output_tokens
        bucket["cost"] += cost
        if failed:
            bucket["failures"] += 1
        if retried:
            bucket["retries"] += 1
        self.metrics.increment("model_calls", provider=provider, model=model)
        if failed:
            self.metrics.increment("model_failures", provider=provider)
        self.metrics.gauge("model_cost", round(bucket["cost"], 6), provider=provider)

    async def summary(self, days: int = 1) -> dict:
        since_day = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "failures": 0, "retries": 0}
        by_provider: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cost": 0.0})
        by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cost": 0.0})
        for key, bucket in self._live.items():
            day, provider, model = key.split("|", 2)
            if day < since_day:
                continue
            totals["calls"] += bucket["calls"]
            totals["input_tokens"] += bucket["input"]
            totals["output_tokens"] += bucket["output"]
            totals["cost"] += bucket["cost"]
            totals["failures"] += bucket["failures"]
            totals["retries"] += bucket["retries"]
            by_provider[provider]["calls"] += bucket["calls"]
            by_provider[provider]["cost"] += bucket["cost"]
            by_model[model]["calls"] += bucket["calls"]
            by_model[model]["cost"] += bucket["cost"]

        persisted_calls = 0
        persisted_cost = 0.0
        if self.performance_store is not None:
            try:
                since = datetime.now(timezone.utc) - timedelta(days=days)
                connection = self.performance_store.database.require_connection()
                cursor = await connection.execute(
                    "SELECT COUNT(*) AS calls, COALESCE(SUM(estimated_cost), 0.0) AS cost "
                    "FROM model_performance WHERE created_at >= ?",
                    (since.isoformat(),),
                )
                row = await cursor.fetchone()
                persisted_calls = int(row["calls"])
                persisted_cost = float(row["cost"])
            except Exception:
                persisted_calls, persisted_cost = 0, 0.0
        return {
            "days": days,
            "live": {
                **{key: (round(value, 6) if key == "cost" else value) for key, value in totals.items()},
            },
            "persisted_model_calls": persisted_calls,
            "persisted_estimated_cost": round(persisted_cost, 6),
            "by_provider": {name: {"calls": v["calls"], "cost": round(v["cost"], 6)} for name, v in by_provider.items()},
            "by_model": {name: {"calls": v["calls"], "cost": round(v["cost"], 6)} for name, v in by_model.items()},
        }

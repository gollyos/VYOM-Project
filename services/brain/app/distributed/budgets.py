from __future__ import annotations

import json
from dataclasses import dataclass

from app.devices.schemas import utc_now


@dataclass
class BudgetLimits:
    daily_model_cost: float = 5.0
    daily_research_calls: int = 50
    # The personal operator contract guarantees that a burst of ten
    # independent tasks can remain separately owned. This is a capacity
    # ceiling, not permission to mix their contexts or effects.
    max_concurrent_tasks: int = 10
    max_active_agents: int = 8
    max_browser_sessions: int = 3


class BudgetExceededError(Exception):
    pass


class GlobalBudgetManager:
    """System-wide resource budgets for the 24/7 runtime. Integrates
    with the existing Cost Manager philosophy: when a budget nears its
    limit, callers should defer non-critical work, use cheaper models,
    or pause expensive automations — and a hard limit is never silently
    exceeded."""

    def __init__(self, database, limits: BudgetLimits | None = None):
        self.database = database
        self.limits = limits or BudgetLimits()

    async def _load_today(self) -> dict:
        day = utc_now().date().isoformat()
        cursor = await self.database.require_connection().execute(
            "SELECT budget_json FROM budget_usage WHERE day = ?", (day,)
        )
        row = await cursor.fetchone()
        if row is None:
            return {
                "model_cost": 0.0,
                "research_calls": 0,
                "concurrent_tasks": 0,
                "active_agents": 0,
                "browser_sessions": 0,
            }
        return json.loads(row["budget_json"])

    async def _save_today(self, usage: dict) -> None:
        day = utc_now().date().isoformat()
        await self.database.require_connection().execute(
            """
            INSERT INTO budget_usage (day, budget_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET budget_json = excluded.budget_json, updated_at = excluded.updated_at
            """,
            (day, json.dumps(usage), utc_now().isoformat()),
        )
        await self.database.require_connection().commit()

    async def usage(self) -> dict:
        return await self._load_today()

    async def record(self, **deltas) -> dict:
        usage = await self._load_today()
        for key, value in deltas.items():
            usage[key] = usage.get(key, 0) + value
        await self._save_today(usage)
        return usage

    async def check_allowed(self, **increase) -> tuple[bool, list[str]]:
        usage = await self._load_today()
        projected = dict(usage)
        for key, value in increase.items():
            projected[key] = projected.get(key, 0) + value
        violations: list[str] = []
        limit_map = {
            "model_cost": self.limits.daily_model_cost,
            "research_calls": self.limits.daily_research_calls,
            "concurrent_tasks": self.limits.max_concurrent_tasks,
            "active_agents": self.limits.max_active_agents,
            "browser_sessions": self.limits.max_browser_sessions,
        }
        for key, limit in limit_map.items():
            if projected.get(key, 0) > limit:
                violations.append(f"{key} would reach {projected[key]} (limit {limit})")
        return (not violations), violations

    async def enforce(self, **increase) -> None:
        allowed, violations = await self.check_allowed(**increase)
        if not allowed:
            raise BudgetExceededError("; ".join(violations))

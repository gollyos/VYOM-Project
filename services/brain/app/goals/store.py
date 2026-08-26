from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import Goal, GoalStatus, Milestone


class GoalStore:
    def __init__(self, database: Database, memory=None) -> None:
        self.database = database
        #: Optional MemoryManager - when given, every save() also
        #: mirrors the goal into the shared cross-domain memory graph
        #: (see app/memory/cross_domain.py) so it is findable alongside
        #: habits, CRM contacts, and researched facts, not just from
        #: this table. None is a valid, fully-supported mode (tests,
        #: or contexts where memory isn't wired) - mirroring is
        #: strictly additive and never required for goals to work.
        self.memory = memory

    async def save(self, goal: Goal) -> Goal:
        goal.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO goals(id, status, category, goal_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, category=excluded.category, goal_json=excluded.goal_json, updated_at=excluded.updated_at""",
            (goal.id, goal.status.value, goal.category.value, goal.model_dump_json(), goal.created_at.isoformat(), goal.updated_at.isoformat()),
        )
        await connection.commit()
        if self.memory is not None:
            from app.memory.cross_domain import mirror
            from app.memory.namespaces import CognitiveNamespace

            await mirror(
                self.memory, namespace=CognitiveNamespace.PERSONAL, domain_store="goal", record_id=goal.id,
                title=f"Goal: {goal.title}",
                content=f"{goal.title} — {goal.description} (status: {goal.status.value}, category: {goal.category.value})",
                entities=[goal.title], extra_tags=[f"status:{goal.status.value}", f"category:{goal.category.value}"],
                importance=0.6 if goal.status.value == "active" else 0.4,
            )
        return goal

    async def get(self, goal_id: str) -> Goal | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT goal_json FROM goals WHERE id = ?", (goal_id,))).fetchone()
        return Goal.model_validate_json(row["goal_json"]) if row else None

    async def list(self, status: GoalStatus | None = None) -> list[Goal]:
        connection = self.database.require_connection()
        if status:
            rows = await (await connection.execute("SELECT goal_json FROM goals WHERE status = ? ORDER BY updated_at DESC", (status.value,))).fetchall()
        else:
            rows = await (await connection.execute("SELECT goal_json FROM goals ORDER BY updated_at DESC")).fetchall()
        return [Goal.model_validate_json(row["goal_json"]) for row in rows]

    async def find_by_title(self, title: str) -> Goal | None:
        normalized = title.strip().lower()
        for goal in await self.list():
            if goal.title.strip().lower() == normalized:
                return goal
        return None


class MilestoneStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, milestone: Milestone) -> Milestone:
        milestone.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO milestones(id, goal_id, status, milestone_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, milestone_json=excluded.milestone_json, updated_at=excluded.updated_at""",
            (milestone.id, milestone.goal_id, milestone.status.value, milestone.model_dump_json(), milestone.created_at.isoformat(), milestone.updated_at.isoformat()),
        )
        await connection.commit()
        return milestone

    async def get(self, milestone_id: str) -> Milestone | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT milestone_json FROM milestones WHERE id = ?", (milestone_id,))).fetchone()
        return Milestone.model_validate_json(row["milestone_json"]) if row else None

    async def list_for_goal(self, goal_id: str) -> list[Milestone]:
        connection = self.database.require_connection()
        rows = await (await connection.execute("SELECT milestone_json FROM milestones WHERE goal_id = ? ORDER BY created_at ASC", (goal_id,))).fetchall()
        return [Milestone.model_validate_json(row["milestone_json"]) for row in rows]

from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import StrategySpec, StrategyStatus


class InvalidStrategyError(ValueError):
    pass


class ActiveStrategyImmutableError(ValueError):
    pass


class StrategyRegistry:
    """Persists `StrategySpec` versions. Rule changes to a strategy that is
    already `paper_testing` must go through `strategies.versioning.new_version`
    rather than overwriting the active record in place (rule 61)."""

    def __init__(self, database: Database):
        self.database = database

    async def create(self, spec: StrategySpec) -> StrategySpec:
        problems = spec.validate_structure()
        if problems:
            raise InvalidStrategyError("; ".join(problems))
        existing = await self.get(spec.name, spec.version)
        if existing is not None and existing.status == StrategyStatus.PAPER_TESTING:
            raise ActiveStrategyImmutableError(
                f"{spec.name} v{spec.version} is actively paper-testing; use strategies.versioning.new_version() instead of overwriting it"
            )
        connection = self.database.require_connection()
        now = datetime.now(timezone.utc).isoformat()
        await connection.execute(
            """INSERT INTO strategies(id, name, version, status, strategy_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name, version) DO UPDATE SET
               status=excluded.status, strategy_json=excluded.strategy_json, updated_at=excluded.updated_at""",
            (spec.id, spec.name, spec.version, spec.status.value, spec.model_dump_json(), spec.created_at.isoformat(), now),
        )
        await connection.commit()
        return spec

    async def get(self, name: str, version: str) -> StrategySpec | None:
        connection = self.database.require_connection()
        row = await (await connection.execute(
            "SELECT strategy_json FROM strategies WHERE name = ? AND version = ?", (name, version)
        )).fetchone()
        return StrategySpec.model_validate_json(row["strategy_json"]) if row else None

    async def list_versions(self, name: str) -> list[StrategySpec]:
        connection = self.database.require_connection()
        rows = await (await connection.execute(
            "SELECT strategy_json FROM strategies WHERE name = ? ORDER BY created_at DESC", (name,)
        )).fetchall()
        return [StrategySpec.model_validate_json(row["strategy_json"]) for row in rows]

    async def list_all(self) -> list[StrategySpec]:
        connection = self.database.require_connection()
        rows = await (await connection.execute("SELECT strategy_json FROM strategies ORDER BY updated_at DESC")).fetchall()
        return [StrategySpec.model_validate_json(row["strategy_json"]) for row in rows]

    async def latest(self, name: str) -> StrategySpec | None:
        versions = await self.list_versions(name)
        return versions[0] if versions else None

    async def set_status(self, name: str, version: str, status: StrategyStatus) -> StrategySpec:
        """Status-only transition (pause/retire/promote) — never touches
        entry/exit rules, so it is exempt from the rule-change immutability
        guard in `create()`."""
        spec = await self.get(name, version)
        if spec is None:
            raise KeyError(f"{name} v{version}")
        spec.status = status
        return await self._force_save(spec)

    async def _force_save(self, spec: StrategySpec) -> StrategySpec:
        connection = self.database.require_connection()
        now = datetime.now(timezone.utc).isoformat()
        await connection.execute(
            "UPDATE strategies SET status = ?, strategy_json = ?, updated_at = ? WHERE name = ? AND version = ?",
            (spec.status.value, spec.model_dump_json(), now, spec.name, spec.version),
        )
        await connection.commit()
        return spec

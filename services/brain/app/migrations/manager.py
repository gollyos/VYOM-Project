from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]
    validation_query: str            # must return a truthy value after upgrade
    validation_expected: tuple = ()

    def validate(self, connection) -> bool:
        cursor = connection.execute(self.validation_query)
        row = cursor.fetchone()
        return row is not None and tuple(row) == self.validation_expected if self.validation_expected else row is not None


class MigrationError(Exception):
    pass


class MigrationManager:
    """Versioned database migrations. The production schema is never
    mutated ad hoc: every change is a Migration with an upgrade and a
    validation, applied inside a transaction, recorded in
    `schema_migrations`. A failed migration marks startup degraded —
    the Brain never continues pretending the database is healthy."""

    BASELINE = Migration(
        version=1,
        name="baseline_schema_v0",
        statements=(),  # baseline: the CREATE TABLE IF NOT EXISTS schema already applied by Database.connect
        validation_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('tasks','memories','automations','nodes','sync_journal')",
        validation_expected=(5,),
    )

    ADAPTIVE = Migration(
        version=2,
        name="adaptive_tables_v1",
        statements=(
            """CREATE TABLE IF NOT EXISTS experiences (
                experience_id TEXT PRIMARY KEY, task_id TEXT, domain TEXT NOT NULL,
                task_type TEXT NOT NULL, success INTEGER NOT NULL, failure_signature TEXT,
                strategy_id TEXT, experience_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_experiences_domain ON experiences(domain, success)",
            """CREATE TABLE IF NOT EXISTS adaptive_strategies (
                strategy_id TEXT PRIMARY KEY, domain TEXT NOT NULL, name TEXT NOT NULL,
                version TEXT NOT NULL, status TEXT NOT NULL, strategy_json TEXT NOT NULL,
                updated_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_adaptive_strategies_domain ON adaptive_strategies(domain, status)",
            """CREATE TABLE IF NOT EXISTS environment_changes (
                change_id TEXT PRIMARY KEY, dimension TEXT NOT NULL, old_value TEXT,
                new_value TEXT, detected_at TEXT NOT NULL, change_json TEXT NOT NULL)""",
        ),
        validation_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('experiences','adaptive_strategies','environment_changes')",
        validation_expected=(3,),
    )

    def __init__(self, database, migrations: list[Migration] | None = None):
        self.database = database
        self.migrations = sorted(migrations or [self.BASELINE, self.ADAPTIVE], key=lambda item: item.version)
        self.last_error: str | None = None

    async def ensure_table(self) -> None:
        connection = self.database.require_connection()
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        await connection.commit()

    async def applied_versions(self) -> list[int]:
        await self.ensure_table()
        connection = self.database.require_connection()
        cursor = await connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        return [int(row["version"]) for row in await cursor.fetchall()]

    async def apply_pending(self) -> dict:
        applied = await self.applied_versions()
        results = {"applied": [], "already_applied": applied, "failed": None}
        connection = self.database.require_connection()
        for migration in self.migrations:
            if migration.version in applied:
                continue
            try:
                for statement in migration.statements:
                    await connection.execute(statement)
                await connection.commit()
                if not self._validate_sync(migration):
                    raise MigrationError(f"Migration v{migration.version} ({migration.name}) failed its validation query")
                await connection.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, datetime.now(timezone.utc).isoformat()),
                )
                await connection.commit()
                results["applied"].append({"version": migration.version, "name": migration.name})
            except Exception as error:
                await connection.rollback()
                self.last_error = str(error)
                results["failed"] = {"version": migration.version, "name": migration.name, "error": str(error)}
                break
        return results

    def _validate_sync(self, migration: Migration) -> bool:
        import sqlite3

        connection = sqlite3.connect(self.database.path)
        try:
            cursor = connection.execute(migration.validation_query)
            row = cursor.fetchone()
            if migration.validation_expected:
                return tuple(row) == migration.validation_expected
            return row is not None
        finally:
            connection.close()

    async def status(self) -> dict:
        applied = await self.applied_versions()
        pending = [m.version for m in self.migrations if m.version not in applied]
        return {
            "current_version": max(applied) if applied else 0,
            "latest_version": self.migrations[-1].version,
            "pending": pending,
            "last_error": self.last_error,
        }

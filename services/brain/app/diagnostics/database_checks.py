from __future__ import annotations

import sqlite3

from .system_checks import CheckResult


class DatabaseChecks:
    def __init__(self, database_path):
        self.database_path = database_path

    def integrity(self) -> CheckResult:
        if not self.database_path.exists():
            return CheckResult("database", "FAIL", f"Database file {self.database_path} does not exist")
        connection = sqlite3.connect(self.database_path)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            result = row[0] if row else "unknown"
            if result == "ok":
                return CheckResult("database", "PASS", "SQLite integrity check passed")
            return CheckResult("database", "FAIL", f"Integrity check reported: {result}")
        except sqlite3.DatabaseError as error:
            return CheckResult("database", "FAIL", f"Database error: {error}")
        finally:
            connection.close()

    async def migration_state(self, migrations_manager) -> CheckResult:
        try:
            state = await migrations_manager.status()
        except Exception as error:
            return CheckResult("database_migrations", "FAIL", f"Cannot read migration state: {error}")
        pending = state.get("pending", [])
        if pending:
            return CheckResult("database_migrations", "WARNING", f"{len(pending)} pending migration(s)", {"pending": pending})
        return CheckResult(
            "database_migrations", "PASS",
            f"Schema at version {state.get('current_version', state.get('current'))}",
        )

    async def run_all(self, migrations_manager=None) -> list[CheckResult]:
        results = [self.integrity()]
        if migrations_manager is not None:
            results.append(await self.migration_state(migrations_manager))
        return results

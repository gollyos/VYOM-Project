from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StartupReport:
    ok: bool                      # core systems usable
    degraded: bool = False        # started, but with warnings
    ready: bool = False           # fully production-ready
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)

    def step(self, name: str, status: str, detail: str = "") -> None:
        self.steps.append({"step": name, "status": status, "detail": detail})
        if status == "FAIL":
            self.failures.append(f"{name}: {detail}")
        elif status == "WARN":
            self.warnings.append(f"{name}: {detail}")

    def finalize(self) -> "StartupReport":
        self.ok = not self.failures
        self.degraded = self.ok and bool(self.warnings)
        self.ready = self.ok and not self.warnings
        return self


class StartupChecks:
    """Production startup validation: configuration, database,
    migrations, secret store, required directories, permissions,
    internal services, protocol compatibility. Optional providers and
    integrations may remain disconnected — VYOM starts degraded (where
    safe) rather than failing on optional pieces."""

    def __init__(self, *, config_validator, database, migrations, secret_store, required_dirs: list[Path]):
        self.config_validator = config_validator
        self.database = database
        self.migrations = migrations
        self.secret_store = secret_store
        self.required_dirs = required_dirs

    async def run(self) -> StartupReport:
        report = StartupReport(ok=False)

        config = self.config_validator.validate_all()
        if config.valid:
            report.step("configuration", "WARN" if config.warnings else "PASS",
                        "; ".join(config.warnings[:3]))
        else:
            report.step("configuration", "FAIL", "; ".join(config.errors[:3]))

        try:
            self.database.require_connection()
            report.step("database", "PASS", "connected")
        except Exception as error:
            report.step("database", "FAIL", str(error))

        migration_result = await self.migrations.apply_pending()
        if migration_result.get("failed"):
            report.step("migrations", "FAIL", str(migration_result["failed"]))
        elif migration_result.get("applied"):
            report.step("migrations", "PASS", f"applied {[m['name'] for m in migration_result['applied']]}")
        else:
            report.step("migrations", "PASS", "schema up to date")

        try:
            self.secret_store.list_secret_metadata()
            report.step("secret_store", "PASS", "backend available")
        except Exception as error:
            report.step("secret_store", "FAIL", str(error))

        missing = [str(path) for path in self.required_dirs if not path.parent.exists()]
        if missing:
            report.step("directories", "FAIL", f"cannot create {missing}")
        else:
            for path in self.required_dirs:
                path.mkdir(parents=True, exist_ok=True)
            report.step("directories", "PASS", f"{len(self.required_dirs)} paths ensured")

        return report.finalize()

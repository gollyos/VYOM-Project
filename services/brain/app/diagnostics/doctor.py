from __future__ import annotations

import time

from .repair_advisor import RepairAdvisor
from .system_checks import CheckResult


class VYOMDoctor:
    """The real diagnostic command: "VYOM, run diagnostics." Runs every
    check layer and reports PASS / WARNING / FAIL with actionable
    explanations and issue-specific repair recommendations.

    Automatic repair is limited to safe deterministic fixes (stale temp
    files, recoverable caches, dead managed processes). Doctor never
    changes security permissions, deletes user data, rotates
    credentials, touches the firewall, or reinstalls software."""

    SAFE_REPAIRS = ("clean_temp", "create_directories")

    def __init__(
        self,
        system_checks,
        database_checks,
        provider_checks,
        tool_checks,
        integration_checks,
        extra_checks: dict[str, object] | None = None,
    ):
        self.system_checks = system_checks
        self.database_checks = database_checks
        self.provider_checks = provider_checks
        self.tool_checks = tool_checks
        self.integration_checks = integration_checks
        self.extra_checks = extra_checks or {}  # name -> async callable() -> CheckResult
        self.advisor = RepairAdvisor()

    async def run(self, *, repair: bool = False) -> dict:
        started = time.perf_counter()
        checks: list[CheckResult] = []
        checks.extend(self.system_checks.run_all())
        checks.extend(await self.database_checks.run_all(getattr(self, "migrations", None)))
        checks.extend(await self.provider_checks.run_all())
        checks.extend(await self.tool_checks.run_all())
        checks.extend(self.integration_checks.run_all())
        for name, check_callable in self.extra_checks.items():
            try:
                result = check_callable()
                if hasattr(result, "__await__"):
                    result = await result
                checks.append(result if isinstance(result, CheckResult) else CheckResult(name, "WARNING", str(result)))
            except Exception as error:
                checks.append(CheckResult(name, "WARNING", f"Check could not run: {error}"))

        applied_repairs: list[str] = []
        if repair:
            applied_repairs = self.apply_safe_repairs(checks)

        entries = [check.as_dict() for check in checks]
        counts = {
            status: sum(1 for check in entries if check["status"] == status)
            for status in ("PASS", "WARNING", "FAIL")
        }
        overall = "FAIL" if counts["FAIL"] else ("WARNING" if counts["WARNING"] else "PASS")
        return {
            "overall": overall,
            "counts": counts,
            "checks": entries,
            "recommendations": self.advisor.recommend(entries),
            "applied_repairs": applied_repairs,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def apply_safe_repairs(self, checks: list[CheckResult]) -> list[str]:
        applied: list[str] = []
        for check in checks:
            if check.name == "temp_artifacts" and check.status == "WARNING":
                temp_root = check.evidence.get("temp_root")
                if temp_root:
                    import shutil
                    from pathlib import Path

                    shutil.rmtree(Path(temp_root), ignore_errors=True)
                    applied.append("clean_temp")
        return applied

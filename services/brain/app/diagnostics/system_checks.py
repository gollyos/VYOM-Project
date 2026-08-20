from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path


class CheckResult:
    def __init__(self, name: str, status: str, explanation: str, evidence: dict | None = None):
        self.name = name
        self.status = status  # PASS | WARNING | FAIL
        self.explanation = explanation
        self.evidence = evidence or {}

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "explanation": self.explanation, "evidence": self.evidence}


class SystemChecks:
    """Machine-level checks: Python, disk space, data directories,
    filesystem writability, temp-file hygiene."""

    def __init__(self, required_dirs: list[Path], min_free_mb: int = 512):
        self.required_dirs = required_dirs
        self.min_free_mb = min_free_mb

    def python_runtime(self) -> CheckResult:
        return CheckResult("python_runtime", "PASS", f"Python {sys.version.split()[0]} on {sys.platform}")

    def disk_space(self) -> CheckResult:
        if not self.required_dirs:
            return CheckResult("disk_space", "WARNING", "No data directories configured")
        root = self.required_dirs[0]
        if not root.exists():
            return CheckResult("disk_space", "FAIL", f"Data root {root} does not exist")
        usage = shutil.disk_usage(root)
        free_mb = usage.free // (1024 * 1024)
        if free_mb < self.min_free_mb:
            return CheckResult("disk_space", "FAIL", f"Only {free_mb} MB free (need {self.min_free_mb} MB)")
        if free_mb < self.min_free_mb * 4:
            return CheckResult("disk_space", "WARNING", f"{free_mb} MB free is getting low")
        return CheckResult("disk_space", "PASS", f"{free_mb} MB free on {root.anchor}")

    def directories(self) -> CheckResult:
        missing = [str(path) for path in self.required_dirs if not path.exists()]
        if missing:
            return CheckResult("data_directories", "FAIL", f"Missing directories: {missing}")
        return CheckResult("data_directories", "PASS", f"{len(self.required_dirs)} required directories present")

    def filesystem_writable(self) -> CheckResult:
        probe = Path(tempfile.gettempdir()) / f"vyom-doctor-{time.time_ns()}.tmp"
        try:
            probe.write_text("probe", encoding="utf-8")
            probe.unlink()
            return CheckResult("filesystem_writable", "PASS", "Temp write probe succeeded")
        except Exception as error:
            return CheckResult("filesystem_writable", "FAIL", f"Cannot write temp files: {error}")

    def temp_artifacts(self, temp_root: Path, max_age_hours: float = 72) -> CheckResult:
        if not temp_root.exists():
            return CheckResult("temp_artifacts", "PASS", "No temp directory to inspect")
        stale_cutoff = time.time() - max_age_hours * 3600
        stale = [item for item in temp_root.rglob("*") if item.is_file() and item.stat().st_mtime < stale_cutoff]
        if stale:
            return CheckResult(
                "temp_artifacts", "WARNING",
                f"{len(stale)} stale temporary files older than {max_age_hours}h (safe cleanup available)",
                {"sample": [str(item) for item in stale[:5]]},
            )
        return CheckResult("temp_artifacts", "PASS", "No stale temporary artifacts")

    def run_all(self) -> list[CheckResult]:
        return [self.python_runtime(), self.disk_space(), self.directories(), self.filesystem_writable()]

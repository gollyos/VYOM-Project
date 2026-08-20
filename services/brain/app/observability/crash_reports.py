from __future__ import annotations

import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..security.redaction import redact_mapping, redact_value


class CrashReporter:
    """Local crash diagnostics: version, OS, redacted stack trace,
    recent safe events, request/task IDs, component health. Secrets and
    raw sensitive user data are redacted before the file is written.
    External upload is opt-in only (and not implemented — by design)."""

    def __init__(self, reports_dir: Path, *, app_version: str, service_version: str, retention: int = 20):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.app_version = app_version
        self.service_version = service_version
        self.retention = retention

    def capture(
        self, error: BaseException, *, recent_events: list[dict] | None = None,
        health: dict | None = None, correlation: dict | None = None, context: dict | None = None,
    ) -> Path:
        report = {
            "report_id": f"crash_{uuid4().hex[:12]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "app_version": self.app_version,
            "service_version": self.service_version,
            "python": sys.version.split()[0],
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "error_type": type(error).__name__,
            "error": redact_value(str(error)),
            "stack": redact_value("".join(traceback.format_exception(type(error), error, error.__traceback__))),
            "recent_events": redact_mapping({"events": recent_events or []})["events"],
            "component_health": health or {},
            "correlation": redact_mapping(correlation or {}),
            "context": redact_mapping(context or {}),
            "upload": "opt-in-only; not enabled",
        }
        path = self.reports_dir / f"{report['report_id']}.json"
        path.write_text(
            __import__("json").dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self._apply_retention()
        return path

    def _apply_retention(self) -> None:
        reports = sorted(self.reports_dir.glob("crash_*.json"))
        for stale in reports[: max(0, len(reports) - self.retention)]:
            stale.unlink(missing_ok=True)

    def list_reports(self) -> list[dict]:
        import json

        results = []
        for path in sorted(self.reports_dir.glob("crash_*.json"), reverse=True):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                results.append({
                    "report_id": report.get("report_id"),
                    "timestamp": report.get("timestamp"),
                    "error_type": report.get("error_type"),
                    "app_version": report.get("app_version"),
                })
            except Exception:
                continue
        return results

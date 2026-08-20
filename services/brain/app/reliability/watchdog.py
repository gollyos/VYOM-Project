from __future__ import annotations

from dataclasses import dataclass

from app.devices.schemas import utc_now

from .health import ReliabilityMetrics


@dataclass
class WatchdogConfig:
    stall_seconds: float = 300.0           # no progress event for this long
    max_recovery_attempts: int = 3         # bounded: never restart endlessly
    repeated_failure_threshold: int = 3


class StuckTaskReport:
    def __init__(self, task_id: str, signals: list[str]):
        self.task_id = task_id
        self.signals = signals


class Watchdog:
    """Detects stuck work from real signals only: no progress event
    within the stall window, an expired lease, or repeated identical
    failures. Responses are bounded — after max_recovery_attempts the
    task is paused and the user is notified instead of looping."""

    def __init__(
        self,
        config: WatchdogConfig | None = None,
        metrics: ReliabilityMetrics | None = None,
    ):
        self.config = config or WatchdogConfig()
        self.metrics = metrics
        self.recovery_attempts: dict[str, int] = {}

    def detect_stalled(self, progress: dict[str, object], now=None) -> StuckTaskReport | None:
        """`progress` maps task_id -> last progress timestamp or None
        while the task is still in an active state."""
        now = now or utc_now()
        stalled: list[StuckTaskReport] = []
        for task_id, last_progress in progress.items():
            if last_progress is None:
                continue
            age = (now - last_progress).total_seconds()
            if age > self.config.stall_seconds:
                stalled.append(StuckTaskReport(task_id, [f"no progress event for {int(age)}s"]))
        return stalled[0] if stalled else None

    def detect_repeated_failures(self, failures: dict[str, list[str]]) -> StuckTaskReport | None:
        for task_id, errors in failures.items():
            if len(errors) >= self.config.repeated_failure_threshold and len(set(errors)) == 1:
                return StuckTaskReport(task_id, [f"identical failure repeated {len(errors)} times: {errors[0]}"])
        return None

    def decide(self, report: StuckTaskReport) -> str:
        """inspect -> bounded retry -> pause + notify. Returns the
        action: retry while attempts remain, pause afterwards."""
        attempts = self.recovery_attempts.get(report.task_id, 0)
        if attempts >= self.config.max_recovery_attempts:
            return "pause_and_notify"
        self.recovery_attempts[report.task_id] = attempts + 1
        if self.metrics is not None:
            self.metrics.record_recovery()
        return "retry"

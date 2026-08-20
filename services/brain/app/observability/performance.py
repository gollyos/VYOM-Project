from __future__ import annotations

from dataclasses import dataclass

from .metrics import MetricsRegistry


@dataclass
class PerformanceBudgets:
    """Configurable alpha performance budgets (milliseconds). Measured
    honestly; never reported as passing without measurement."""

    brain_health_ms: float = 250.0
    command_latency_ms: float = 800.0
    task_planning_ms: float = 1500.0
    tool_latency_ms: float = 5000.0
    model_latency_ms: float = 30000.0
    memory_retrieval_ms: float = 300.0
    websocket_reconnect_ms: float = 3000.0
    desktop_startup_ms: float = 5000.0

    @classmethod
    def from_config(cls, config: dict) -> "PerformanceBudgets":
        section = config.get("performance_budgets") or {}
        defaults = cls()
        return cls(**{
            field: float(section.get(field, getattr(defaults, field)))
            for field in defaults.__dataclass_fields__
        })


class PerformanceMonitor:
    """Records real timings against budgets and reports breaches with
    evidence (metric name, measured value, budget)."""

    def __init__(self, metrics: MetricsRegistry, budgets: PerformanceBudgets | None = None):
        self.metrics = metrics
        self.budgets = budgets or PerformanceBudgets()

    def record(self, name: str, elapsed_ms: float, **labels) -> dict:
        self.metrics.observe(name, elapsed_ms, **labels)
        budget = getattr(self.budgets, f"{name}_ms", None)
        entry = {"metric": name, "measured_ms": round(elapsed_ms, 1)}
        if budget is not None:
            entry["budget_ms"] = budget
            entry["within_budget"] = elapsed_ms <= budget
        return entry

    def budget_report(self) -> list[dict]:
        snapshots = self.metrics.snapshot()["histograms"]
        report = []
        for field_name in self.budgets.__dataclass_fields__:
            metric = field_name[: -len("_ms")] if field_name.endswith("_ms") else field_name
            histogram = snapshots.get(metric)
            if not histogram:
                continue
            budget = getattr(self.budgets, field_name)
            report.append({
                "metric": metric,
                "budget_ms": budget,
                "p95_ms": histogram["p95"],
                "within_budget": histogram["p95"] <= budget,
            })
        return report

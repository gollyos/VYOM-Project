from __future__ import annotations

import threading
import time
from collections import defaultdict


class MetricsRegistry:
    """Lightweight in-process metrics: counters, gauges, and
    histograms. No external dependency; for monitoring and diagnostics,
    never a permanent UI."""

    def __init__(self):
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self.max_samples = 500

    def increment(self, name: str, value: float = 1, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    def gauge(self, name: str, value: float, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def observe(self, name: str, value: float, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            samples = self._histograms[key]
            samples.append(value)
            if len(samples) > self.max_samples:
                del samples[: len(samples) - self.max_samples]

    def timing(self, name: str, **labels):
        start = time.perf_counter()

        class _Timer:
            def __enter__(_self):
                return _self

            def __exit__(_self, *exc):
                elapsed_ms = (time.perf_counter() - start) * 1000
                self.observe(name, elapsed_ms, **labels)
                return False

        return _Timer()

    @staticmethod
    def _key(name: str, labels: dict) -> str:
        if not labels:
            return name
        label_text = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_text}}}"

    @staticmethod
    def _percentile(values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(int(len(ordered) * fraction), len(ordered) - 1)
        return ordered[index]

    def snapshot(self) -> dict:
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            histograms = {
                key: {
                    "count": len(values),
                    "avg": round(sum(values) / len(values), 2) if values else 0.0,
                    "p50": round(self._percentile(values, 0.50), 2),
                    "p95": round(self._percentile(values, 0.95), 2),
                    "max": round(max(values), 2) if values else 0.0,
                }
                for key, values in self._histograms.items()
            }
        return {"counters": counters, "gauges": gauges, "histograms": histograms}

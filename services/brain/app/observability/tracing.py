from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Span:
    span_id: str = field(default_factory=lambda: uuid4().hex[:12])
    name: str = ""
    parent_id: str | None = None
    started_at: float = field(default_factory=time.perf_counter)
    duration_ms: float = 0.0
    attributes: dict = field(default_factory=dict)
    status: str = "ok"  # ok | error

    def finish(self, status: str = "ok") -> None:
        self.duration_ms = round((time.perf_counter() - self.started_at) * 1000, 2)
        self.status = status


class Tracer:
    """Distributed-tracing foundation: in-memory span trees with an
    optional JSONL exporter. Spans attach to the correlation trace ID
    so a failure can be traced Brain -> task -> tool without exposing
    any hidden reasoning (only names/timings/status are recorded)."""

    def __init__(self, max_spans: int = 1000, export_path=None):
        self.max_spans = max_spans
        self.spans: list[Span] = []
        self.export_path = export_path

    @contextmanager
    def span(self, name: str, parent: Span | None = None, **attributes):
        current = Span(name=name, parent_id=parent.span_id if parent else None, attributes=attributes)
        self._record(current)
        try:
            yield current
            current.finish("ok")
        except Exception as error:
            current.finish("error")
            current.attributes["error"] = type(error).__name__
            raise
        finally:
            self._export(current)

    def _record(self, span: Span) -> None:
        self.spans.append(span)
        if len(self.spans) > self.max_spans:
            del self.spans[: len(self.spans) - self.max_spans]

    def _export(self, span: Span) -> None:
        if self.export_path is None:
            return
        import json

        from ..security.redaction import redact_mapping

        record = {
            "span_id": span.span_id, "name": span.name, "parent_id": span.parent_id,
            "duration_ms": span.duration_ms, "status": span.status,
            "attributes": redact_mapping(span.attributes),
        }
        with open(self.export_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def recent(self, limit: int = 50) -> list[dict]:
        return [
            {"span_id": s.span_id, "name": s.name, "parent_id": s.parent_id,
             "duration_ms": s.duration_ms, "status": s.status}
            for s in self.spans[-limit:]
        ]

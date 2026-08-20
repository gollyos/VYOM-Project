from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from uuid import uuid4

# Correlation context: every external request gets a request/trace ID
# propagated through Brain -> task -> agent -> tool -> evidence.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("vyom_request_id", default="")
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("vyom_trace_id", default="")
task_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("vyom_task_id", default="")


def new_request_id() -> str:
    return f"req_{uuid4().hex[:16]}"


def new_trace_id() -> str:
    return f"trace_{uuid4().hex[:16]}"


@dataclass
class CorrelationContext:
    request_id: str = field(default_factory=new_request_id)
    trace_id: str = field(default_factory=new_trace_id)
    task_id: str = ""

    def as_fields(self) -> dict[str, str]:
        fields = {"request_id": self.request_id, "trace_id": self.trace_id}
        if self.task_id:
            fields["task_id"] = self.task_id
        return fields


def bind_request(request_id: str | None = None, trace_id: str | None = None) -> CorrelationContext:
    context = CorrelationContext(
        request_id=request_id or new_request_id(),
        trace_id=trace_id or new_trace_id(),
    )
    request_id_var.set(context.request_id)
    trace_id_var.set(context.trace_id)
    return context


def bind_task(task_id: str) -> None:
    task_id_var.set(task_id)


def current() -> CorrelationContext:
    return CorrelationContext(
        request_id=request_id_var.get() or new_request_id(),
        trace_id=trace_id_var.get() or new_trace_id(),
        task_id=task_id_var.get(),
    )

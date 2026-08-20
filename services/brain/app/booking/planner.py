from __future__ import annotations

from .schemas import BookingCategory, BookingConstraints, BookingRequest


class BookingPlanner:
    """Understand requirement -> retrieve preferences -> build a bounded
    BookingRequest. Architecture-first: category coverage is deliberately
    limited (see docs/BOOKING_POLICY.md)."""

    def plan(
        self,
        category: BookingCategory,
        constraints: BookingConstraints,
        *,
        task_id: str | None = None,
        remembered_preferences: list[str] | None = None,
    ) -> BookingRequest:
        merged_preferences = list(dict.fromkeys([*constraints.preferences, *(remembered_preferences or [])]))
        resolved_constraints = constraints.model_copy(update={"preferences": merged_preferences})
        request = BookingRequest(category=category, constraints=resolved_constraints, requested_by_task=task_id)
        request.idempotency_key = request.compute_idempotency_key()
        return request

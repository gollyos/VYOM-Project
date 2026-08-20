from __future__ import annotations

from typing import Any

from .schemas import BookingRequest, BookingStatus


class BookingConfirmation:
    """Normalizes a raw provider reservation response onto the booking
    request. A click alone is never treated as confirmation; a missing
    confirmation_id keeps the booking FAILED, not RESERVED."""

    @staticmethod
    def apply(request: BookingRequest, provider_response: dict[str, Any]) -> BookingRequest:
        confirmation_id = provider_response.get("confirmation_id")
        request.confirmation_id = confirmation_id
        request.final_price = provider_response.get("price", request.final_price)
        request.confirmation_email_evidence = provider_response.get("email_message_id")
        request.status = BookingStatus.RESERVED if confirmation_id else BookingStatus.FAILED
        return request

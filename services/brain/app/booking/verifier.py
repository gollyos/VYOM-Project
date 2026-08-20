from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import BookingOption, BookingRequest, BookingStatus


@dataclass
class BookingVerificationReport:
    verified: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


class BookingVerifier:
    """A click on 'Book' is not completion. Only a confirmation ID with
    date/time, provider, and final price (when applicable) marks the
    booking VERIFIED."""

    def verify(self, request: BookingRequest, selected_option: BookingOption | None) -> BookingVerificationReport:
        checks = {
            "has_confirmation_id": bool(request.confirmation_id),
            "has_date_or_time": bool(request.constraints.date or request.constraints.time),
            "has_provider": bool(selected_option and selected_option.provider),
            "has_final_price_if_applicable": (
                request.final_price is not None or selected_option is None or selected_option.price is None
            ),
        }
        verified = all(checks.values())
        if verified:
            request.status = BookingStatus.CONFIRMED
        return BookingVerificationReport(verified=verified, checks=checks, reasons=[key for key, ok in checks.items() if not ok])

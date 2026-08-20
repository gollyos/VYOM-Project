from __future__ import annotations

from .confirmation import BookingConfirmation
from .schemas import BookingOption, BookingRequest, BookingStatus
from .search import BookingSearchService
from .store import BookingStore


class DuplicateBookingError(Exception):
    pass


class BookingReservationService:
    """Reserve/pay boundary. Callers are expected to have already applied
    the L2 (reserve no-cost slot) / L3 (payment) approval decision through
    the Permission Engine before calling reserve(); this service still
    independently refuses to create a second reservation for an equivalent
    request (see docs/BOOKING_POLICY.md, item 62)."""

    def __init__(self, search_service: BookingSearchService, store: BookingStore):
        self.search_service = search_service
        self.store = store

    async def reserve(self, request: BookingRequest, option: BookingOption) -> BookingRequest:
        existing = await self.store.find_by_idempotency_key(request.idempotency_key)
        if existing and existing.status in {BookingStatus.RESERVED, BookingStatus.CONFIRMED}:
            raise DuplicateBookingError(f"An equivalent booking already exists: {existing.id} ({existing.status.value})")

        provider = self.search_service.provider_for(request.category.value)
        provider_response = await provider.reserve(option, request.constraints)

        request.options = request.options or [option]
        request.selected_option_id = option.option_id
        request = BookingConfirmation.apply(request, provider_response)
        await self.store.save(request)
        return request

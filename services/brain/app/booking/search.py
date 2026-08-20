from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .schemas import BookingConstraints, BookingOption


class BookingProvider(ABC):
    category: str = "unknown"

    @abstractmethod
    async def health(self) -> tuple[bool, str | None]: ...

    @abstractmethod
    async def search(self, constraints: BookingConstraints) -> list[BookingOption]: ...

    @abstractmethod
    async def reserve(self, option: BookingOption, constraints: BookingConstraints) -> dict[str, Any]: ...


class DisconnectedBookingProvider(BookingProvider):
    """Honest default: no live booking provider is configured for this
    category."""

    category = "disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "No booking provider is configured for this category"

    async def search(self, constraints: BookingConstraints) -> list[BookingOption]:
        raise RuntimeError("No booking provider is configured for this category")

    async def reserve(self, option: BookingOption, constraints: BookingConstraints) -> dict[str, Any]:
        raise RuntimeError("No booking provider is configured for this category")


class MockBookingProvider(BookingProvider):
    """Deterministic fixture provider for demos/tests. Every option is
    labeled test-fixture and never represents a real reservation."""

    category = "test-fixture"

    def __init__(self, options: list[BookingOption] | None = None):
        self._options = options

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    async def search(self, constraints: BookingConstraints) -> list[BookingOption]:
        if self._options is not None:
            return list(self._options)
        base_price = constraints.budget or 50.0
        results: list[BookingOption] = []
        for index in range(1, 4):
            rating = round(3.5 + index * 0.3, 1)
            matches = constraints.minimum_rating is None or rating >= constraints.minimum_rating
            relaxed = [] if matches else ["minimum_rating"]
            results.append(BookingOption(
                provider="test-fixture",
                name=f"Fixture Option {index}",
                price=round(base_price * (0.8 + index * 0.15), 2),
                currency="USD",
                matches_constraints=matches,
                relaxed_constraints=relaxed,
                rating=rating,
                availability="available",
                details={"party_size": constraints.party_size or 2, "source": "test-fixture"},
            ))
        return results

    async def reserve(self, option: BookingOption, constraints: BookingConstraints) -> dict[str, Any]:
        return {
            "confirmation_id": f"FIX-{option.option_id[-8:].upper()}",
            "provider": option.provider,
            "status": "confirmed",
            "price": option.price,
            "email_message_id": None,
        }


class BookingSearchService:
    def __init__(self, providers: dict[str, BookingProvider] | None = None):
        self.providers = providers or {}

    def provider_for(self, category: str) -> BookingProvider:
        return self.providers.get(category, DisconnectedBookingProvider())

    async def search(self, category: str, constraints: BookingConstraints) -> list[BookingOption]:
        provider = self.provider_for(category)
        healthy, error = await provider.health()
        if not healthy:
            raise RuntimeError(error or f"No booking provider is configured for {category}")
        return await provider.search(constraints)

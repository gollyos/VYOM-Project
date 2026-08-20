from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BookingCategory(str, Enum):
    RESTAURANT = "restaurant"
    APPOINTMENT = "appointment"
    MEETING = "meeting"
    HOTEL = "hotel"
    TRAVEL_RESEARCH = "travel-research"
    SERVICE_BOOKING = "service-booking"


class BookingStatus(str, Enum):
    DRAFT = "draft"
    SEARCHING = "searching"
    OPTIONS_READY = "options_ready"
    AWAITING_APPROVAL = "awaiting_approval"
    RESERVING = "reserving"
    RESERVED = "reserved"
    PAYMENT_REQUIRED = "payment_required"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BookingConstraints(BaseModel):
    date: str | None = None
    time: str | None = None
    location: str | None = None
    budget: float | None = None
    party_size: int | None = None
    preferences: list[str] = Field(default_factory=list)
    cancellation_policy: str | None = None
    distance_km: float | None = None
    minimum_rating: float | None = None


class BookingOption(BaseModel):
    option_id: str = Field(default_factory=lambda: f"opt_{uuid4().hex}")
    provider: str
    name: str
    price: float | None = None
    currency: str = "USD"
    matches_constraints: bool = True
    relaxed_constraints: list[str] = Field(default_factory=list)
    rating: float | None = None
    availability: str = "unknown"
    details: dict = Field(default_factory=dict)


class BookingRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"booking_{uuid4().hex}")
    category: BookingCategory
    constraints: BookingConstraints
    requested_by_task: str | None = None
    status: BookingStatus = BookingStatus.DRAFT
    options: list[BookingOption] = Field(default_factory=list)
    selected_option_id: str | None = None
    confirmation_id: str | None = None
    confirmation_email_evidence: str | None = None
    final_price: float | None = None
    idempotency_key: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def compute_idempotency_key(self) -> str:
        raw = f"{self.category.value}|{self.constraints.model_dump_json()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def selected_option(self) -> BookingOption | None:
        return next((option for option in self.options if option.option_id == self.selected_option_id), None)

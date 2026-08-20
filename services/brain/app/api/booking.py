from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.booking.comparator import BookingComparator
from app.booking.schemas import BookingCategory, BookingConstraints, BookingOption

router = APIRouter(prefix="/api/booking", tags=["booking"])


@router.post("/search", response_model=list[BookingOption])
async def search(category: BookingCategory, constraints: BookingConstraints, request: Request) -> list[BookingOption]:
    try:
        options = await request.app.state.booking_search_service.search(category.value, constraints)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return BookingComparator().rank(options, constraints)

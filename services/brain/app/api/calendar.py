from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.calendar.schemas import AvailabilityRequest, AvailabilitySlot, CalendarReceipt, CreateEventRequest
from app.schemas.approvals import PermissionLevel


router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.post("/availability", response_model=list[AvailabilitySlot])
async def availability(payload: AvailabilityRequest, request: Request) -> list[AvailabilitySlot]:
    try:
        return await request.app.state.calendar_service.availability(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/events", response_model=CalendarReceipt)
async def create_event(payload: CreateEventRequest, request: Request, approval_task_id: str | None = None) -> CalendarReceipt:
    task = await request.app.state.task_store.get(approval_task_id) if approval_task_id else None
    if task is None or not task.approval_granted or task.permission_level != PermissionLevel.L2 or payload.title.casefold() not in task.user_request.casefold():
        raise HTTPException(status_code=403, detail="A scoped L2 meeting approval is required")
    try:
        return await request.app.state.calendar_service.create(payload, approval_granted=True)
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

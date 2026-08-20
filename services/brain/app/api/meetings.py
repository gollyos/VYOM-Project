from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.meetings.schemas import FollowUpDraft, MeetingBriefing, MeetingNotes


router = APIRouter(prefix="/api/meetings", tags=["meetings"])


@router.get("/briefings", response_model=list[MeetingBriefing])
async def briefing(request: Request, hours: int = 24) -> list[MeetingBriefing]:
    try:
        return await request.app.state.meeting_service.upcoming_briefings(min(max(hours, 1), 168))
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/notes", response_model=MeetingNotes)
async def save_notes(payload: MeetingNotes, request: Request) -> MeetingNotes:
    return await request.app.state.meeting_service.save_notes(payload)


@router.post("/{event_id}/follow-up", response_model=FollowUpDraft)
async def follow_up(event_id: str, recipients: list[str], request: Request) -> FollowUpDraft:
    try:
        return await request.app.state.meeting_service.prepare_follow_up(event_id, recipients)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Meeting notes not found") from error

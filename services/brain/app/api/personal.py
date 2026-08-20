from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.personal.schemas import Commitment, CommitmentSource, PersonalProfile

router = APIRouter(prefix="/api/personal", tags=["personal"])


@router.get("/profile", response_model=PersonalProfile)
async def get_profile(request: Request) -> PersonalProfile:
    return await request.app.state.personal_profile_service.get()


@router.post("/profile/fields")
async def set_field(key: str, value: str, request: Request) -> PersonalProfile:
    return await request.app.state.personal_profile_service.set_field(key, value)


@router.get("/commitments", response_model=list[Commitment])
async def list_commitments(request: Request) -> list[Commitment]:
    return await request.app.state.commitment_service.open_commitments()


@router.post("/commitments", response_model=Commitment)
async def create_commitment(description: str, request: Request, recipient: str | None = None, source: CommitmentSource = CommitmentSource.EXPLICIT_PROMISE) -> Commitment:
    return await request.app.state.commitment_service.create(description, recipient=recipient, source=source)


@router.post("/commitments/{commitment_id}/complete", response_model=Commitment)
async def complete_commitment(commitment_id: str, request: Request) -> Commitment:
    try:
        return await request.app.state.commitment_service.complete(commitment_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

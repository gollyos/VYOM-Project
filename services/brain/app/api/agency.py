from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.agency.schemas import LeadResearchRequest, OutreachRequest, QualificationResult
from app.email.schemas import EmailDraft


router = APIRouter(prefix="/api/agency", tags=["agency"])


@router.post("/research", response_model=list[QualificationResult])
async def research(payload: LeadResearchRequest, request: Request) -> list[QualificationResult]:
    try:
        return await request.app.state.agency_service.research_leads(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/outreach/draft", response_model=EmailDraft)
async def draft_outreach(payload: OutreachRequest, request: Request) -> EmailDraft:
    try:
        return await request.app.state.agency_service.prepare_outreach(payload)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Lead not found") from error
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

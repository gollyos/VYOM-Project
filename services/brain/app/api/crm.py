from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.crm.models import CRMRecord, Lead, LeadState


router = APIRouter(prefix="/api/crm", tags=["crm"])


@router.get("/records")
async def list_records(request: Request, record_type: str | None = None) -> list[dict]:
    return [item.model_dump(mode="json") for item in await request.app.state.crm_store.list(record_type)]


@router.post("/records")
async def upsert_record(payload: CRMRecord, request: Request) -> dict:
    record, created = await request.app.state.crm_store.upsert(payload)
    return {"record": record.model_dump(mode="json"), "created": created}


@router.get("/leads", response_model=list[Lead])
async def list_leads(request: Request, state: LeadState | None = None) -> list[Lead]:
    return await request.app.state.crm_store.leads(state)


@router.post("/leads", response_model=Lead)
async def upsert_lead(payload: Lead, request: Request) -> Lead:
    record, _ = await request.app.state.crm_store.upsert(payload)
    return Lead.model_validate(record.model_dump())


@router.post("/leads/{lead_id}/state/{state}", response_model=Lead)
async def transition_lead(lead_id: str, state: LeadState, request: Request) -> Lead:
    try:
        return await request.app.state.crm_store.transition_lead(lead_id, state)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Lead not found") from error
    except PermissionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.automation.schemas import Automation, AutomationCreate, AutomationStatus


router = APIRouter(prefix="/api/automations", tags=["automations"])


@router.get("", response_model=list[Automation])
async def list_automations(request: Request) -> list[Automation]:
    return await request.app.state.automation_store.list()


@router.post("", response_model=Automation)
async def create_automation(payload: AutomationCreate, request: Request) -> Automation:
    automation = Automation.from_create(payload)
    await request.app.state.automation_store.save(automation)
    return automation


@router.post("/{automation_id}/pause", response_model=Automation)
async def pause(automation_id: str, request: Request) -> Automation:
    try:
        automation = await request.app.state.automation_store.get(automation_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Automation not found") from error
    automation.status = AutomationStatus.PAUSED
    await request.app.state.automation_store.save(automation)
    return automation


@router.post("/{automation_id}/resume", response_model=Automation)
async def resume(automation_id: str, request: Request) -> Automation:
    try:
        automation = await request.app.state.automation_store.get(automation_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Automation not found") from error
    if automation.status == AutomationStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Completed one-time automation cannot resume")
    automation.status = AutomationStatus.ACTIVE
    await request.app.state.automation_store.save(automation)
    return automation

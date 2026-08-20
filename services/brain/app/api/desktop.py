from __future__ import annotations

from fastapi import APIRouter, Request

from app.automation.schemas import AutomationStatus
from app.desktop.schemas import SystemStatus

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


@router.get("/status", response_model=SystemStatus)
async def status(request: Request) -> SystemStatus:
    return request.app.state.desktop_controller.status()


@router.post("/emergency-pause")
async def emergency_pause(request: Request) -> dict:
    """Safety stop always takes priority over normal execution: engages
    the global input-automation pause and cancels every active task."""
    request.app.state.emergency_pause.pause()
    runtime = request.app.state.runtime
    cancelled = []
    for task_id in list(runtime.active.keys()):
        await runtime.cancel(task_id)
        cancelled.append(task_id)
    return {"paused": True, "cancelled_tasks": cancelled}


@router.post("/emergency-resume")
async def emergency_resume(request: Request) -> dict:
    request.app.state.emergency_pause.resume()
    return {"paused": False}


@router.post("/automations/pause-all")
async def pause_all_automations(request: Request) -> dict:
    store = request.app.state.automation_store
    paused = []
    for automation in await store.list():
        if automation.status == AutomationStatus.ACTIVE:
            automation.status = AutomationStatus.PAUSED
            await store.save(automation)
            paused.append(automation.id)
    return {"paused": paused}


@router.post("/automations/resume-all")
async def resume_all_automations(request: Request) -> dict:
    store = request.app.state.automation_store
    resumed = []
    for automation in await store.list():
        if automation.status == AutomationStatus.PAUSED:
            automation.status = AutomationStatus.ACTIVE
            await store.save(automation)
            resumed.append(automation.id)
    return {"resumed": resumed}

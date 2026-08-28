from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.automation.schemas import Automation, AutomationCreate, AutomationStatus
from app.automation.natural_builder import NaturalAutomationBuilder
from app.automation.workflow_engine import WorkflowStep


router = APIRouter(prefix="/api/automations", tags=["automations"])


class NaturalPromptRequest(BaseModel):
    prompt: str


class RunAutomationRequest(BaseModel):
    trigger_data: dict[str, Any] = Field(default_factory=dict)


@router.get("", response_model=list[Automation])
async def list_automations(request: Request) -> list[Automation]:
    return await request.app.state.automation_store.list()


@router.post("", response_model=Automation)
async def create_automation(payload: AutomationCreate, request: Request) -> Automation:
    automation = Automation.from_create(payload)
    await request.app.state.automation_store.save(automation)
    return automation


@router.post("/generate")
async def generate_from_natural_language(payload: NaturalPromptRequest) -> dict[str, Any]:
    """Convert natural language description into a structured automation."""
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    return NaturalAutomationBuilder.parse_instruction(payload.prompt)


@router.post("/{automation_id}/run")
async def run_automation(automation_id: str, payload: RunAutomationRequest, request: Request) -> dict[str, Any]:
    """Manually trigger a multi-step automation workflow."""
    try:
        automation = await request.app.state.automation_store.get(automation_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Automation not found") from error

    workflow_engine = getattr(request.app.state, "workflow_engine", None)
    if not workflow_engine:
        raise HTTPException(status_code=503, detail="Workflow engine unavailable")

    # Build steps from automation condition or action
    cond = automation.condition or {}
    raw_steps = cond.get("steps") or []
    steps = [WorkflowStep.model_validate(s) for s in raw_steps] if raw_steps else [
        WorkflowStep(
            name=f"Execute {automation.action}",
            type="tool_call",
            tool=automation.action if "." in automation.action else "system.run_command",
            input_template=cond.get("inputs", {}),
        )
    ]

    run = await workflow_engine.execute_workflow(
        workflow_id=automation.id,
        workflow_name=automation.name,
        steps=steps,
        trigger_data=payload.trigger_data,
    )
    return run.model_dump(mode="json")


@router.get("/runs/{run_id}")
async def get_run_details(run_id: str, request: Request) -> dict[str, Any]:
    workflow_engine = getattr(request.app.state, "workflow_engine", None)
    if not workflow_engine:
        raise HTTPException(status_code=503, detail="Workflow engine unavailable")
    run = workflow_engine.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run.model_dump(mode="json")


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


@router.delete("/{automation_id}")
async def delete_automation(automation_id: str, request: Request) -> dict[str, Any]:
    connection = request.app.state.automation_store.database.require_connection()
    await connection.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
    await connection.commit()
    return {"status": "deleted", "id": automation_id}

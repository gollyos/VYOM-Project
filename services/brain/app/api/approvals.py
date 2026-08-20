from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.schemas.approvals import ApprovalDecision, ApprovalRequest
from app.schemas.tasks import Task, TaskStatus


router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalRequest])
async def list_pending_approvals(request: Request) -> list[ApprovalRequest]:
    tasks = await request.app.state.task_store.list_by_status({TaskStatus.NEEDS_APPROVAL})
    return [ApprovalRequest.model_validate(task.metadata["approval"]) for task in tasks if task.metadata.get("approval")]


@router.post("/{task_id}", response_model=Task)
async def decide_approval(task_id: str, decision: ApprovalDecision, request: Request) -> Task:
    try:
        return await request.app.state.runtime.decide_approval(task_id, decision.approved)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Task not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

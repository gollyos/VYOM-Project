from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.tasks import Task, TaskCreate


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=Task, status_code=status.HTTP_202_ACCEPTED)
async def create_task(payload: TaskCreate, request: Request) -> Task:
    return await request.app.state.runtime.create_task(payload)


@router.get("", response_model=list[Task])
async def list_tasks(request: Request, limit: int = 100) -> list[Task]:
    return await request.app.state.task_store.list(min(max(limit, 1), 500))


@router.get("/{task_id}", response_model=Task)
async def get_task(task_id: str, request: Request) -> Task:
    task = await request.app.state.task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _control(task_id: str, request: Request, operation: str) -> Task:
    try:
        return await getattr(request.app.state.runtime, operation)(task_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Task not found") from error


@router.post("/{task_id}/pause", response_model=Task)
async def pause_task(task_id: str, request: Request) -> Task:
    return await _control(task_id, request, "pause")


@router.post("/{task_id}/resume", response_model=Task)
async def resume_task(task_id: str, request: Request) -> Task:
    return await _control(task_id, request, "resume")


@router.post("/{task_id}/cancel", response_model=Task)
async def cancel_task(task_id: str, request: Request) -> Task:
    return await _control(task_id, request, "cancel")


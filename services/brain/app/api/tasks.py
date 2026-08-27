from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.tasks import Task, TaskCreate, TaskStatus


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=Task, status_code=status.HTTP_202_ACCEPTED)
async def create_task(payload: TaskCreate, request: Request) -> Task:
    return await request.app.state.runtime.create_task(payload)


@router.get("", response_model=list[Task])
async def list_tasks(request: Request, limit: int = 100) -> list[Task]:
    return await request.app.state.task_store.list(min(max(limit, 1), 500))


@router.get("/pending-work")
async def pending_work(request: Request) -> dict:
    """Unfinished work from before the app was last closed/crashed/lost
    power - the answer to 'bijli chali gayi thi, kya pending tha'.
    Called by the frontend once on boot (see use-vyom-runtime.ts) so the
    user is told about interrupted work WITHOUT having to ask for a
    daily briefing first. Real task_store rows only - PAUSED tasks were
    deliberately not auto-resumed (Phase 12 recovery decided it was
    unsafe to blindly re-run), FAILED tasks genuinely failed; both need
    an explicit user decision (resume / retry / dismiss), never a
    silent re-run.

    Stale failures stop counting after 3 days: during the Aug-2026
    disconnect era every command failed while the Brain was down, and
    those dead rows kept re-appearing in the boot banner for weeks as
    scary "unfinished work" nobody can meaningfully resume.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=3)

    def _fresh(task: Task) -> bool:
        try:
            created = task.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return created >= cutoff
        except Exception:
            return True

    paused = await request.app.state.task_store.list_by_status({TaskStatus.PAUSED})
    failed = await request.app.state.task_store.list_by_status({TaskStatus.FAILED})
    def _summarize(task: Task) -> dict:
        return {
            "task_id": task.id,
            "summary": (task.user_request or task.goal or "task")[:200],
            "status": task.status.value,
            "created_at": task.created_at.isoformat(),
            "error": task.error,
        }
    items = [
        _summarize(t) for t in (paused + failed)
        if t.status is TaskStatus.PAUSED or _fresh(t)
    ][:10]
    return {"count": len(items), "items": items}


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


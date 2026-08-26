from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.skills.registry import DuplicateSkillError

router = APIRouter(prefix="/api/learn", tags=["learn"])


@router.post("/from-task/{task_id}")
async def learn_from_task(task_id: str, request: Request, payload: dict | None = None) -> dict:
    """VYOM's `/learn` - mirrors Hermes's own agent/learn_prompt.py:
    point at a completed task and derive a reusable, TESTING-status
    skill from its real plan + evidence. Never auto-activates - see
    app/skills/learn.py for the safety rationale."""
    task_store = request.app.state.task_store
    task = await task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    learn_service = request.app.state.learn_service
    skill_id = (payload or {}).get("skill_id")
    try:
        skill = learn_service.from_task(task, skill_id=skill_id)
    except (ValueError, DuplicateSkillError) as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"skill_id": skill.id, "status": skill.status.value, "steps": len(skill.steps)}


@router.post("/from-description")
async def learn_from_description(request: Request, payload: dict) -> dict:
    """Learn from a pasted/described workflow (numbered or bulleted
    steps) instead of a task - the other real source in
    app/skills/learn.py."""
    learn_service = request.app.state.learn_service
    try:
        skill = learn_service.from_description(
            payload["description"], skill_id=payload["skill_id"], name=payload.get("name", payload["skill_id"]),
        )
    except (ValueError, DuplicateSkillError) as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"skill_id": skill.id, "status": skill.status.value, "steps": len(skill.steps)}

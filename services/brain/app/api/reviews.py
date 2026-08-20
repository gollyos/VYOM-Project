from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/plan-today")
async def plan_today(request: Request) -> dict:
    engine = request.app.state.phase11_engine
    context = await engine._chief_of_staff_context()
    briefing = engine.chief_of_staff.brief(context)
    return briefing.model_dump(mode="json")


@router.get("/evening")
async def evening_review(request: Request) -> dict:
    from app.schemas.tasks import Task, TaskProfile

    engine = request.app.state.phase11_engine
    task = Task(goal="Evening review", user_request="How did today go?")
    profile = TaskProfile(intent="evening_review", needs={"phase11"}, deterministic=True)

    async def noop_emit(event_type: str, message: str, payload: dict) -> None:
        return None

    result = await engine._evening_review(task, noop_emit)
    return result.structured_data


@router.get("/weekly")
async def weekly_review(request: Request) -> dict:
    from app.schemas.tasks import Task, TaskProfile

    engine = request.app.state.phase11_engine
    task = Task(goal="Weekly review", user_request="Give me my weekly review.")
    profile = TaskProfile(intent="weekly_review", needs={"phase11"}, deterministic=True)

    async def noop_emit(event_type: str, message: str, payload: dict) -> None:
        return None

    result = await engine._weekly_review(task, noop_emit)
    return result.structured_data


@router.post("/quiet-mode/start")
async def start_quiet_mode(minutes: float, request: Request) -> dict:
    until = request.app.state.quiet_mode.start(minutes)
    return {"until": until.isoformat()}


@router.post("/quiet-mode/end")
async def end_quiet_mode(request: Request) -> dict:
    request.app.state.quiet_mode.end()
    return {"active": False}


@router.post("/focus/start")
async def start_focus(goal: str, request: Request, planned_minutes: float = 25.0) -> dict:
    session = await request.app.state.focus_session_service.start(goal, planned_minutes=planned_minutes)
    return session.model_dump(mode="json")


@router.post("/focus/complete")
async def complete_focus(session_id: str, request: Request) -> dict:
    session = await request.app.state.focus_session_service.complete(session_id)
    return session.model_dump(mode="json")

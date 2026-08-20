from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.habits.schemas import Habit, HabitEvent, HabitEventSource

router = APIRouter(prefix="/api/habits", tags=["habits"])


@router.get("", response_model=list[Habit])
async def list_habits(request: Request) -> list[Habit]:
    return await request.app.state.habit_store.list()


@router.post("", response_model=Habit)
async def create_habit(habit: Habit, request: Request) -> Habit:
    return await request.app.state.habit_tracker.create(habit)


@router.post("/{habit_id}/check-in", response_model=HabitEvent)
async def check_in(habit_id: str, request: Request, value: float = 1.0, source: HabitEventSource = HabitEventSource.MANUAL, note: str | None = None) -> HabitEvent:
    try:
        return await request.app.state.habit_tracker.check_in(habit_id, value=value, source=source, note=note)
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/{habit_id}/disable", response_model=Habit)
async def disable_habit(habit_id: str, request: Request) -> Habit:
    """Rule 70: the user can always say "do not track this habit"."""
    try:
        return await request.app.state.habit_tracker.disable(habit_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{habit_id}/insight")
async def habit_insight(habit_id: str, request: Request) -> dict:
    habit = await request.app.state.habit_store.get(habit_id)
    if habit is None:
        raise HTTPException(status_code=404, detail="Habit not found")
    events = await request.app.state.habit_tracker.events(habit_id)
    report = request.app.state.habit_insight_service.report(habit, events)
    return report.model_dump(mode="json")

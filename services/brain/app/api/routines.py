from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.routines.schemas import Routine, RoutineRun

router = APIRouter(prefix="/api/routines", tags=["routines"])


@router.get("", response_model=list[Routine])
async def list_routines(request: Request) -> list[Routine]:
    return await request.app.state.routine_manager.list()


@router.post("", response_model=Routine)
async def create_routine(routine: Routine, request: Request) -> Routine:
    return await request.app.state.routine_manager.create(routine)


@router.post("/{routine_id}/run", response_model=RoutineRun)
async def run_routine(routine_id: str, request: Request) -> RoutineRun:
    try:
        routine = await request.app.state.routine_manager.get(routine_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return await request.app.state.routine_completion_service.run(routine)


@router.post("/{routine_id}/enable", response_model=Routine)
async def enable_routine(routine_id: str, request: Request) -> Routine:
    try:
        return await request.app.state.routine_manager.enable(routine_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{routine_id}/adaptation")
async def routine_adaptation(routine_id: str, request: Request) -> dict:
    suggestion = await request.app.state.routine_adaptation_service.evaluate(routine_id)
    return suggestion.model_dump(mode="json") if suggestion else {"suggestion": None}

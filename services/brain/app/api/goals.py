from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.goals.schemas import Goal, GoalCategory, GoalPriority, GoalStatus, Milestone

router = APIRouter(prefix="/api/goals", tags=["goals"])


@router.get("", response_model=list[Goal])
async def list_goals(request: Request, status: GoalStatus | None = None) -> list[Goal]:
    return await request.app.state.goal_manager.list(status)


@router.post("", response_model=Goal)
async def create_goal(title: str, request: Request, description: str = "", category: GoalCategory = GoalCategory.OTHER, priority: GoalPriority = GoalPriority.MEDIUM) -> Goal:
    goal, _plan = await request.app.state.goal_manager.create(title, description=description, category=category, priority=priority)
    return goal


@router.get("/{goal_id}", response_model=Goal)
async def get_goal(goal_id: str, request: Request) -> Goal:
    try:
        return await request.app.state.goal_manager.get(goal_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{goal_id}/milestones", response_model=list[Milestone])
async def list_milestones(goal_id: str, request: Request) -> list[Milestone]:
    return await request.app.state.milestone_service.list_for_goal(goal_id)


@router.post("/{goal_id}/transition", response_model=Goal)
async def transition_goal(goal_id: str, status: GoalStatus, request: Request, reason: str | None = None) -> Goal:
    try:
        return await request.app.state.goal_manager.transition(goal_id, status, reason=reason)
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/{goal_id}/health")
async def goal_health(goal_id: str, request: Request) -> dict:
    goal = await request.app.state.goal_manager.get(goal_id)
    report = request.app.state.goal_evaluator.evaluate(goal)
    return report.model_dump(mode="json")

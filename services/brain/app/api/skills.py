from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request


router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
async def list_skills(request: Request) -> list[dict]:
    return [skill.model_dump(mode="json") for skill in request.app.state.skill_registry.list()]


@router.get("/{skill_id}")
async def get_skill(skill_id: str, request: Request) -> dict:
    skill = request.app.state.skill_registry.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.model_dump(mode="json")


@router.post("/build-check")
async def create_build_check(request: Request) -> dict:
    skill, evaluation, created = await request.app.state.skill_builder.create_build_check(created_by="local-api")
    request.app.state.capability_discovery.from_skill(skill)
    return {"skill": skill.model_dump(mode="json"), "evaluation": evaluation.model_dump(mode="json") if evaluation else None, "created": created}

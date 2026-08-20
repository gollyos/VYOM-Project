from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agents.schemas import AgentStatus


router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentTransition(BaseModel):
    status: AgentStatus


@router.get("")
async def list_agents(request: Request) -> list[dict]:
    return [agent.model_dump(mode="json") for agent in request.app.state.agent_registry.list()]


@router.get("/{agent_id}")
async def get_agent(agent_id: str, request: Request) -> dict:
    agent = request.app.state.agent_registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent.model_dump(mode="json")


@router.post("/project-health")
async def create_project_health_agent(request: Request) -> dict:
    skill, _, _ = await request.app.state.skill_builder.create_build_check(created_by="agent-api")
    request.app.state.capability_discovery.from_skill(skill)
    agent, validation, created = request.app.state.agent_factory.create_project_health()
    request.app.state.capability_discovery.from_agent(agent)
    return {"agent": agent.model_dump(mode="json"), "validation": validation.model_dump(mode="json"), "created": created}


@router.patch("/{agent_id}/status")
async def transition_agent(agent_id: str, payload: AgentTransition, request: Request) -> dict:
    try:
        agent = request.app.state.agent_lifecycle.transition(agent_id, payload.status)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Agent not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return agent.model_dump(mode="json")

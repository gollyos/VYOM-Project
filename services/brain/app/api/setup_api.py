from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.setup.schemas import SetupStepId, SetupStepStatus

router = APIRouter(prefix="/api/setup", tags=["setup"])


class CompleteStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: dict = {}


class ProviderConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    api_key: str


class AutonomyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str


@router.get("/status")
async def setup_status(request: Request) -> dict:
    return request.app.state.onboarding.status()


@router.get("/steps")
async def list_steps(request: Request) -> list[dict]:
    state = request.app.state.onboarding.current()
    return [step.model_dump(mode="json") for step in state.steps]


@router.post("/steps/{step_id}/complete")
async def complete_step(step_id: str, payload: CompleteStepRequest, request: Request) -> dict:
    try:
        parsed = SetupStepId(step_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=f"Unknown step {step_id}") from error
    return await request.app.state.onboarding.complete_step(parsed, payload.data)


@router.post("/steps/{step_id}/skip")
async def skip_step(step_id: str, request: Request) -> dict:
    try:
        parsed = SetupStepId(step_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=f"Unknown step {step_id}") from error
    try:
        return await request.app.state.onboarding.skip_step(parsed)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/reset")
async def reset_setup(request: Request) -> dict:
    """Resets onboarding/setup configuration only — memories, projects,
    and stored secrets are untouched."""
    return await request.app.state.onboarding.reset()


@router.get("/providers")
async def provider_options(request: Request) -> list[dict]:
    return request.app.state.provider_setup.list_options()


@router.post("/providers/connect")
async def connect_provider(payload: ProviderConnectRequest, request: Request) -> dict:
    result = await request.app.state.provider_setup.connect(payload.provider, payload.api_key)
    await request.app.state.security_events.record(
        "secret_changed", actor="setup",
        detail=f"provider credential stored: {payload.provider}",
    )
    return result


@router.get("/integrations")
async def integration_options(request: Request) -> list[dict]:
    return request.app.state.integration_setup.list_options()


@router.post("/integrations/{integration_id}/begin")
async def begin_integration(integration_id: str, request: Request) -> dict:
    try:
        return await request.app.state.integration_setup.begin_connection(integration_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Unknown integration") from error


@router.get("/autonomy")
async def autonomy_options(request: Request) -> dict:
    return {
        "presets": request.app.state.permission_setup.describe_options(),
        "current": request.app.state.authorization_service.describe(),
    }


@router.post("/autonomy")
async def apply_autonomy(payload: AutonomyRequest, request: Request) -> dict:
    try:
        applied = request.app.state.permission_setup.apply(payload.preset)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await request.app.state.security_events.record(
        "permission_changed", actor="setup", detail=f"autonomy preset -> {payload.preset}",
    )
    return applied

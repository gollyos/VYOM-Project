from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.integrations.schemas import IntegrationRecord, OAuthCallback, OAuthStart


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationRecord])
async def list_integrations(request: Request) -> list[IntegrationRecord]:
    return request.app.state.integration_registry.list()


@router.post("/{integration_id}/oauth/start", response_model=OAuthStart)
async def start_oauth(integration_id: str, request: Request) -> OAuthStart:
    try:
        return await request.app.state.integration_registry.begin_oauth(integration_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Integration not found") from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/{integration_id}/oauth/callback", response_model=IntegrationRecord)
async def oauth_callback(integration_id: str, payload: OAuthCallback, request: Request) -> IntegrationRecord:
    try:
        return await request.app.state.integration_registry.complete_oauth(integration_id, payload.code, payload.state)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Integration not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/{integration_id}/health", response_model=IntegrationRecord)
async def integration_health(integration_id: str, request: Request) -> IntegrationRecord:
    try:
        return await request.app.state.integration_registry.refresh_health(integration_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Integration not found") from error


@router.post("/{integration_id}/disconnect", response_model=IntegrationRecord)
async def disconnect(integration_id: str, request: Request) -> IntegrationRecord:
    try:
        return await request.app.state.integration_registry.disconnect(integration_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Integration not found") from error

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


class ConnectRequest(BaseModel):
    credentials: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def list_connectors(request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "connector_registry", None)
    if not registry:
        return {"connectors": []}
    return {"connectors": registry.list_connectors()}


@router.get("/{connector_id}")
async def get_connector(connector_id: str, request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "connector_registry", None)
    if not registry:
        raise HTTPException(status_code=503, detail="Connector system unavailable")
    conn = registry.get_connector(connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found")
    status = await conn.status_check()
    return {
        **conn.definition.model_dump(mode="json"),
        "status": conn.status.value,
        "health": status,
        "tools": [t.model_dump(mode="json") for t in conn.list_tools()],
    }


@router.post("/{connector_id}/connect")
async def connect_connector(connector_id: str, payload: ConnectRequest, request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "connector_registry", None)
    if not registry:
        raise HTTPException(status_code=503, detail="Connector system unavailable")
    try:
        return await registry.connect(connector_id, payload.credentials)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found")
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/{connector_id}/disconnect")
async def disconnect_connector(connector_id: str, request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "connector_registry", None)
    if not registry:
        raise HTTPException(status_code=503, detail="Connector system unavailable")
    try:
        return await registry.disconnect(connector_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found")


@router.post("/{connector_id}/test")
async def test_connector(connector_id: str, request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "connector_registry", None)
    if not registry:
        raise HTTPException(status_code=503, detail="Connector system unavailable")
    conn = registry.get_connector(connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found")
    return await conn.status_check()


@router.post("/{connector_id}/tools/{tool_name}/execute")
async def execute_tool(
    connector_id: str, tool_name: str, payload: ToolExecutionRequest, request: Request
) -> dict[str, Any]:
    registry = getattr(request.app.state, "connector_registry", None)
    if not registry:
        raise HTTPException(status_code=503, detail="Connector system unavailable")
    conn = registry.get_connector(connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found")
    
    try:
        result = await conn.execute_tool(tool_name, payload.arguments)
        return {"success": True, "output": result}
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))

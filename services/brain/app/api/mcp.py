from __future__ import annotations

from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, Request

from app.mcp import catalog as mcp_catalog
from app.mcp.server_config import MCPServerConfig

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/servers")
async def list_servers(request: Request) -> dict:
    return {"servers": request.app.state.mcp_registry.describe()}


@router.post("/servers")
async def add_server(config: MCPServerConfig, request: Request) -> dict:
    """Add and immediately connect a new MCP server. This is the explicit,
    auditable act of granting VYOM a new capability — VYOM does not invent
    or auto-discover servers to run; a human (or an approved automation)
    names the command here."""
    manager = request.app.state.mcp_manager
    if config.id in request.app.state.mcp_registry.servers:
        raise HTTPException(status_code=409, detail=f"MCP server '{config.id}' is already registered")
    result = await manager.connect(config)
    if result.get("status") != "connected":
        raise HTTPException(status_code=502, detail=result.get("detail", "failed to connect"))
    return result


@router.post("/servers/{server_id}/reconnect")
async def reconnect_server(server_id: str, request: Request) -> dict:
    result = await request.app.state.mcp_manager.reconnect(server_id)
    if result.get("status") != "connected":
        raise HTTPException(status_code=502, detail=result.get("detail", "failed to reconnect"))
    return result


@router.delete("/servers/{server_id}")
async def remove_server(server_id: str, request: Request) -> dict:
    removed = await request.app.state.mcp_manager.disconnect(server_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' is not registered")
    return {"server_id": server_id, "status": "disconnected"}


@router.get("/catalog")
async def list_catalog() -> dict:
    """Curated, pre-vetted MCP servers VYOM knows how to run by NAME —
    not live discovery of arbitrary npm/PyPI packages. This is how a task
    that needs 'a filesystem tool' or 'a persistent memory graph' can be
    satisfied without a human typing an exact command line."""
    return {"catalog": mcp_catalog.describe()}


class CatalogConnectRequest(BaseModel):
    catalog_id: str
    server_id: str | None = None
    path: str | None = None


@router.post("/servers/from-catalog")
async def add_server_from_catalog(payload: CatalogConnectRequest, request: Request) -> dict:
    entry = mcp_catalog.find(payload.catalog_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No catalog entry named '{payload.catalog_id}'")
    if entry.requires_path_arg and not payload.path:
        raise HTTPException(
            status_code=422,
            detail=f"Catalog server '{entry.catalog_id}' requires a 'path' (a directory VYOM may access)",
        )
    args = [arg.format(path=payload.path or "") for arg in entry.args_template]
    server_id = payload.server_id or entry.catalog_id
    config = MCPServerConfig(
        id=server_id, name=entry.display_name, command=entry.command, args=args,
        trust_level=entry.trust_level,
    )
    manager = request.app.state.mcp_manager
    if server_id in request.app.state.mcp_registry.servers:
        raise HTTPException(status_code=409, detail=f"MCP server '{server_id}' is already registered")
    result = await manager.connect(config)
    if result.get("status") != "connected":
        raise HTTPException(status_code=502, detail=result.get("detail", "failed to connect"))
    return result

from __future__ import annotations

from pydantic import BaseModel, Field

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


class ConnectServiceRequest(BaseModel):
    #: A plain-language service name — "notion", "connect my slack",
    #: "I want github" — NOT necessarily an exact catalog_id.
    service: str
    path: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


@router.post("/connect")
async def connect_service(payload: ConnectServiceRequest, request: Request) -> dict:
    """The 'tell VYOM a service name, it figures out the rest' entry point.
    Fuzzy-matches the request against the curated catalog first (never
    against live npm/PyPI search — see catalog.py's docstring on why); if
    nothing matches, returns a structured 'unknown' response naming what a
    human (or a follow-up catalog-authoring change) needs to supply, rather
    than guessing a package name and running it."""
    normalized = payload.service.strip().lower()
    match = mcp_catalog.find(normalized)
    if match is None:
        # Fuzzy match: score every entry by how many of the request's
        # significant words it matches (catalog_id / display_name weighted
        # higher than description, so e.g. "brave search" matches
        # brave-search's id+name over filesystem's description mentioning
        # "search" once), then take the best-scoring entry above a floor.
        words = [w for w in normalized.replace("-", " ").split() if len(w) > 2]
        best_entry, best_score = None, 0
        for entry in mcp_catalog.CATALOG:
            identity = f"{entry.catalog_id} {entry.display_name}".lower().replace("-", " ")
            description = entry.description.lower()
            score = 0
            if entry.catalog_id.replace("-", " ") in normalized:
                score += 10  # the catalog id itself appearing is decisive
            for word in words:
                if word in identity:
                    score += 3
                elif word in description:
                    score += 1
            if score > best_score:
                best_entry, best_score = entry, score
        if best_score >= 3:  # require at least one identity-level hit
            match = best_entry
    if match is None:
        known = ", ".join(entry.catalog_id for entry in mcp_catalog.CATALOG)
        return {
            "status": "unknown_service",
            "requested": payload.service,
            "detail": (
                f"'{payload.service}' is not in VYOM's reviewed MCP catalog yet. "
                f"Known services: {known}. To add a new one, VYOM (or a developer) "
                "reviews the service's real MCP server package and adds a catalog "
                "entry — VYOM never runs an unreviewed package automatically."
            ),
            "known_services": [entry.catalog_id for entry in mcp_catalog.CATALOG],
        }
    missing = [name for name in match.required_env if name not in payload.env]
    if missing:
        return {
            "status": "needs_credentials",
            "catalog_id": match.catalog_id,
            "display_name": match.display_name,
            "description": match.description,
            "missing_env": missing,
            "detail": f"Connecting {match.display_name} needs: {', '.join(missing)}. Ask the user for these, then retry with env filled in.",
        }
    if match.requires_path_arg and not payload.path:
        return {
            "status": "needs_path",
            "catalog_id": match.catalog_id,
            "display_name": match.display_name,
            "detail": f"{match.display_name} needs a path/connection-string argument.",
        }
    server_id = match.catalog_id
    if server_id in request.app.state.mcp_registry.servers:
        return {"status": "already_connected", "server_id": server_id}
    if match.requires_path_arg and "{connection_string}" in match.args_template:
        args = [arg.format(connection_string=payload.path or "") for arg in match.args_template]
    else:
        args = [arg.format(path=payload.path or "") for arg in match.args_template]
    config = MCPServerConfig(
        id=server_id, name=match.display_name, command=match.command, args=args,
        env=payload.env, trust_level=match.trust_level, timeout_seconds=match.startup_timeout_seconds,
    )
    result = await request.app.state.mcp_manager.connect(config)
    return {"status": result.get("status", "error"), "matched_catalog_id": match.catalog_id, **result}


class CatalogConnectRequest(BaseModel):
    catalog_id: str
    server_id: str | None = None
    path: str | None = None
    #: API keys/tokens the catalog entry's required_env names. VYOM never
    #: invents or stores these on its own — the caller (a human, or an
    #: approved automation reading a value the user already gave it)
    #: supplies the real value here, once, and it becomes this server's
    #: subprocess environment for as long as it's connected.
    env: dict[str, str] = Field(default_factory=dict)


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
    missing = [name for name in entry.required_env if name not in payload.env]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Catalog server '{entry.catalog_id}' requires env value(s) for: {', '.join(missing)}",
        )
    if entry.requires_path_arg and "{connection_string}" in entry.args_template:
        args = [arg.format(connection_string=payload.path or "") for arg in entry.args_template]
    else:
        args = [arg.format(path=payload.path or "") for arg in entry.args_template]
    server_id = payload.server_id or entry.catalog_id
    config = MCPServerConfig(
        id=server_id, name=entry.display_name, command=entry.command, args=args,
        env=payload.env, trust_level=entry.trust_level, timeout_seconds=entry.startup_timeout_seconds,
    )
    manager = request.app.state.mcp_manager
    if server_id in request.app.state.mcp_registry.servers:
        raise HTTPException(status_code=409, detail=f"MCP server '{server_id}' is already registered")
    result = await manager.connect(config)
    if result.get("status") != "connected":
        raise HTTPException(status_code=502, detail=result.get("detail", "failed to connect"))
    return result

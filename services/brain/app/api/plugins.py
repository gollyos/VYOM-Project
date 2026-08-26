from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("")
async def list_plugins(request: Request) -> dict:
    """Loaded plugins and any load errors (see app/plugins/registry.py -
    mirrors Hermes's own 4-source plugin discovery, scoped to VYOM's own
    task lifecycle hooks). A broken plugin never blocks Brain startup;
    its error is recorded here instead."""
    return request.app.state.plugin_registry.status()

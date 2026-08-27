from fastapi import APIRouter, Query, Request
from app.tools.catalog_300 import (
    ALL_300_TOOLS,
    get_all_tool_definitions,
    get_tools_by_category,
    search_tools,
    count_tools,
)
from app.tools.dynamic_matcher import get_tool_matcher

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools(request: Request) -> dict:
    active_tools = []
    if hasattr(request.app.state, "tool_registry") and request.app.state.tool_registry:
        active_tools = await request.app.state.tool_registry.describe()
    mcp_servers = []
    if hasattr(request.app.state, "mcp_registry") and request.app.state.mcp_registry:
        mcp_servers = request.app.state.mcp_registry.describe()
    return {
        "active_registered_tools": active_tools,
        "mcp_servers": mcp_servers,
        "catalog_summary": count_tools(),
    }


@router.get("/catalog")
async def get_tool_catalog(category: str | None = None) -> dict:
    """Returns the comprehensive 335+ tool definitions in the catalog."""
    if category:
        tools = get_tools_by_category(category)
    else:
        tools = get_all_tool_definitions()
    return {
        "total": len(tools),
        "category": category or "all",
        "counts": count_tools(),
        "tools": [t.model_dump(mode="json") for t in tools],
    }


@router.get("/search")
async def search_tool_catalog(q: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=50)) -> dict:
    """Dynamic JIT tool search across the 335+ tool catalog."""
    matcher = get_tool_matcher()
    matched = matcher.match_for_prompt(q, max_tools=limit)
    return {
        "query": q,
        "count": len(matched),
        "results": [t.model_dump(mode="json") for t in matched],
    }


@router.get("/categories")
async def get_catalog_categories() -> dict:
    """Returns breakdown of all 10 tool domains and counts."""
    return {
        "categories": count_tools(),
    }


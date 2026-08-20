from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools(request: Request) -> dict:
    return {
        "tools": await request.app.state.tool_registry.describe(),
        "mcp_servers": request.app.state.mcp_registry.describe(),
    }

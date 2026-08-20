from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.brain_graph.schemas import ConnectRequest


router = APIRouter(prefix="/api/brain-graph", tags=["brain-graph"])


@router.get("")
async def get_graph(request: Request, root_id: str | None = None, depth: int = 2,
                    limit: int = 300, include_core_edges: bool = True) -> dict:
    try:
        graph = await request.app.state.brain_graph.graph(
            root_id, depth=depth, limit=limit, include_core_edges=include_core_edges,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Brain entity not found: {error.args[0]}") from error
    return graph.model_dump(mode="json")


@router.get("/summary")
async def graph_summary(request: Request) -> dict:
    return await request.app.state.brain_graph.summary()


@router.get("/composition")
async def graph_composition(request: Request) -> dict:
    """Return the same Living Core composition used by a natural Brain command."""
    from app.schemas.tasks import Task, TaskProfile, TaskDomain

    task = Task(user_request="show my brain", goal="Show my brain")
    profile = TaskProfile(domain=TaskDomain.ANALYSIS, complexity=1, deterministic=True,
                          intent="show_brain_graph", needs={"intelligence"})

    async def emit(*_args, **_kwargs):
        return None

    result = await request.app.state.intelligence_engine.execute(task, profile, emit)
    return result.ui_composition or {}


@router.get("/{entity_id:path}/context")
async def linked_context(entity_id: str, request: Request, limit: int = 8) -> dict:
    try:
        context = await request.app.state.brain_graph.linked_context(entity_id, limit=min(max(limit, 1), 30))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Brain entity not found: {error.args[0]}") from error
    return {"entity_id": entity_id, "connections": context}


@router.post("/relationships")
async def connect_entities(payload: ConnectRequest, request: Request) -> dict:
    try:
        edge = await request.app.state.brain_graph.connect(payload)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Brain entity not found: {error.args[0]}") from error
    return edge.model_dump(mode="json")


@router.delete("/relationships/{edge_id}")
async def remove_relationship(edge_id: str, request: Request) -> dict:
    if not await request.app.state.brain_graph.remove_explicit(edge_id):
        raise HTTPException(status_code=404, detail="Explicit Brain relationship not found")
    return {"removed": True, "edge_id": edge_id}

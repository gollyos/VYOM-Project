from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.memory.schemas import (
    MemoryEntry, MemoryProvenance, MemoryQuery, MemoryType, ProvenanceType,
    Sensitivity, VerificationState,
)
from app.schemas.events import BrainEvent, EventType


router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryCreate(BaseModel):
    type: MemoryType
    title: str
    content: str
    summary: str
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.8, ge=0, le=1)
    sensitivity: Sensitivity = Sensitivity.NORMAL
    project_id: str | None = None
    client_id: str | None = None


class MemoryUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    summary: str | None = None
    entities: list[str] | None = None
    tags: list[str] | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    sensitivity: Sensitivity | None = None
    verification_state: VerificationState | None = None


@router.get("")
async def search_memory(
    request: Request,
    q: str = "",
    type: MemoryType | None = None,
    project_id: str | None = None,
    client_id: str | None = None,
    entity: str | None = None,
    source: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    include_history: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    results = await request.app.state.memory_manager.search(MemoryQuery(
        text=q,
        types={type} if type else set(),
        project_id=project_id,
        client_id=client_id,
        entities={entity} if entity else set(),
        sources={source} if source else set(),
        created_after=created_after,
        created_before=created_before,
        include_superseded=include_history,
        include_expired=include_history,
        limit=min(max(limit, 1), 100),
    ))
    return [item.model_dump(mode="json") for item in results]


@router.post("")
async def create_memory(payload: MemoryCreate, request: Request) -> dict[str, Any]:
    memory = await request.app.state.memory_manager.remember(MemoryEntry(
        **payload.model_dump(),
        provenance=[MemoryProvenance(type=ProvenanceType.MANUAL_IMPORT, reference="Local memory API")],
        verification_state=VerificationState.UNVERIFIED,
    ))
    await request.app.state.event_bus.publish(BrainEvent(task_id="memory-api", type=EventType.MEMORY_CREATED, human_readable_message="Memory created through the local API", structured_payload={"memory_id": memory.id}))
    return memory.model_dump(mode="json")


@router.get("/{memory_id}")
async def inspect_memory(memory_id: str, request: Request) -> dict[str, Any]:
    result = await request.app.state.memory_manager.inspect(memory_id)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.patch("/{memory_id}")
async def update_memory(memory_id: str, payload: MemoryUpdate, request: Request) -> dict[str, Any]:
    try:
        memory = await request.app.state.memory_manager.update(memory_id, **payload.model_dump(exclude_none=True))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Memory not found") from error
    await request.app.state.event_bus.publish(BrainEvent(task_id="memory-api", type=EventType.MEMORY_UPDATED, human_readable_message="Memory updated", structured_payload={"memory_id": memory.id}))
    return memory.model_dump(mode="json")


@router.delete("/{memory_id}")
async def forget_memory(memory_id: str, request: Request) -> dict[str, Any]:
    forgotten = await request.app.state.memory_manager.forget(memory_id)
    if not forgotten:
        raise HTTPException(status_code=404, detail="Memory not found")
    await request.app.state.event_bus.publish(BrainEvent(task_id="memory-api", type=EventType.MEMORY_FORGOTTEN, human_readable_message="Memory forgotten", structured_payload={"memory_id": memory_id}))
    return {"forgotten": True, "memory_id": memory_id}


@router.get("/{memory_id}/graph")
async def memory_graph(memory_id: str, request: Request, depth: int = 1) -> dict[str, Any]:
    if not await request.app.state.memory_store.get(memory_id, touch=False):
        raise HTTPException(status_code=404, detail="Memory not found")
    return await request.app.state.memory_manager.relationships.graph(memory_id, depth)

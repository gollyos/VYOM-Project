from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.sync.schemas import SyncEntity, SyncRecord

router = APIRouter(prefix="/api/sync", tags=["sync"])


class ApplyRequest(BaseModel):
    entity: SyncEntity
    entity_id: str
    payload: dict


class QueueRequest(BaseModel):
    command: str
    payload: dict = {}
    source_node: str = "mobile"


@router.get("/journal")
async def journal_since(request: Request, since: int = 0, limit: int = 200) -> dict:
    journal = request.app.state.sync_journal
    records = await journal.since(since, limit=min(limit, 1000))
    return {
        "latest_seq": await journal.latest_seq(),
        "records": [record.model_dump(mode="json") for record in records],
    }


@router.post("/apply")
async def apply_record(payload: ApplyRequest, request: Request) -> dict:
    engine = request.app.state.sync_engine
    record = await engine.apply(payload.entity, payload.entity_id, payload.payload)
    return record.model_dump(mode="json")


@router.get("/conflicts")
async def conflicts(request: Request) -> list[dict]:
    cursor = await request.app.state.database.require_connection().execute(
        "SELECT conflict_json FROM sync_conflicts ORDER BY created_at DESC LIMIT 100"
    )
    rows = await cursor.fetchall()
    import json

    return [json.loads(row["conflict_json"]) for row in rows]


@router.post("/offline/queue")
async def queue_command(payload: QueueRequest, request: Request) -> dict:
    queue = request.app.state.offline_queue
    record = await queue.enqueue({"command": payload.command, "payload": payload.payload, "source_node": payload.source_node})
    return {key: record[key] for key in ("id", "command", "risk", "consequential", "requires_reconfirmation", "expires_in_seconds")}


@router.post("/offline/submit")
async def submit_queued(request: Request) -> dict:
    queue = request.app.state.offline_queue

    async def submitter(record: dict) -> dict:
        from app.schemas.tasks import TaskCreate

        created = await request.app.state.runtime.create_task(TaskCreate(user_request=str(record.get("command", ""))))
        return {"task_id": created.id, "status": created.status.value}

    results = await queue.submit_due(submitter)
    return {"results": results}


@router.get("/snapshot/{node_id}")
async def snapshot_for(node_id: str, request: Request, since: int = 0) -> dict:
    replication = request.app.state.replication_manager
    return await replication.snapshot_for(node_id, since_seq=since)


@router.get("/freshness")
async def freshness(request: Request, entity: SyncEntity) -> dict:
    from app.devices.schemas import utc_now

    view = await request.app.state.sync_engine.freshness(entity, {}, as_of=utc_now())
    return {"entity": entity.value, "stale": view.stale, "age_seconds": view.age_seconds}

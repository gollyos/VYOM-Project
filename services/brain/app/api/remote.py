from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.remote.approvals import ApprovalExpiredError, StrongVerificationRequired
from app.remote.command_gateway import CommandRejected, RemoteCommandEnvelope
from app.remote.session import RemoteSessionManager

router = APIRouter(prefix="/api/remote", tags=["remote"])


class OpenSessionRequest(BaseModel):
    node_id: str
    token: str


class ApprovalDecisionRequest(BaseModel):
    decision: str  # approve | reject | modify | pause | cancel
    node_id: str
    strong_verification: bool = False
    modification: str | None = None


class NotifyStateRequest(BaseModel):
    state: str  # read | acted_on | dismissed


@router.post("/session")
async def open_session(payload: OpenSessionRequest, request: Request) -> dict:
    state = request.app.state
    node = state.device_registry.get(payload.node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown node")
    try:
        if not state.device_pairing.authenticate(payload.node_id, payload.token):
            raise HTTPException(status_code=401, detail="Authentication failed")
    except Exception as error:
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(status_code=401, detail="Authentication failed") from error
    session = await state.remote_sessions.open(payload.node_id)
    from app.schemas.events import BrainEvent, EventType

    await state.event_bus.publish(BrainEvent(
        task_id="system", type=EventType.NODE_AUTHENTICATED,
        human_readable_message=f"Node {node.name} authenticated for a remote session",
        structured_payload={"node_id": payload.node_id, "session_id": session.session_id},
    ))
    return {"session_id": session.session_id, "expires_at": session.expires_at.isoformat()}


@router.post("/command")
async def submit_command(payload: RemoteCommandEnvelope, request: Request) -> dict:
    gateway = request.app.state.remote_command_gateway
    try:
        result = await gateway.submit(payload)
    except CommandRejected as error:
        raise HTTPException(status_code=error.status_code, detail=error.reason) from error
    if result.get("accepted"):
        from app.schemas.tasks import TaskCreate

        created = await request.app.state.runtime.create_task(TaskCreate(user_request=payload.command))
        await request.app.state.remote_sessions.update_context(payload.session_id, active_task_id=created.id)
        result["task_id"] = created.id
        result["task_status"] = created.status.value
    return result


@router.post("/cancel/{task_id}")
async def cancel_task(task_id: str, payload: OpenSessionRequest, request: Request) -> dict:
    gateway = request.app.state.remote_command_gateway
    sessions: RemoteSessionManager = request.app.state.remote_sessions
    session = sessions.get(payload.node_id) or await sessions.open(payload.node_id)
    try:
        return await gateway.cancel_task(payload.node_id, session.session_id, task_id, request.app.state.runtime)
    except CommandRejected as error:
        raise HTTPException(status_code=error.status_code, detail=error.reason) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Task not found") from error


@router.get("/approvals")
async def list_approvals(request: Request) -> list[dict]:
    service = request.app.state.remote_approvals
    return [view.model_dump() for view in await service.pending()]


@router.post("/approvals/{task_id}")
async def decide_approval(task_id: str, payload: ApprovalDecisionRequest, request: Request) -> dict:
    service = request.app.state.remote_approvals
    try:
        return await service.decide(
            task_id, payload.decision, node_id=payload.node_id,
            strong_verification=payload.strong_verification, modification=payload.modification,
        )
    except ApprovalExpiredError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except StrongVerificationRequired as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Task not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/notifications/route")
async def route_notification(request: Request, title: str = "VYOM", body: str = "", priority: str = "normal") -> dict:
    router_service = request.app.state.remote_notification_router
    routed = router_service.route(title, body, priority)
    return routed.model_dump()


@router.post("/notifications/{notification_id}/state")
async def notification_state(notification_id: str, payload: NotifyStateRequest, request: Request) -> dict:
    router_service = request.app.state.remote_notification_router
    try:
        await router_service.record_state(notification_id, payload.state)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"notification_id": notification_id, "state": payload.state}


@router.get("/context/{node_id}")
async def node_context(node_id: str, request: Request) -> dict:
    return request.app.state.remote_sessions.context_for_node(node_id).model_dump()


@router.get("/away-summary")
async def away_summary(request: Request, since_iso: str) -> dict:
    from datetime import datetime

    try:
        since = datetime.fromisoformat(since_iso)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid since_iso") from error
    builder = request.app.state.activity_summary
    return await builder.build(since)

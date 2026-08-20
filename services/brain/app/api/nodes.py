from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.devices.schemas import (
    DeviceCapability,
    DeviceNode,
    DeviceType,
    NodePresence,
    NodeRole,
    NodeVersionInfo,
)
from app.distributed.coordinator import VersionCompatibilityError
from app.distributed.schemas import TaskRequirements

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


class RegisterNodeRequest(BaseModel):
    name: str
    device_type: DeviceType
    platform: str
    roles: list[NodeRole] = []
    capabilities: list[DeviceCapability] = []
    version_info: NodeVersionInfo = NodeVersionInfo()


class HeartbeatRequest(BaseModel):
    presence: dict = {}
    runtime_health: str | None = None


class DispatchRequest(BaseModel):
    task_id: str
    requirements: TaskRequirements = TaskRequirements()
    lease_ttl_seconds: int | None = None


@router.post("/register", response_model=DeviceNode)
async def register_node(payload: RegisterNodeRequest, request: Request) -> DeviceNode:
    """Operator-side registration of deployment nodes (desktop/home
    server): registered nodes become TRUSTED immediately. Untrusted
    client devices (phones/laptops) must go through the explicit
    pairing flow at /api/devices/pair instead."""
    from app.devices.schemas import DeviceTrustLevel

    coordinator = request.app.state.coordinator
    node = DeviceNode(
        name=payload.name,
        device_type=payload.device_type,
        platform=payload.platform,
        capabilities=payload.capabilities,
        roles=payload.roles,
        version_info=payload.version_info,
        trust_level=DeviceTrustLevel.TRUSTED,
    )
    try:
        return await coordinator.register_node(node)
    except VersionCompatibilityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{node_id}/heartbeat")
async def heartbeat(node_id: str, payload: HeartbeatRequest, request: Request) -> dict:
    coordinator = request.app.state.coordinator
    node = await coordinator.record_heartbeat(
        node_id, presence=payload.presence or None, runtime_health=payload.runtime_health,
    )
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown node")
    return {"ok": True, "online": node.online.value, "runtime_health": node.runtime_health}


@router.get("/network")
async def network(request: Request) -> dict:
    coordinator = request.app.state.coordinator
    summary = await coordinator.network_summary()
    return {
        "nodes": [item.model_dump() for item in summary],
        "online_count": sum(1 for item in summary if item.online == "online"),
    }


@router.post("/{node_id}/revoke")
async def revoke_node(node_id: str, request: Request) -> dict:
    state = request.app.state
    node = state.device_registry.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown node")
    await state.device_registry.revoke_and_save(node_id, state.device_pairing)
    invalidated = await state.remote_sessions.invalidate_node(node_id)
    from app.schemas.events import BrainEvent, EventType
    from app.devices.schemas import utc_now

    await state.event_bus.publish(BrainEvent(
        task_id="system", type=EventType.NODE_REVOKED,
        human_readable_message=f"Node {node.name} revoked; credentials and sessions invalidated",
        structured_payload={"node_id": node_id, "sessions_invalidated": invalidated},
    ))
    return {"revoked": True, "sessions_invalidated": invalidated}


@router.post("/dispatch")
async def dispatch_task(payload: DispatchRequest, request: Request) -> dict:
    dispatcher = request.app.state.task_dispatcher
    outcome = await dispatcher.dispatch(payload.task_id, payload.requirements, lease_ttl_seconds=payload.lease_ttl_seconds)
    return outcome.model_dump()


@router.get("/leases/expired")
async def expired_leases(request: Request) -> dict:
    coordinator = request.app.state.coordinator
    handled = await coordinator.handle_expired_leases()
    return {"handled": handled}


@router.post("/pause-everything")
async def pause_everything(request: Request) -> dict:
    return await request.app.state.coordinator.pause_everything()


@router.post("/resume-all")
async def resume_all(request: Request) -> dict:
    return await request.app.state.coordinator.resume_all()

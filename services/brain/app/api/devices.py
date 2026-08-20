from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.devices.authentication import PairingError
from app.devices.schemas import DeviceCapability, DeviceNode, DeviceType, PairingRequest

router = APIRouter(prefix="/api/devices", tags=["devices"])


class PairRequest(BaseModel):
    name: str
    device_type: DeviceType
    platform: str
    requested_capabilities: list[DeviceCapability] = []


@router.post("/pair", response_model=PairingRequest)
async def start_pairing(payload: PairRequest, request: Request) -> PairingRequest:
    pairing = request.app.state.device_pairing
    try:
        return pairing.start_pairing(payload.name, payload.device_type, payload.platform, payload.requested_capabilities)
    except PairingError as error:
        raise HTTPException(status_code=429, detail=str(error)) from error


class ApproveRequest(BaseModel):
    allowed_capabilities: list[DeviceCapability]


@router.post("/pair/{request_id}/approve")
async def approve_pairing(request_id: str, payload: ApproveRequest, request: Request) -> dict:
    pairing = request.app.state.device_pairing
    registry = request.app.state.device_registry
    try:
        node, token = pairing.approve(request_id, allowed_capabilities=payload.allowed_capabilities)
    except PairingError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    registry.register(node)
    return {"node": node.model_dump(mode="json"), "token": token}


@router.get("", response_model=list[DeviceNode])
async def list_devices(request: Request) -> list[DeviceNode]:
    return request.app.state.device_registry.list()


@router.post("/{node_id}/heartbeat")
async def heartbeat(node_id: str, request: Request) -> dict:
    request.app.state.device_heartbeat.record(node_id)
    return {"ok": True}


@router.post("/{node_id}/revoke")
async def revoke(node_id: str, request: Request) -> dict:
    request.app.state.device_registry.revoke(node_id, request.app.state.device_pairing)
    return {"revoked": True}

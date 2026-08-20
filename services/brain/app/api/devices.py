from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.devices.authentication import PairingError
from app.devices.schemas import DeviceCapability, DeviceNode, DeviceType, PairingRequest

router = APIRouter(prefix="/api/devices", tags=["devices"])


def _require_local_operator(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="Pairing approval is allowed only from the local VYOM PC")


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
    _require_local_operator(request)
    pairing = request.app.state.device_pairing
    registry = request.app.state.device_registry
    try:
        node, token = pairing.approve(request_id, allowed_capabilities=payload.allowed_capabilities)
    except PairingError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    await registry.register_and_save(node)
    if pairing.token_store is not None:
        await pairing.token_store.save(node.node_id, pairing._tokens[node.node_id])
    return {"node": node.model_dump(mode="json"), "token": token}


class ClaimRequest(BaseModel):
    code: str


@router.get("/pair/pending")
async def pending_pairings(request: Request) -> list[dict]:
    _require_local_operator(request)
    return [
        item.model_dump(mode="json", exclude={"code"})
        for item in request.app.state.device_pairing.pending()
    ]


@router.post("/pair/{request_id}/claim")
async def claim_pairing(request_id: str, payload: ClaimRequest, request: Request) -> dict:
    try:
        node, token = request.app.state.device_pairing.claim(request_id, payload.code)
    except PairingError as error:
        status = 409 if "waiting" in str(error).lower() else 404
        raise HTTPException(status_code=status, detail=str(error)) from error
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

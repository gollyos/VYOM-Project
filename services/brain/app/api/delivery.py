from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.delivery.package_builder import DeliveryPackage

router = APIRouter(prefix="/api/delivery", tags=["delivery"])


@router.get("/{package_id}", response_model=DeliveryPackage)
async def get_package(package_id: str, request: Request) -> DeliveryPackage:
    try:
        return await request.app.state.delivery_store.get(package_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Delivery package not found") from error


@router.get("", response_model=list[DeliveryPackage])
async def list_packages(request: Request, client: str | None = None) -> list[DeliveryPackage]:
    return await request.app.state.delivery_store.list(client)

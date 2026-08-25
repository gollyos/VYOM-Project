from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.meta_ads.schemas import CampaignCreateRequest, CampaignReceipt, MetaAdsConnectRequest

router = APIRouter(prefix="/api/meta-ads", tags=["meta-ads"])


@router.post("/connect")
async def connect(payload: MetaAdsConnectRequest, request: Request) -> dict:
    provider = request.app.state.meta_ads_provider
    provider.store_credentials(payload.ad_account_id, payload.access_token)
    healthy, error = await provider.health()
    if not healthy:
        await provider.disconnect()
        raise HTTPException(status_code=401, detail=error or "Meta Ads connect failed")
    return {"status": "connected", "ad_account_id": payload.ad_account_id}


@router.post("/disconnect")
async def disconnect(request: Request) -> dict:
    await request.app.state.meta_ads_provider.disconnect()
    return {"status": "disconnected"}


@router.get("/status")
async def status(request: Request) -> dict:
    healthy, error = await request.app.state.meta_ads_provider.health()
    return {"connected": healthy, "detail": error}


@router.post("/campaigns", response_model=CampaignReceipt)
async def create_campaign(payload: CampaignCreateRequest, request: Request) -> CampaignReceipt:
    """Creates a campaign ALWAYS PAUSED with a hard-capped daily budget —
    see MetaAdsProvider's docstring. Activate it manually in Meta Ads
    Manager once you have reviewed it; this endpoint intentionally has no
    'activate' counterpart."""
    try:
        return await request.app.state.meta_ads_service.create_campaign(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

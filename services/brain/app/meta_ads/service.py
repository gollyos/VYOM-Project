from __future__ import annotations

from .provider import MetaAdsProvider
from .schemas import CampaignCreateRequest, CampaignReceipt


class MetaAdsService:
    def __init__(self, provider: MetaAdsProvider) -> None:
        self.provider = provider

    async def create_campaign(self, request: CampaignCreateRequest) -> CampaignReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Meta Ads provider unavailable")
        receipt = await self.provider.create_campaign(request)
        if not receipt.verified or not receipt.campaign_id:
            raise RuntimeError("Meta Ads did not return a verifiable campaign id")
        if receipt.status != "PAUSED":
            # This should be structurally impossible (the provider always
            # forces PAUSED) — treat it as a fatal integrity error rather
            # than silently trusting a receipt that claims otherwise.
            raise RuntimeError(
                f"SAFETY VIOLATION: campaign receipt reports status={receipt.status}, expected PAUSED"
            )
        return receipt

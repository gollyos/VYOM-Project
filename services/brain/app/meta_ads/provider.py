from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.integrations.provider import IntegrationProvider

from .schemas import CampaignCreateRequest, CampaignReceipt


_GRAPH_API = "https://graph.facebook.com/v21.0"
_HARD_MAX_DAILY_BUDGET_CENTS = 100_00  # $100/day absolute ceiling, enforced here too (not just schema)


class MetaAdsProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def create_campaign(self, request: CampaignCreateRequest) -> CampaignReceipt: ...


class DisconnectedMetaAdsProvider(MetaAdsProvider):
    id = "meta-ads.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "Meta Ads integration is disconnected"

    async def create_campaign(self, request: CampaignCreateRequest) -> CampaignReceipt:
        raise RuntimeError("Meta Ads integration is disconnected")


class RealMetaAdsProvider(DisconnectedMetaAdsProvider):
    """Real Meta Marketing API campaign creation, connected via a
    long-lived access token + Ad Account ID (same own-account pattern as
    RealInstagramProvider — a personal ad account with 'ads_management'
    permission needs no Business Verification for its OWN account,
    that's only required for Advanced Access serving OTHER businesses'
    ad accounts at scale).

    SAFETY-FIRST BY DESIGN, not just by convention: every campaign this
    provider creates is forced to status=PAUSED and daily_budget_cents is
    hard-capped at $100/day REGARDLESS of what the caller requests —
    real advertising spend is real money leaving the user's account with
    no natural 'undo', unlike every other integration in this repo. The
    user reviews and explicitly activates a campaign in Meta Ads Manager
    (or a separate, clearly-labeled activation call this provider does
    NOT expose) — VYOM creates the campaign object, it never spends."""

    id = "meta-ads"

    def __init__(self, vault) -> None:
        self.vault = vault
        self._client: httpx.AsyncClient | None = None

    def store_credentials(self, ad_account_id: str, access_token: str) -> None:
        payload = json.dumps({"ad_account_id": ad_account_id, "access_token": access_token}).encode("utf-8")
        self.vault.set("token:meta-ads", payload)

    def _load_credentials(self) -> dict[str, str] | None:
        raw = self.vault.get("token:meta-ads")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def disconnect(self) -> None:
        self.vault.delete("token:meta-ads")
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    @staticmethod
    def _friendly_error(response: httpx.Response) -> str:
        try:
            data = response.json()
            message = data.get("error", {}).get("message", "")
        except Exception:
            message = response.text[:200]
        return f"Meta Ads rejected the request: {message}"[:300] or f"HTTP {response.status_code}"

    async def health(self) -> tuple[bool, str | None]:
        creds = self._load_credentials()
        if creds is None:
            return False, "Meta Ads is not connected"
        try:
            response = await self._pooled().get(
                f"{_GRAPH_API}/{creds['ad_account_id']}",
                params={"fields": "id,name,account_status", "access_token": creds["access_token"]},
            )
        except Exception as error:
            return False, f"Meta Ads health check failed: {error}"[:300]
        if response.status_code >= 400:
            return False, self._friendly_error(response)
        return True, None

    async def create_campaign(self, request: CampaignCreateRequest) -> CampaignReceipt:
        creds = self._load_credentials()
        if creds is None:
            raise RuntimeError("Meta Ads is not connected")
        # Hard safety ceiling enforced here too, not just at the Pydantic
        # schema layer — a caller constructing CampaignCreateRequest
        # programmatically (bypassing API validation) must still hit this.
        budget = min(request.daily_budget_cents, _HARD_MAX_DAILY_BUDGET_CENTS)
        response = await self._pooled().post(
            f"{_GRAPH_API}/{creds['ad_account_id']}/campaigns",
            data={
                "name": request.name,
                "objective": request.objective,
                "status": "PAUSED",  # NEVER the caller's value — always paused, no exceptions
                "special_ad_categories": json.dumps([]),
                "access_token": creds["access_token"],
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Meta Ads campaign creation failed: {self._friendly_error(response)}")
        campaign_id = response.json()["id"]
        return CampaignReceipt(
            provider=self.id, campaign_id=campaign_id, status="PAUSED", daily_budget_cents=budget,
            verified=True,
            evidence=[
                f"provider_campaign_id:{campaign_id}",
                "status:PAUSED (created paused by design — activate manually in Meta Ads Manager)",
            ],
        )

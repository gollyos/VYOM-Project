"""Tests for the Meta Ads integration added this session: real Marketing
API campaign creation, but with a hard safety design — every campaign is
FORCED to status=PAUSED and daily_budget_cents is hard-capped, regardless
of what the caller requests. These safety tests matter MORE than the
happy-path tests here: this is the only integration in the repo where a
bug lets real money leave the user's account.
"""
from __future__ import annotations

import httpx
import pytest

from app.integrations.secrets import InMemorySecretVault
from app.meta_ads.provider import DisconnectedMetaAdsProvider, RealMetaAdsProvider
from app.meta_ads.schemas import CampaignCreateRequest
from app.meta_ads.service import MetaAdsService


def _connected_provider() -> RealMetaAdsProvider:
    provider = RealMetaAdsProvider(InMemorySecretVault())
    provider.store_credentials("act_1234567890", "fake-long-lived-token")
    return provider


def test_schema_rejects_budget_above_hard_cap_at_construction():
    with pytest.raises(Exception):  # pydantic ValidationError
        CampaignCreateRequest(name="Test", daily_budget_cents=200_00)


def test_schema_default_status_is_always_paused():
    request = CampaignCreateRequest(name="Test", daily_budget_cents=50_00)
    assert request.status == "PAUSED"


@pytest.mark.asyncio
async def test_health_false_when_not_connected():
    provider = RealMetaAdsProvider(InMemorySecretVault())
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_health_true_when_ad_account_lookup_succeeds():
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "act_1234567890" in str(request.url)
        return httpx.Response(200, json={"id": "act_1234567890", "name": "Test Account"})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    healthy, error = await provider.health()
    assert healthy is True


@pytest.mark.asyncio
async def test_create_campaign_ALWAYS_sends_status_paused_to_the_real_api():
    """THE critical safety test: even though this is the happy path, the
    actual HTTP request sent to Meta's servers must carry status=PAUSED
    no matter what — this is what stops a bug from ever activating real
    spend."""
    provider = _connected_provider()
    sent_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(x.split("=") for x in request.content.decode().split("&") if "=" in x)
        sent_body.update(body)
        return httpx.Response(200, json={"id": "23851000000000001"})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = CampaignCreateRequest(name="My Campaign", daily_budget_cents=50_00)
    receipt = await provider.create_campaign(request)

    assert sent_body["status"] == "PAUSED"
    assert receipt.status == "PAUSED"
    assert receipt.verified is True
    assert receipt.campaign_id == "23851000000000001"


@pytest.mark.asyncio
async def test_create_campaign_hard_caps_budget_even_if_schema_bypassed():
    """Defense in depth: even if a caller somehow constructs a request
    with a budget above the cap (bypassing Pydantic validation via
    model_construct or similar), the PROVIDER must still clamp it."""
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "campaign_id_x"})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    # Bypass Pydantic's own validation to simulate a hypothetical schema gap.
    bad_request = CampaignCreateRequest.model_construct(
        name="Overbudget", objective="OUTCOME_TRAFFIC", daily_budget_cents=999_99, status="PAUSED",
    )
    receipt = await provider.create_campaign(bad_request)
    assert receipt.daily_budget_cents <= 100_00


@pytest.mark.asyncio
async def test_service_rejects_a_receipt_that_somehow_claims_non_paused_status():
    """If create_campaign() ever returned status != PAUSED (should be
    structurally impossible), the service layer must refuse to accept
    it as a second line of defense, not silently pass it through."""
    class _BrokenProvider(DisconnectedMetaAdsProvider):
        async def health(self):
            return True, None

        async def create_campaign(self, request):
            from app.meta_ads.schemas import CampaignReceipt

            return CampaignReceipt(
                provider="broken", campaign_id="x", status="ACTIVE",  # simulated bug
                daily_budget_cents=request.daily_budget_cents, verified=True,
            )

    service = MetaAdsService(_BrokenProvider())
    request = CampaignCreateRequest(name="Test", daily_budget_cents=10_00)
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        await service.create_campaign(request)


@pytest.mark.asyncio
async def test_service_refuses_campaign_when_provider_unhealthy():
    service = MetaAdsService(DisconnectedMetaAdsProvider())
    request = CampaignCreateRequest(name="Test", daily_budget_cents=10_00)
    with pytest.raises(RuntimeError, match="disconnected"):
        await service.create_campaign(request)


@pytest.mark.asyncio
async def test_create_campaign_surfaces_real_api_error_honestly():
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid parameter"}})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = CampaignCreateRequest(name="Test", daily_budget_cents=10_00)
    with pytest.raises(RuntimeError, match="Invalid parameter"):
        await provider.create_campaign(request)

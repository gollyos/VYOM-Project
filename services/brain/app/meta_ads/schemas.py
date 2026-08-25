from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MetaAdsConnectRequest(BaseModel):
    ad_account_id: str  # "act_1234567890"
    access_token: str


class CampaignCreateRequest(BaseModel):
    name: str
    objective: str = "OUTCOME_TRAFFIC"
    daily_budget_cents: int = Field(..., gt=0, le=100_00)  # hard cap: max $100/day, enforced below too
    #: ALWAYS created PAUSED — VYOM never spends real ad budget without
    #: the user separately, explicitly flipping it live in Meta Ads
    #: Manager or via a distinct, clearly-labeled 'activate' call.
    status: str = "PAUSED"


class CampaignReceipt(BaseModel):
    provider: str
    campaign_id: str
    status: str
    daily_budget_cents: int
    created_at: datetime = Field(default_factory=utc_now)
    verified: bool
    evidence: list[str] = Field(default_factory=list)

from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class MetaAdsTool(BaseTool):
    """Create a Meta (Facebook/Instagram) ad campaign — ALWAYS created
    PAUSED with a hard-capped daily budget; see MetaAdsProvider's
    docstring for why. L2 — real ad spend is real money leaving the
    user's account, the highest-consequence action tier in this repo."""

    metadata = ToolMetadata(
        name="meta_ads",
        description=(
            "Create a Meta Ads campaign (name, objective, daily_budget_cents — hard-capped at "
            "$100/day). ALWAYS created PAUSED — VYOM never activates real ad spend; the user "
            "reviews and activates it manually in Meta Ads Manager. Requires Meta Ads to be "
            "connected first. L2 — requires explicit approval."
        ),
        category="content",
        required_permissions=[PermissionLevel.L2],
        risk_level="high",
    )

    def __init__(self, service) -> None:
        self.service = service

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L2

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        from app.meta_ads.schemas import CampaignCreateRequest

        name = str(inputs.get("name", "")).strip()
        if not name:
            raise ToolValidationError("name is required")
        try:
            budget = int(inputs.get("daily_budget_cents", 0))
        except (TypeError, ValueError):
            raise ToolValidationError("daily_budget_cents must be an integer number of cents")
        if budget <= 0:
            raise ToolValidationError("daily_budget_cents must be a positive number of cents")
        request = CampaignCreateRequest(
            name=name, objective=str(inputs.get("objective", "OUTCOME_TRAFFIC")),
            daily_budget_cents=min(budget, 100_00),
        )
        receipt = await self.service.create_campaign(request)
        return ToolResult.completed(
            f"Created Meta Ads campaign '{name}' (id={receipt.campaign_id}, status=PAUSED — "
            "review and activate manually in Meta Ads Manager)",
            output=receipt.model_dump(mode="json"),
            evidence=[EvidenceItem(
                type="tool_result", summary="Meta Ads campaign created (paused)",
                data={"campaign_id": receipt.campaign_id, "status": receipt.status},
            )],
        )

    async def health(self) -> dict[str, Any]:
        healthy, error = await self.service.provider.health()
        return {"healthy": healthy, "reason": error or "connected"}

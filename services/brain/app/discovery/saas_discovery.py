from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.research.orchestrator import DeepResearchTask, EmitFn
from app.research.schemas import ResearchDepth, SourceType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SaaSCandidate(BaseModel):
    name: str
    capabilities: list[str] = Field(default_factory=list)
    price_notes: str = ""
    has_free_tier: bool | None = None
    has_api: bool | None = None
    has_mcp: bool | None = None
    privacy_notes: str = ""
    limits_notes: str = ""
    integration_effort: str = "unknown"
    reliability_notes: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class Subscription(BaseModel):
    """A user-owned tool/subscription. No financial or card information is
    stored here; the point is to avoid recommending a new paid tool when an
    existing subscription already solves the need."""

    service: str
    plan: str = ""
    status: str = "active"
    capabilities: list[str] = Field(default_factory=list)
    usage_limits: str = ""
    renewal: str = ""
    cost_notes: str = ""
    integration_method: str = "none"
    updated_at: datetime = Field(default_factory=utc_now)


class SubscriptionRegistry:
    def __init__(self, subscriptions: list[Subscription] | None = None):
        self._subscriptions: dict[str, Subscription] = {sub.service.lower(): sub for sub in (subscriptions or [])}

    def add(self, subscription: Subscription) -> Subscription:
        self._subscriptions[subscription.service.lower()] = subscription
        return subscription

    def get(self, service: str) -> Subscription | None:
        return self._subscriptions.get(service.lower())

    def list(self) -> list[Subscription]:
        return list(self._subscriptions.values())

    def find_capable(self, capability_hint: str) -> list[Subscription]:
        hint = capability_hint.lower()
        return [
            sub for sub in self._subscriptions.values()
            if sub.status == "active" and any(hint in capability.lower() or capability.lower() in hint for capability in sub.capabilities)
        ]


class SaaSDiscovery:
    """Capability need -> research alternatives -> compare. Does not
    automatically subscribe to anything."""

    def __init__(self, research_task: DeepResearchTask):
        self.research_task = research_task

    async def discover(
        self,
        need: str,
        *,
        depth: ResearchDepth = ResearchDepth.STANDARD,
        emit: EmitFn | None = None,
    ) -> list[SaaSCandidate]:
        result = await self.research_task.run(
            f"Best tools/SaaS for: {need}",
            depth=depth,
            required_facts=["capabilities", "price", "free tier", "API availability", "privacy"],
            preferred_sources=[SourceType.COMPANY, SourceType.COMMUNITY],
            emit=emit,
        )
        candidates: list[SaaSCandidate] = []
        seen_names: set[str] = set()
        for source in result.sources:
            name = source.publisher if source.publisher not in {"unknown", "local-fixture"} else source.title
            if name in seen_names:
                continue
            seen_names.add(name)
            candidates.append(SaaSCandidate(
                name=name,
                capabilities=[need],
                evidence=[f"{source.title} ({source.url})"],
                confidence=source.trust_score,
            ))
        if emit:
            await emit("saas_discovered", f"Found {len(candidates)} SaaS candidate(s) for {need}", {"need": need, "count": len(candidates)})
        return candidates

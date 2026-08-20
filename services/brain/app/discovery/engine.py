from __future__ import annotations

from typing import Any

from app.capabilities.registry import CapabilityRegistry
from app.research.orchestrator import DeepResearchTask, EmitFn

from .api_discovery import APIDiscovery
from .capability_gap import CapabilityGapDetector
from .evaluator import ToolEvaluator
from .mcp_discovery import MCPCatalog, MCPDiscoveryEngine
from .recommendation import DiscoveryRecommendation, RecommendationEngine
from .saas_discovery import SaaSDiscovery, SubscriptionRegistry


class DiscoveryEngine:
    """Top-level facade used by the runtime/API layer for capability,
    API, MCP, and SaaS discovery."""

    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        research_task: DeepResearchTask,
        subscriptions: SubscriptionRegistry | None = None,
        mcp_registry: Any = None,
    ):
        self.subscriptions = subscriptions or SubscriptionRegistry()
        self.recommendation_engine = RecommendationEngine(
            gap_detector=CapabilityGapDetector(capability_registry),
            subscriptions=self.subscriptions,
            saas_discovery=SaaSDiscovery(research_task),
            api_discovery=APIDiscovery(research_task),
            mcp_discovery=MCPDiscoveryEngine(MCPCatalog(), mcp_registry),
            evaluator=ToolEvaluator(),
        )

    async def discover(self, goal: str, *, emit: EmitFn | None = None) -> DiscoveryRecommendation:
        return await self.recommendation_engine.recommend(goal, emit=emit)

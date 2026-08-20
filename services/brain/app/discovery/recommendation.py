from __future__ import annotations

from dataclasses import dataclass, field

from app.research.orchestrator import EmitFn

from .api_discovery import APICandidate, APIDiscovery
from .capability_gap import CapabilityGapDetector, CapabilityGapReport
from .evaluator import EvaluationScore, ToolEvaluator
from .mcp_discovery import MCPCandidate, MCPDiscoveryEngine
from .saas_discovery import SaaSDiscovery, Subscription, SubscriptionRegistry


@dataclass
class DiscoveryRecommendation:
    goal: str
    gap_report: CapabilityGapReport
    existing_subscription: Subscription | None = None
    saas_candidates: list[EvaluationScore] = field(default_factory=list)
    api_candidate: APICandidate | None = None
    mcp_candidates: list[MCPCandidate] = field(default_factory=list)
    recommendation: str = ""


class RecommendationEngine:
    """Goal -> Capability Registry -> existing tool? -> existing MCP? ->
    existing API? -> existing SaaS subscription? -> browser workflow? ->
    custom skill required? VYOM never auto-subscribes or auto-installs."""

    def __init__(
        self,
        gap_detector: CapabilityGapDetector,
        subscriptions: SubscriptionRegistry,
        saas_discovery: SaaSDiscovery,
        api_discovery: APIDiscovery,
        mcp_discovery: MCPDiscoveryEngine,
        evaluator: ToolEvaluator,
    ):
        self.gap_detector = gap_detector
        self.subscriptions = subscriptions
        self.saas_discovery = saas_discovery
        self.api_discovery = api_discovery
        self.mcp_discovery = mcp_discovery
        self.evaluator = evaluator

    async def recommend(self, goal: str, *, emit: EmitFn | None = None) -> DiscoveryRecommendation:
        gap_report = self.gap_detector.check(goal)
        if gap_report.has_existing_capability:
            return DiscoveryRecommendation(
                goal=goal, gap_report=gap_report,
                recommendation=f"VYOM already has a capability that covers this: {gap_report.matched[0].name}.",
            )

        existing = self.evaluator.prefer_existing_subscription(goal, self.subscriptions.list())
        if existing:
            return DiscoveryRecommendation(
                goal=goal, gap_report=gap_report, existing_subscription=existing,
                recommendation=f"An existing subscription ({existing.service}) already covers this need; no new tool is recommended.",
            )

        mcp_candidates = self.mcp_discovery.discover(goal)
        api_candidate = await self.api_discovery.discover(goal, emit=emit)
        saas_candidates = await self.saas_discovery.discover(goal, emit=emit)
        scored = self.evaluator.evaluate_saas(saas_candidates)

        if mcp_candidates:
            recommendation = f"A restricted-trust MCP candidate exists ({mcp_candidates[0].name}); it requires approval and security review before connection."
        elif api_candidate.has_official_api:
            recommendation = f"{goal} appears to expose an official API; prefer it over browser automation once credentials are configured."
        elif scored:
            recommendation = f"Top researched option: {scored[0].candidate} (score {scored[0].score})."
        else:
            recommendation = "No reliable existing capability, subscription, MCP, or API was found; a bounded browser workflow or a new skill may be required."

        if emit:
            await emit("capability_gap_detected", f"Capability gap for '{goal}' resolved", {"recommendation": recommendation})

        return DiscoveryRecommendation(
            goal=goal, gap_report=gap_report, saas_candidates=scored,
            api_candidate=api_candidate, mcp_candidates=mcp_candidates, recommendation=recommendation,
        )

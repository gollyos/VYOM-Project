from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolChoice:
    tool: str | None
    reason: str
    evidence: dict


class LearnedRouter:
    """Phase 16 evidence layer. It does NOT replace the Model Router,
    Capability Registry, or Tool Registry — it adds historical
    performance evidence from real Phase 14 experiences so existing
    routing considers: capability, health, permissions, context,
    historical success, verification quality, latency, cost, recent
    failures, and environment similarity."""

    def __init__(self, learner, minimum_samples: int = 2):
        self.learner = learner                # AdaptiveLearner (Phase 14)
        self.minimum_samples = minimum_samples

    # -- tool learning ------------------------------------------------------------

    async def preferred_tool(self, candidates: list[str], conditions: dict) -> ToolChoice:
        """Evidence-based tool preference, e.g. Defuddle on static
        pages vs Playwright after Defuddle failures on JS-heavy pages.
        Never runs multiple expensive tools when a known-good route
        exists; falls back to None (caller's default order) when
        evidence is thin."""
        performance = await self.learner.tool_performance()
        condition_key = str(conditions.get("site_type", conditions.get("condition", "default")))
        best, best_score, evidence = None, None, {}
        for candidate in candidates:
            stats = performance.get(candidate)
            if not stats:
                continue
            bucket = stats["by_condition"].get(condition_key)
            rate, sample = (bucket["rate"], bucket["uses"]) if bucket else (stats["rate"], stats["uses"])
            if sample < self.minimum_samples:
                continue  # one lucky run must not decide routing
            score = rate - 0.001 * (stats.get("avg_latency_ms", 0) or 0) / 1000
            if best_score is None or score > best_score:
                best, best_score = candidate, score
                evidence = {"tool": candidate, "rate": rate, "samples": sample,
                            "condition": condition_key, "recent_failures": stats["uses"] - stats["wins"]}
        if best is None:
            return ToolChoice(None, "insufficient evidence — using default routing order", {})
        return ToolChoice(best, (
            f"{best} succeeded {evidence['rate']:.0%} over {evidence['samples']} recorded uses "
            f"under matching conditions"), evidence)

    # -- model learning --------------------------------------------------------------

    def model_bias(self, model_id: str, domain: str, performance: dict | None = None) -> tuple[float, str]:
        """Context-specific bias for the EXISTING Model Router's score:
        positive for historically strong model+domain pairs, negative
        for failure-prone ones, 0 without evidence. Never one global
        best-model — always per-context."""
        stats = (performance or {}).get(model_id)
        if not stats:
            return 0.0, ""
        domain_stats = stats.get("domains", {}).get(domain)
        if not domain_stats or domain_stats["calls"] < self.minimum_samples:
            return 0.0, ""
        bias = (domain_stats["rate"] - 0.5) * 20  # ±10 points max
        return bias, f"learned: {model_id} at {domain_stats['rate']:.0%} in {domain} ({domain_stats['calls']} calls)"

    # -- strategy check ----------------------------------------------------------------

    async def strategy_check(self, goal: str, domain: str, environment: dict, conditions: dict):
        """REUSE / ADAPT / REPLAN against current conditions — delegates
        to the Phase 14 StrategyEngine; never reuses merely because it
        worked before."""
        return await self.learner.strategies.decide_reuse(goal, domain, environment, conditions, self.learner.store)

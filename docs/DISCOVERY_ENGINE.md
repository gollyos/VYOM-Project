# VYOM Discovery Engine

## Purpose

`DiscoveryEngine` / `RecommendationEngine`
(`services/brain/app/discovery/`) answers "can VYOM already do this?" before
reaching for a new integration:

```text
Goal
  -> Capability Registry (existing tool/skill/agent/model?)
  -> Existing subscription? (SubscriptionRegistry)
  -> Existing MCP candidate? (MCPDiscoveryEngine, restricted trust)
  -> Existing/official API? (APIDiscovery)
  -> Existing SaaS alternative? (SaaSDiscovery + ToolEvaluator)
  -> Recommendation (never auto-installs/auto-subscribes/auto-connects)
```

## Capability gap detection

`CapabilityGapDetector.check` reuses the Phase 6 `CapabilityRegistry`
(tools, models, skills, agents, integrations). A match here means VYOM
already has a working, available capability — the flow stops immediately
with `has_existing_capability=True` rather than proposing new work.

## Subscription registry

`SubscriptionRegistry` is a private registry of user-owned tools/plans
(`service, plan, status, capabilities, usage_limits, renewal, cost_notes,
integration_method`). No financial or card information is stored. If an
active subscription's capabilities already cover the need,
`RecommendationEngine` recommends using it instead of a new tool.

## MCP discovery

`MCPCatalog` is a small, explicitly curated local list of publicly known
MCP servers — VYOM does not scan the network to discover MCP servers.
Every `MCPCandidate` carries `name, source, capabilities, publisher, trust,
required_permissions, installation_method, risks`. Trust always starts
`restricted`; discovery never elevates trust, and a candidate must pass
approval/security review before connection (see
`docs/MCP_ARCHITECTURE.md`).

## API discovery

`APIDiscovery` runs a bounded `DeepResearchTask` scoped to
`authentication, endpoints, rate limits, pricing, documentation` and
reports whether official/documentation sources were found. VYOM does not
automatically store third-party API credentials; a positive result is a
recommendation to prefer the official API over browser automation, not a
configured integration.

## SaaS / subscription discovery

`SaaSDiscovery` researches alternatives and `ToolEvaluator` scores them on
capabilities, price, free tier, API availability, MCP availability,
privacy, limits, integration effort, and reliability. VYOM never
auto-subscribes; the result is a ranked comparison and a recommendation
only.

## Preferred integration order

official API → official SDK → trusted/restricted MCP → browser automation
→ ask the user, matching the order in `docs/VYOM_PROJECT_MEMORY.md`'s tool
direction.

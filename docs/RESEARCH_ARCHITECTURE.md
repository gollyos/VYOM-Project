# VYOM Research Architecture

## Purpose

Deep research is a bounded, evidence-bound workflow, not a single search
query. `DeepResearchTask` (`services/brain/app/research/orchestrator.py`)
runs:

```text
goal
  -> plan (QueryPlanner)
  -> discover sources (SourceDiscovery)
  -> rank sources (SourceRanker)
  -> read + evaluate freshness (FreshnessPolicy)
  -> extract claims (ClaimExtractor)
  -> cross-check (ContradictionDetector)
  -> identify gaps
  -> synthesize (ResearchSynthesizer)
  -> verify (ResearchVerifier)
  -> build citations (CitationBuilder)
  -> ResearchResult
```

One search query is never treated as equivalent to research; `QueryPlanner`
always expands a goal into multiple bounded questions before any source is
read.

## Research plan and depth

`ResearchPlan` carries `goal`, `questions`, `required_facts`,
`preferred_sources`, `source_diversity`, `freshness_requirement`, `depth`,
`budget`, and `stop_conditions`. Depth is `quick`, `standard`, `deep`, or
`exhaustive`. Defaults and per-depth budgets live in `config/research.yaml`.
An unscoped `exhaustive` request (no `required_facts`) is downgraded to
`deep`; exhaustive research is reserved for explicitly high-value goals.

## Source model

`Source` records `source_id`, `url`, `title`, `publisher`, `source_type`,
`retrieved_at`, `published_at`, `freshness`, `trust_score`,
`relevance_score`, `primary_or_secondary`, `claims_supported`, and
`conflicts`. `SourceType` is one of `official`, `documentation`,
`research_paper`, `government`, `company`, `news`, `database`, `community`,
`social`, `unknown`. See `docs/SOURCE_TRUST_POLICY.md` for ranking weights.

## Claim and evidence model

Every `Claim` keeps `supporting_sources` and `contradicting_sources` so
"where did this come from?" always has an answer. A claim with no
supporting source is never cited; `CitationBuilder.mark_uncertain` caps its
confidence instead of dropping it silently.

## Contradiction detection

`ContradictionDetector` groups claims by their `required_fact` and flags
pairs whose statements contain different numeric values. Disagreements are
recorded as a `Contradiction` (source A, source B, difference, possible
reason, recommended interpretation, confidence) and surfaced to the user —
never silently resolved by picking one side.

## Freshness

`FreshnessPolicy` compares `retrieved_at` against `published_at` using a
depth-appropriate `stale_after` window (`config/research.yaml`). A source
with `freshness_requirement=fresh` that exceeds the time-sensitive window is
marked `stale` and is not treated as sufficient for a current-decision
claim.

## Budgets

`ResearchBudget` bounds `max_queries`, `max_sources`, `max_model_calls`,
`max_browser_time_seconds`, `max_cost`, and `max_runtime_seconds` per depth.
`QueryPlanner.generate_queries` and `SourceDiscovery.discover` both enforce
their bound; research stops once the budget is exhausted rather than
looping indefinitely.

## Search providers

`SourceDiscovery` is provider-pluggable (`SearchProvider` protocol):

- `LocalFixtureSearchProvider` — deterministic, offline, always labels
  `publisher="local-fixture"`. Enabled by default so research always has an
  honest, non-live fallback and automated tests never need network access.
- `BrowserSearchProvider` — routes a query through the Browser Agent to a
  real search engine. Disabled by default in `config/research.yaml`;
  requires real network access and is never used in automated tests.
- `DisconnectedSearchProvider` — the honest default when no provider is
  configured.

## Web Intelligence layer

`services/brain/app/web_intelligence/` contains thin, domain-specific
wrappers (`company_research`, `competitor_research`, `product_research`,
`market_research`, `technology_research`, `trend_analysis`) that build a
`ResearchPlan` with domain-appropriate `required_facts`/`preferred_sources`
and delegate execution to `DeepResearchTask`. They add no execution logic of
their own.

## Runtime integration

`Phase8Engine` (`services/brain/app/phase8/engine.py`) is the Task Runtime
delegate for research/discovery/booking/artifact/delivery intents, mirroring
`BusinessEngine`/`IntelligenceEngine`. It never calls a paid model for
orchestration; deterministic classification, planning, and composition stay
free, matching the Omni Model Router principle of using the cheapest
reliable path.

## Model routing note

`ResearchSynthesizer` produces a deterministic template synthesis by
default so research never depends on a paid model to produce a result. A
routed provider may be used by a caller to enrich synthesis text, but the
deterministic path remains authoritative for verification.

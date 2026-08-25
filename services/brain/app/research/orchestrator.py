from __future__ import annotations

from typing import Any, Awaitable, Callable

import yaml

from .citation_builder import CitationBuilder
from .contradiction import ContradictionDetector
from .extractor import ClaimExtractor
from .freshness import FreshnessPolicy
from .query_planner import QueryPlanner
from .schemas import Freshness, ResearchDepth, ResearchPlan, ResearchResult, SourceType
from .source_discovery import BrowserSearchProvider, LocalFixtureSearchProvider, SearchProvider, SerpApiSearchProvider, SourceDiscovery
from .source_ranker import SourceRanker
from .synthesizer import ResearchSynthesizer
from .verifier import ResearchVerifier

EmitFn = Callable[[str, str, dict[str, Any]], Awaitable[None]]


async def _noop_emit(event_type: str, message: str, payload: dict[str, Any]) -> None:
    return None


class DeepResearchTask:
    """Runs the full research flow:

    goal -> plan -> discover -> rank -> read -> extract -> cross-check ->
    identify contradictions -> fill gaps -> synthesize -> verify ->
    citations -> present.

    One search query is never equated with completed research.
    """

    def __init__(
        self,
        query_planner: QueryPlanner,
        source_discovery: SourceDiscovery,
        source_ranker: SourceRanker,
        extractor: ClaimExtractor,
        contradiction_detector: ContradictionDetector,
        freshness_policy: FreshnessPolicy,
        synthesizer: ResearchSynthesizer,
        citation_builder: CitationBuilder,
        verifier: ResearchVerifier,
        defuddle_extractor: Any = None,
        knowledge_service: Any = None,
    ):
        self.query_planner = query_planner
        self.source_discovery = source_discovery
        self.source_ranker = source_ranker
        self.extractor = extractor
        self.contradiction_detector = contradiction_detector
        self.freshness_policy = freshness_policy
        self.synthesizer = synthesizer
        self.citation_builder = citation_builder
        self.verifier = verifier
        # Optional: when set, each ranked source is actually read through
        # the learned Defuddle/Playwright extractor (now bounded/worker-
        # isolated - see BrowserSession) instead of relying only on
        # discovery-time snippets, and every read feeds Phase 14 learning.
        # Absent by default - behavior is unchanged for callers that never
        # wire it in.
        self.defuddle_extractor = defuddle_extractor
        # Optional: app/knowledge.KnowledgeService. When set, every
        # source actually read (real extraction, non-fixture) has
        # candidate facts pulled from its clean text and persisted to
        # the knowledge base with the real source_url as evidence -
        # deepening research into VYOM's own permanent, queryable
        # general-knowledge store. Absent by default - unchanged
        # behavior for callers that never wire it in.
        self.knowledge_service = knowledge_service

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        *,
        browser_actions: Any = None,
        defuddle_extractor: Any = None,
        knowledge_service: Any = None,
        serpapi_key: str | None = None,
    ) -> "DeepResearchTask":
        query_planner = QueryPlanner.from_config(config)
        source_ranker = SourceRanker.from_config(config)
        freshness_policy = FreshnessPolicy.from_config(config)

        providers: list[SearchProvider] = []
        search_config = config.get("search_providers", {})
        browser_config = search_config.get("browser_search", {})
        # Provider PRIORITY (minimize paid SerpAPI spam): the FREE real
        # browsing path (actual Google/DuckDuckGo results via the browser
        # tool) is tried FIRST; the PAID SerpAPI key is a FALLBACK — only
        # invoked when the browser path yields zero results or errors, so
        # every research task doesn't silently burn paid quota. LocalFixture
        # is the clearly-labelled offline/demo last resort.
        if browser_config.get("enabled") and browser_actions is not None:
            providers.append(BrowserSearchProvider(browser_actions, browser_config.get(
                "search_url_template", "https://duckduckgo.com/html/?q={query}",
            )))
        # SerpAPI (real Google JSON) — only consulted as a fallback when
        # the free browser path above came up empty. If you set
        # search_providers.serpapi.priority: primary (see config/research.yaml)
        # it moves ahead of browser_search instead (explict opt-in).
        serpapi_config = search_config.get("serpapi", {})
        if serpapi_config.get("enabled", True) and serpapi_key:
            if serpapi_config.get("priority") == "primary":
                providers.insert(0, SerpApiSearchProvider(serpapi_key))
            else:
                providers.append(SerpApiSearchProvider(serpapi_key))
        if search_config.get("local_fixture", {}).get("enabled", True):
            providers.append(LocalFixtureSearchProvider())
        source_discovery = SourceDiscovery(providers)

        return cls(
            query_planner=query_planner,
            source_discovery=source_discovery,
            source_ranker=source_ranker,
            extractor=ClaimExtractor(),
            contradiction_detector=ContradictionDetector(),
            freshness_policy=freshness_policy,
            synthesizer=ResearchSynthesizer(),
            citation_builder=CitationBuilder(),
            verifier=ResearchVerifier(),
            defuddle_extractor=defuddle_extractor,
            knowledge_service=knowledge_service,
        )

    @staticmethod
    def load_config(path) -> dict[str, Any]:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    async def run(
        self,
        goal: str,
        *,
        depth: ResearchDepth | None = None,
        required_facts: list[str] | None = None,
        preferred_sources: list[SourceType] | None = None,
        freshness_requirement: Freshness = Freshness.UNKNOWN,
        emit: EmitFn | None = None,
        synthesis_provider=None,
        synthesis_model: str | None = None,
    ) -> ResearchResult:
        emit = emit or _noop_emit
        await emit("research_started", f"Planning research for: {goal}", {"goal": goal})

        plan = self.query_planner.build_plan(
            goal, depth=depth, required_facts=required_facts,
            preferred_sources=preferred_sources, freshness_requirement=freshness_requirement,
        )
        await emit("research_plan_ready", f"Research plan ready ({plan.depth.value})", {"plan": plan.model_dump(mode="json")})

        queries = self.query_planner.generate_queries(plan)
        sources = await self.source_discovery.discover(plan, queries)
        for source in sources:
            await emit("source_discovered", f"Found source: {source.title}", {"source_id": source.source_id, "url": source.url})

        ranked_sources = self.source_ranker.rank(sources, plan)[: plan.budget.max_sources]
        for source in ranked_sources:
            self.freshness_policy.evaluate(source, plan.freshness_requirement)
            # Only ever read a source for real when it came from a real
            # provider. local-fixture sources are deliberately synthetic
            # (docs.example.test placeholders) and must never trigger a
            # live fetch or browser navigation - that would break the
            # documented "no live network call" guarantee of offline
            # research. Real reads are bounded by BrowserSession's own
            # worker-thread isolation + timeout, so a stuck read can
            # never block this loop either.
            if self.defuddle_extractor is not None and source.url and source.publisher != "local-fixture":
                try:
                    extraction = await self.defuddle_extractor.extract(source.url)
                except Exception:
                    extraction = None
                if extraction is not None and extraction.success and extraction.content:
                    source.excerpt = extraction.content[:2000]
                    # Deepen research into VYOM's permanent knowledge base:
                    # candidate facts are extracted from the SAME clean
                    # text just read and persisted with this source's real
                    # url as evidence. Never blocks/fails the research run.
                    if self.knowledge_service is not None:
                        try:
                            recorded = await self.knowledge_service.record_facts_from_text(
                                text=extraction.content, source_url=source.url,
                                source_title=source.title, subject_hint=plan.goal,
                            )
                            if recorded:
                                await emit(
                                    "claim_extracted", f"Learned {len(recorded)} fact(s) from {source.title}",
                                    {"source_id": source.source_id, "fact_count": len(recorded)},
                                )
                        except Exception:
                            pass
            await emit("source_read", f"Read source: {source.title}", {"source_id": source.source_id, "trust_score": source.trust_score})

        claims = self.extractor.extract(ranked_sources, plan)
        for claim in claims:
            await emit("claim_extracted", claim.statement[:120], {"claim_id": claim.claim_id, "required_fact": claim.required_fact})

        contradictions = self.contradiction_detector.detect(claims, ranked_sources)
        for contradiction in contradictions:
            await emit("contradiction_found", f"Contradiction on {contradiction.claim}", contradiction.model_dump(mode="json"))

        gaps = self._identify_gaps(plan, claims)
        claims = self.citation_builder.mark_uncertain(claims)
        # Model-written synthesis over the SAME extracted claims when a
        # provider is offered; the deterministic template is the fallback
        # and the only path when none is wired (offline guarantee holds).
        synthesis = await self.synthesizer.synthesize_async(
            plan, claims, contradictions, gaps,
            provider=synthesis_provider, model=synthesis_model,
        )
        citations = self.citation_builder.build(claims, ranked_sources)

        result = ResearchResult(
            plan=plan, sources=ranked_sources, claims=claims,
            contradictions=contradictions, synthesis=synthesis,
            gaps=gaps, citations=citations,
        )
        result = self.verifier.verify(result)
        await emit(
            "research_verified", "Research verification complete",
            {"research_id": result.id, "verification_state": result.verification_state.value, "confidence": result.confidence},
        )
        return result

    @staticmethod
    def _identify_gaps(plan: ResearchPlan, claims: list) -> list[str]:
        covered = {claim.required_fact for claim in claims if claim.supporting_sources}
        return [fact for fact in plan.required_facts if fact not in covered]

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceType(str, Enum):
    OFFICIAL = "official"
    DOCUMENTATION = "documentation"
    RESEARCH_PAPER = "research_paper"
    GOVERNMENT = "government"
    COMPANY = "company"
    NEWS = "news"
    DATABASE = "database"
    COMMUNITY = "community"
    SOCIAL = "social"
    UNKNOWN = "unknown"


class Freshness(str, Enum):
    FRESH = "fresh"
    RECENT = "recent"
    STALE = "stale"
    UNKNOWN = "unknown"


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    INFERRED = "inferred"
    VERIFIED = "verified"


class ResearchDepth(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"
    EXHAUSTIVE = "exhaustive"


class ResearchBudget(BaseModel):
    max_queries: int = 4
    max_sources: int = 8
    max_model_calls: int = 2
    max_browser_time_seconds: int = 90
    max_cost: float = 0.10
    max_runtime_seconds: int = 120


class ResearchPlan(BaseModel):
    id: str = Field(default_factory=lambda: f"plan_{uuid4().hex}")
    goal: str
    questions: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    preferred_sources: list[SourceType] = Field(default_factory=list)
    source_diversity: int = 2
    freshness_requirement: Freshness = Freshness.UNKNOWN
    depth: ResearchDepth = ResearchDepth.STANDARD
    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    stop_conditions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class Source(BaseModel):
    source_id: str = Field(default_factory=lambda: f"src_{uuid4().hex}")
    url: str
    title: str
    publisher: str
    source_type: SourceType = SourceType.UNKNOWN
    retrieved_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    freshness: Freshness = Freshness.UNKNOWN
    trust_score: float = 0.0
    relevance_score: float = 0.0
    primary_or_secondary: str = "secondary"
    claims_supported: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    excerpt: str = ""


class Claim(BaseModel):
    claim_id: str = Field(default_factory=lambda: f"claim_{uuid4().hex}")
    statement: str
    confidence: float = 0.5
    supporting_sources: list[str] = Field(default_factory=list)
    contradicting_sources: list[str] = Field(default_factory=list)
    freshness: Freshness = Freshness.UNKNOWN
    verification_state: VerificationState = VerificationState.UNVERIFIED
    required_fact: str | None = None


class Contradiction(BaseModel):
    contradiction_id: str = Field(default_factory=lambda: f"contra_{uuid4().hex}")
    claim: str
    source_a: str
    source_b: str
    difference: str
    possible_reason: str
    recommended_interpretation: str
    confidence: float = 0.5


class ResearchResult(BaseModel):
    id: str = Field(default_factory=lambda: f"research_{uuid4().hex}")
    plan: ResearchPlan
    sources: list[Source] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    synthesis: str = ""
    gaps: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    citations: list[str] = Field(default_factory=list)
    verification_state: VerificationState = VerificationState.UNVERIFIED
    generated_at: datetime = Field(default_factory=utc_now)

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeFact(BaseModel):
    """One discrete fact VYOM has learned, e.g.

    subject="Python programming language", predicate="created by",
    value="Guido van Rossum", source_url="https://python.org/...".

    This is the row-level record behind the 'khud ka Wikipedia': every
    fact carries real source evidence, a confidence, and the two
    timestamps that drive staleness (first_learned_at is permanent
    provenance, last_confirmed_at moves forward every time the fact is
    re-seen so a still-true fact never looks stale just because it is
    old).
    """

    id: str = Field(default_factory=lambda: f"fact_{uuid4().hex}")
    subject: str = Field(min_length=1, max_length=300)
    predicate: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=4000)
    #: Which agent/task-type this fact belongs to (its own 'wiki'). Every
    #: distinct capability (research, coding, email, video, market data,
    #: ...) accumulates and improves its own namespace independently
    #: instead of all facts mixing into one undifferentiated pool. Facts
    #: default to the 'general' namespace so existing unscoped callers
    #: keep working unchanged.
    domain: str = Field(default="general", max_length=64)
    source_url: str | None = None
    source_title: str | None = None
    confidence: float = Field(default=0.6, ge=0, le=1)
    first_learned_at: datetime = Field(default_factory=utc_now)
    last_confirmed_at: datetime = Field(default_factory=utc_now)
    #: When the VALUE itself last actually changed (distinct from
    #: last_confirmed_at, which advances on every re-confirmation even
    #: when the value is unchanged). This is the missing "which newer
    #: thing replaced this, and when" the reel's memory-lifecycle
    #: critique names: last_confirmed_at alone cannot answer "how long
    #: has the CURRENT value specifically been true", only "how
    #: recently was this subject looked at". Defaults to
    #: first_learned_at so a fact's very first value counts as having
    #: "changed" at creation.
    value_changed_at: datetime = Field(default_factory=utc_now)
    confirmations: int = 1
    task_id: str | None = None
    memory_id: str | None = None  # links to the MemoryEntry that carries this fact for FTS/embedding recall
    #: Karpathy-style contradiction handling. When a re-record finds a
    #: DIFFERENT value for the same (subject, predicate, domain), VYOM no
    #: longer silently overwrites: it flags the fact as contradicted and
    #: notes both values/sources so lint can surface it for review. A
    #: newer, more-confident source can still supersede, but the conflict
    #: is never silently dropped.
    contradicted: bool = False
    contradiction_count: int = 0
    #: How many re-confirmations in a row have agreed with the CURRENT
    #: value since the last contradiction. A fact stays "contradicted"
    #: forever otherwise, even after the world settles and every
    #: subsequent research pass agrees - which trains the user to
    #: distrust lint's contradiction list once it fills with
    #: long-since-resolved noise. Reset to 0 on every new contradiction;
    #: auto-clears `contradicted` once it reaches
    #: CONTRADICTION_AUTO_RESOLVE_THRESHOLD agreeing re-confirmations.
    consistent_reconfirmations: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_sentence(self) -> str:
        return f"{self.subject} {self.predicate} {self.value}".strip()

    #: Re-confirmations agreeing with the CURRENT value needed to
    #: auto-clear a contradiction flag. Not "the disagreement never
    #: happened" (contradiction_count and prior_values in metadata
    #: still carry that history permanently) - only "this is no longer
    #: an OPEN conflict needing review", the same distinction a real
    #: wiki draws between an edit-war flag and its resolution.
    CONTRADICTION_AUTO_RESOLVE_THRESHOLD: ClassVar[int] = 3

    def effective_confidence(self, *, half_life_days: float = 180.0) -> float:
        """Confidence for RETRIEVAL RANKING, decayed by how long it has
        been since this fact was last confirmed - without mutating the
        stored `confidence` (the design-guide finding this follows:
        exposing recency to ranking is nearly free and catches facts
        the world may have quietly outdated even though nothing has
        actively contradicted them yet, e.g. 'the deploy pipeline runs
        on the shared runner pool' from six months ago). A fact
        re-confirmed yesterday keeps full confidence; one untouched for
        a full half-life is worth half its stored confidence in
        ranking, though it is never treated as false outright - lint's
        own `stale` check is the harder signal for that."""
        age_days = max(0.0, (utc_now() - self.last_confirmed_at).total_seconds() / 86400)
        decay = 0.5 ** (age_days / half_life_days)
        return self.confidence * decay


class KnowledgeRecallResult(BaseModel):
    """What recall() answers: the known facts plus whether they are
    fresh enough to skip a new research/browsing pass."""

    subject: str
    facts: list[KnowledgeFact] = Field(default_factory=list)
    stale: bool = True
    needs_research: bool = True
    reason: str = ""

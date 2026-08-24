from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
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
    source_url: str | None = None
    source_title: str | None = None
    confidence: float = Field(default=0.6, ge=0, le=1)
    first_learned_at: datetime = Field(default_factory=utc_now)
    last_confirmed_at: datetime = Field(default_factory=utc_now)
    confirmations: int = 1
    task_id: str | None = None
    memory_id: str | None = None  # links to the MemoryEntry that carries this fact for FTS/embedding recall
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_sentence(self) -> str:
        return f"{self.subject} {self.predicate} {self.value}".strip()


class KnowledgeRecallResult(BaseModel):
    """What recall() answers: the known facts plus whether they are
    fresh enough to skip a new research/browsing pass."""

    subject: str
    facts: list[KnowledgeFact] = Field(default_factory=list)
    stale: bool = True
    needs_research: bool = True
    reason: str = ""

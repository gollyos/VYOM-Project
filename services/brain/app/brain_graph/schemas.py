from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BrainRelation(str, Enum):
    KNOWN_BY = "KNOWN_BY"
    BELONGS_TO = "BELONGS_TO"
    CREATED_BY = "CREATED_BY"
    PRODUCED = "PRODUCED"
    SUPPORTED_BY = "SUPPORTED_BY"
    USES = "USES"
    DEPENDS_ON = "DEPENDS_ON"
    BLOCKED_BY = "BLOCKED_BY"
    SUPERSEDES = "SUPERSEDES"
    LEARNED_FROM = "LEARNED_FROM"
    HAS_MILESTONE = "HAS_MILESTONE"
    HAS_RUN = "HAS_RUN"
    IMPLEMENTS = "IMPLEMENTS"
    RELATED_TO = "RELATED_TO"


class BrainNode(BaseModel):
    id: str
    native_id: str
    kind: str
    label: str
    summary: str = ""
    status: str | None = None
    source_store: str
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrainEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation: BrainRelation
    confidence: float = Field(default=1.0, ge=0, le=1)
    verified: bool = False
    origin: str = "projection"
    provenance: str
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrainGraph(BaseModel):
    root_id: str | None = None
    depth: int
    nodes: list[BrainNode]
    edges: list[BrainEdge]
    truncated: bool = False
    refreshed_at: datetime


class ConnectRequest(BaseModel):
    source_id: str
    target_id: str
    relation: BrainRelation = BrainRelation.RELATED_TO
    confidence: float = Field(default=1.0, ge=0, le=1)
    verified: bool = False
    provenance: str = Field(min_length=3, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_id")
    @classmethod
    def reject_self_link(cls, value: str, info):
        if info.data.get("source_id") == value:
            raise ValueError("A Brain relationship cannot point to itself")
        return value

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryType(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PROJECT = "project"
    CLIENT = "client"
    PERSON = "person"
    PREFERENCE = "preference"
    DECISION = "decision"
    FAILURE = "failure"
    LESSON = "lesson"
    TOOL_PERFORMANCE = "tool_performance"
    MODEL_PERFORMANCE = "model_performance"
    AGENT_PERFORMANCE = "agent_performance"


class Sensitivity(str, Enum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    INFERRED = "inferred"
    VERIFIED = "verified"
    SUPERSEDED = "superseded"


class ProvenanceType(str, Enum):
    USER_STATEMENT = "user_statement"
    VERIFIED_TOOL_RESULT = "verified_tool_result"
    TASK_RESULT = "task_result"
    EXTERNAL_SOURCE = "external_source"
    GENERATED_SUMMARY = "generated_summary"
    AGENT_OBSERVATION = "agent_observation"
    MANUAL_IMPORT = "manual_import"


class MemoryProvenance(BaseModel):
    type: ProvenanceType
    reference: str | None = None
    task_id: str | None = None
    event_id: str | None = None
    source_url: str | None = None
    file: str | None = None
    evidence_id: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class MemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: f"mem_{uuid4().hex}")
    type: MemoryType
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=40_000)
    summary: str = Field(min_length=1, max_length=2_000)
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    provenance: list[MemoryProvenance] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_accessed_at: datetime = Field(default_factory=utc_now)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    sensitivity: Sensitivity = Sensitivity.NORMAL
    verification_state: VerificationState = VerificationState.UNVERIFIED
    project_id: str | None = None
    client_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    expires_at: datetime | None = None
    supersedes: str | None = None
    embedding_reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content", "summary")
    @classmethod
    def reject_secret_material(cls, value: str) -> str:
        lowered = value.lower()
        forbidden = ("api_key=", "password=", "bearer ey", "private_key")
        if any(marker in lowered for marker in forbidden):
            raise ValueError("Secrets cannot be stored as ordinary memory")
        return value


class MemoryQuery(BaseModel):
    text: str = ""
    types: set[MemoryType] = Field(default_factory=set)
    project_id: str | None = None
    client_id: str | None = None
    agent_id: str | None = None
    max_sensitivity: Sensitivity = Sensitivity.SENSITIVE
    verification_states: set[VerificationState] = Field(default_factory=set)
    limit: int = Field(default=8, ge=1, le=100)


class MemorySearchResult(BaseModel):
    memory: MemoryEntry
    score: float = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)


class EntityType(str, Enum):
    USER = "User"
    PERSON = "Person"
    CLIENT = "Client"
    PROJECT = "Project"
    TASK = "Task"
    AGENT = "Agent"
    SKILL = "Skill"
    TOOL = "Tool"
    MODEL = "Model"
    FILE = "File"
    MEETING = "Meeting"
    GOAL = "Goal"
    DECISION = "Decision"
    ARTIFACT = "Artifact"


class RelationType(str, Enum):
    WORKS_ON = "WORKS_ON"
    BELONGS_TO = "BELONGS_TO"
    DEPENDS_ON = "DEPENDS_ON"
    CREATED_BY = "CREATED_BY"
    USES = "USES"
    KNOWS = "KNOWS"
    RELATED_TO = "RELATED_TO"
    BLOCKED_BY = "BLOCKED_BY"
    PRODUCED = "PRODUCED"
    PREFERS = "PREFERS"
    LEARNED_FROM = "LEARNED_FROM"


class MemoryRelationship(BaseModel):
    id: str = Field(default_factory=lambda: f"rel_{uuid4().hex}")
    source_id: str
    target_id: str
    relation: RelationType
    confidence: float = Field(default=0.8, ge=0, le=1)
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GoalCategory(str, Enum):
    BUSINESS = "business"
    CAREER = "career"
    HEALTH = "health"
    LEARNING = "learning"
    FINANCE = "finance"
    PERSONAL = "personal"
    RELATIONSHIP = "relationship"
    PROJECT = "project"
    OTHER = "other"


class GoalStatus(str, Enum):
    IDEA = "idea"
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class GoalPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# A goal is a durable outcome; a task is a concrete unit of work toward
# it (rule 4). Goals never embed a task list directly — `next_action` is
# the single next concrete step, and full task tracking stays in the
# existing Task Runtime/CRM/skills systems this goal references.
class Goal(BaseModel):
    id: str = Field(default_factory=lambda: f"goal_{uuid4().hex}")
    title: str
    description: str = ""
    category: GoalCategory = GoalCategory.OTHER
    priority: GoalPriority = GoalPriority.MEDIUM
    status: GoalStatus = GoalStatus.IDEA
    target_date: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    progress: float | None = None            # None means "no evidence-based progress yet" (rule 6)
    progress_basis: str | None = None        # explains what the progress number is derived from
    motivation: str | None = None
    related_projects: list[str] = Field(default_factory=list)
    related_habits: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    next_action: str | None = None
    deferred_count: int = 0
    last_progress_at: datetime | None = None


class MilestoneStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Milestone(BaseModel):
    id: str = Field(default_factory=lambda: f"milestone_{uuid4().hex}")
    goal_id: str
    title: str
    target: str
    deadline: datetime | None = None
    status: MilestoneStatus = MilestoneStatus.PENDING
    evidence: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

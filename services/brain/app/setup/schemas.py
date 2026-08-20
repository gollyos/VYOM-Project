from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class SetupStepId(str, Enum):
    INTRO = "intro"
    PREFERENCES = "preferences"
    VOICE_TEST = "voice_test"
    MICROPHONE = "microphone"
    PRIVACY = "privacy"
    PROVIDER = "provider"
    WORKSPACE = "workspace"
    INTEGRATIONS = "integrations"
    AUTONOMY = "autonomy"
    NOTIFICATIONS = "notifications"
    STARTUP = "startup"
    DIAGNOSTICS = "diagnostics"
    READY = "ready"


REQUIRED_STEPS = [SetupStepId.INTRO, SetupStepId.PRIVACY, SetupStepId.READY]
SKIPPABLE_STEPS = set(SetupStepId) - set(REQUIRED_STEPS)


class SetupStepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class SetupStep(BaseModel):
    id: SetupStepId
    title: str
    description: str
    required: bool = False
    status: SetupStepStatus = SetupStepStatus.PENDING
    data: dict = Field(default_factory=dict)


class SetupState(BaseModel):
    onboarding_version: int = 1
    state_id: str = Field(default_factory=lambda: f"setup_{uuid4().hex[:10]}")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    steps: list[SetupStep] = Field(default_factory=list)
    user_preferences: dict = Field(default_factory=dict)
    privacy_choices: dict = Field(default_factory=dict)
    autonomy_preset: str = "balanced"

    @property
    def finished(self) -> bool:
        return self.completed_at is not None

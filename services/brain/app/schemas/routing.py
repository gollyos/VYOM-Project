from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelDefinition(BaseModel):
    provider: str
    model_id: str
    enabled: bool = True
    capabilities: set[str] = Field(default_factory=set)
    quality_tier: str = "balanced"
    speed_tier: str = "balanced"
    cost_tier: str = "medium"
    context_tier: str = "medium"
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_vision: bool = False
    privacy_policy: str = "cloud_standard"
    priority: int = 0

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model_id}"


class RoutingDecision(BaseModel):
    primary_model: str
    primary_provider: str
    fallback_models: list[str] = Field(default_factory=list)
    optional_verifier: str | None = None
    reason_selected: str
    estimated_cost_tier: str
    considered_models: list[str] = Field(default_factory=list)


class ProviderStatus(BaseModel):
    provider: str
    configured: bool
    available: bool
    reason: str
    recent_failures: int = 0


class UsageRecord(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


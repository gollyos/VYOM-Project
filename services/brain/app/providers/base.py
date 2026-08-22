from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.routing import UsageRecord
from app.schemas.tasks import TaskProfile


class ProviderError(RuntimeError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    #: True when the provider reported an exhausted DAILY allowance rather
    #: than a short burst limit. Google meters the free tier per model per
    #: day, so this distinction decides whether backing off for seconds is
    #: pointless and the router should move to a different model instead.
    daily_quota: bool = False

    def __init__(self, *args, daily_quota: bool = False):
        super().__init__(*args)
        self.daily_quota = daily_quota

    pass


class ProviderResponseInvalidError(ProviderError):
    pass


class ProviderRequest(BaseModel):
    model: str
    user_request: str
    system_instruction: str
    profile: TaskProfile
    context: dict[str, Any] = Field(default_factory=dict)


class ToolSchema(BaseModel):
    """One capability offered to the planner as a callable contract.

    Parameters follow JSON Schema so the model returns a STRUCTURED call
    rather than prose describing what the user could do themselves."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    #: Opaque provider token that must be echoed back with the call when
    #: replaying history. Gemini 3 rejects a multi-turn tool conversation
    #: whose functionCall parts have lost it.
    thought_signature: str | None = None


class ProviderResponse(BaseModel):
    text: str
    structured: dict[str, Any] = Field(default_factory=dict)
    usage: UsageRecord = Field(default_factory=UsageRecord)
    #: Structured tool calls the model chose. Empty means it answered in
    #: text; the planner treats a text-only reply to an ACTIONABLE goal as
    #: a refusal to act, never as the result.
    tool_calls: list[ToolCall] = Field(default_factory=list)


class BaseProvider(ABC):
    name: str

    def __init__(self) -> None:
        self._last_usage = UsageRecord()
        #: Optional shared disk cache (app.providers.response_cache),
        #: attached at wiring time - constructed providers default to no
        #: cache so direct use (tests, tools) is unaffected.
        self.response_cache: Any = None

    @property
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    async def stream(self, request: ProviderRequest) -> AsyncIterator[str]:
        response = await self.generate(request)
        yield response.text

    async def structured_output(self, request: ProviderRequest) -> ProviderResponse:
        cache = self.response_cache
        if cache is not None and cache.enabled:
            cached = cache.get(request)
            if cached is not None:
                return cached
        response = await self.generate(request)
        if cache is not None and cache.enabled and response.text.strip():
            cache.put(request, response)
        return response

    @property
    def supports_tool_calls(self) -> bool:
        """Whether this provider can return structured tool calls. The
        general planner requires it; providers without it are skipped
        rather than allowed to answer an actionable goal in prose."""
        return False

    async def generate_with_tools(
        self,
        request: ProviderRequest,
        tools: list[ToolSchema],
        history: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError(f"{self.name} does not support tool calling")

    async def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "configured": self.configured,
            "available": self.configured,
            "reason": "configured" if self.configured else "missing credentials",
        }

    def usage(self) -> UsageRecord:
        return self._last_usage


class ProviderRegistry:
    def __init__(self, providers: list[BaseProvider]):
        self.providers = {provider.name: provider for provider in providers}

    def get(self, name: str) -> BaseProvider | None:
        return self.providers.get(name)

    def all(self) -> list[BaseProvider]:
        return list(self.providers.values())


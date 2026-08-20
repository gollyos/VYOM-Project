from __future__ import annotations

import os

import httpx

from app.schemas.routing import UsageRecord

from .base import (
    BaseProvider,
    ProviderRateLimitError,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseInvalidError,
    ProviderUnavailableError,
)


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, timeout_seconds: float):
        super().__init__()
        self.timeout_seconds = timeout_seconds

    @property
    def api_key(self) -> str | None:
        return os.getenv("ANTHROPIC_API_KEY") or None

    @property
    def configured(self) -> bool:
        return self.api_key is not None

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.api_key:
            raise ProviderUnavailableError("Anthropic credentials are not configured")
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": request.model,
            "max_tokens": 2048,
            "system": request.system_instruction,
            "messages": [{"role": "user", "content": request.user_request}],
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        if response.status_code == 429:
            raise ProviderRateLimitError("Anthropic rate limit")
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"Anthropic request failed with HTTP {response.status_code}")
        data = response.json()
        try:
            text = "".join(item.get("text", "") for item in data["content"] if item.get("type") == "text")
        except (KeyError, TypeError) as error:
            raise ProviderResponseInvalidError("Anthropic returned malformed output") from error
        usage_raw = data.get("usage", {})
        usage = UsageRecord(
            input_tokens=usage_raw.get("input_tokens"),
            output_tokens=usage_raw.get("output_tokens"),
            total_tokens=(usage_raw.get("input_tokens") or 0) + (usage_raw.get("output_tokens") or 0),
            raw=usage_raw,
        )
        self._last_usage = usage
        return ProviderResponse(text=text, usage=usage)


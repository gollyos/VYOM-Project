from __future__ import annotations

import json
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


class OpenAICompatibleProvider(BaseProvider):
    def __init__(
        self,
        *,
        name: str,
        api_key_env: str,
        base_url: str,
        timeout_seconds: float,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.name = name
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.extra_headers = extra_headers or {}

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env) or None

    @property
    def configured(self) -> bool:
        return self.api_key is not None

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.api_key:
            raise ProviderUnavailableError(f"{self.name} credentials are not configured")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        payload = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": request.user_request},
            ],
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
        if response.status_code == 429:
            raise ProviderRateLimitError(f"{self.name} rate limit")
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"{self.name} request failed with HTTP {response.status_code}")
        data = response.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderResponseInvalidError(f"{self.name} returned malformed output") from error
        usage_raw = data.get("usage", {})
        usage = UsageRecord(
            input_tokens=usage_raw.get("prompt_tokens"),
            output_tokens=usage_raw.get("completion_tokens"),
            total_tokens=usage_raw.get("total_tokens"),
            raw=usage_raw,
        )
        self._last_usage = usage
        structured: dict[str, object] = {}
        try:
            candidate = json.loads(text)
            if isinstance(candidate, dict):
                structured = candidate
        except json.JSONDecodeError:
            pass
        return ProviderResponse(text=text, structured=structured, usage=usage)


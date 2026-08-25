from __future__ import annotations

import json

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


class OpenCodeFreeProvider(BaseProvider):
    """KEYLESS free-tier model via the OpenCode Zen relay
    (https://opencode.ai/zen/v1). No signup, no API key: the relay
    serves its curated "-free" model family anonymously — an empty
    Authorization header is required (a missing header or any non-empty
    bearer is rejected). This mirrors the same keyless routing Hermes
    Agent ships for its `opencode-free` provider (hermes_cli/models.py:
    OPENCODE_ZEN_FREE_KEYLESS_PLACEHOLDER / opencode_zen_free_headers).

    Always reports `configured = True`: there is no credential to be
    missing. If the upstream free model is temporarily unavailable
    (observed for x-preview-f-free / "Ox Alpha" on 2026-08-25), this
    raises ProviderUnavailableError like any other outage — the router's
    normal fallback chain handles it, it does not need special-casing.
    """

    BASE_URL = "https://opencode.ai/zen/v1"
    # Curated keyless model family confirmed live: x-preview-f-free ("Ox
    # Alpha"), hy3-free, laguna-s-2.1-free, nemotron-3-ultra-free,
    # nemotron-3.5-lightning-free, mimo-v2.5-free. Any other "-free" slug
    # on this relay is also served anonymously by the same route.
    DEFAULT_MODEL = "hy3-free"  # verified consistently available; x-preview-f-free had a transient outage

    def __init__(self, timeout_seconds: float):
        super().__init__()
        self.name = "opencode-free"
        self.timeout_seconds = timeout_seconds

    @property
    def api_key(self) -> str | None:
        return "opencode-zen-free-keyless"  # placeholder only — never sent on the wire

    @property
    def configured(self) -> bool:
        return True  # keyless: there is no credential to be missing

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        model = request.model if request.model and request.model.endswith("-free") else self.DEFAULT_MODEL
        headers = {
            "Content-Type": "application/json",
            "Authorization": "",  # explicit empty auth — the anonymous free route requires this
            "X-Title": "VYOM Brain",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": request.user_request},
            ],
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.BASE_URL}/chat/completions", headers=headers, json=payload)
        if response.status_code == 429:
            raise ProviderRateLimitError(f"{self.name} rate limit")
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"{self.name} request failed with HTTP {response.status_code}: {response.text[:200]}")
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

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
    ToolCall,
    ToolSchema,
)


def _is_daily_quota(response: httpx.Response) -> bool:
    """Did Google reject this for an exhausted DAILY, per-model allowance?

    The free tier meters `GenerateRequestsPerDayPerProjectPerModel`. That
    quota does not return for hours, so a short retry against the SAME
    model can never succeed - the router has to move to a different model.
    A per-minute burst limit is a genuinely different situation, and
    treating the two identically is what turned one exhausted model into a
    total outage."""
    try:
        details = response.json().get("error", {}).get("details", [])
    except Exception:
        return False
    for detail in details:
        for violation in detail.get("violations", []) or []:
            identifier = str(violation.get("quotaId", ""))
            if "PerDay" in identifier or "per_day" in identifier.lower():
                return True
    return False


class GoogleProvider(BaseProvider):
    name = "google"

    def __init__(self, timeout_seconds: float):
        super().__init__()
        self.timeout_seconds = timeout_seconds

    @property
    def api_key(self) -> str | None:
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None

    @property
    def configured(self) -> bool:
        return self.api_key is not None

    def _auth_headers(self) -> dict[str, str]:
        """Credential travels in a header, never in the URL.

        As `?key=...` it was written verbatim into every HTTP access log
        line, leaking the key to anyone who could read the log file."""
        return {"x-goog-api-key": self.api_key or "", "Content-Type": "application/json"}

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.api_key:
            raise ProviderUnavailableError("Google credentials are not configured")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{request.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": request.system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_request}]}],
            "generationConfig": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, headers=self._auth_headers(), json=payload)
        if response.status_code == 429:
            raise ProviderRateLimitError(
                f"Google rate limit for {request.model}",
                daily_quota=_is_daily_quota(response),
            )
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"Google request failed with HTTP {response.status_code}")
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderResponseInvalidError("Google returned malformed output") from error
        usage_raw = data.get("usageMetadata", {})
        usage = UsageRecord(
            input_tokens=usage_raw.get("promptTokenCount"),
            output_tokens=usage_raw.get("candidatesTokenCount"),
            total_tokens=usage_raw.get("totalTokenCount"),
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


    # -- structured tool calling ------------------------------------------
    #
    # This is what lets the general planner ACT instead of advise. Without
    # it an unmatched request reached a text-only model, which could only
    # describe what the user might do (or invent an answer) - the exact
    # behaviour that made VYOM feel like a chatbot.

    @property
    def supports_tool_calls(self) -> bool:
        return True

    async def generate_with_tools(
        self,
        request: ProviderRequest,
        tools: list[ToolSchema],
        history: list[dict] | None = None,
    ) -> ProviderResponse:
        if not self.api_key:
            raise ProviderUnavailableError("Google credentials are not configured")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{request.model}:generateContent"

        contents: list[dict] = [{"role": "user", "parts": [{"text": request.user_request}]}]
        contents.extend(history or [])

        payload: dict = {
            "systemInstruction": {"parts": [{"text": request.system_instruction}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.1},
        }
        if tools:
            payload["tools"] = [{
                "functionDeclarations": [
                    {
                        "name": tool.name,
                        "description": tool.description[:900],
                        "parameters": tool.parameters or {"type": "object", "properties": {}},
                    }
                    for tool in tools
                ]
            }]

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, headers=self._auth_headers(), json=payload)
        if response.status_code == 429:
            raise ProviderRateLimitError(
                f"Google rate limit for {request.model}",
                daily_quota=_is_daily_quota(response),
            )
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                f"Google tool request failed with HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderResponseInvalidError("Google returned malformed output") from error

        text_chunks: list[str] = []
        calls: list[ToolCall] = []
        for part in parts:
            if "text" in part and part["text"]:
                text_chunks.append(part["text"])
            call = part.get("functionCall")
            if call and call.get("name"):
                calls.append(ToolCall(
                    name=call["name"],
                    arguments=dict(call.get("args") or {}),
                    thought_signature=part.get("thoughtSignature"),
                ))

        usage_raw = data.get("usageMetadata", {})
        usage = UsageRecord(
            input_tokens=usage_raw.get("promptTokenCount"),
            output_tokens=usage_raw.get("candidatesTokenCount"),
            total_tokens=usage_raw.get("totalTokenCount"),
            raw=usage_raw,
        )
        self._last_usage = usage
        return ProviderResponse(
            text="".join(text_chunks).strip(),
            structured={},
            usage=usage,
            tool_calls=calls,
        )

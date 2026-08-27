from __future__ import annotations

import json
import os
from typing import Any

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


#: JSON-Schema keywords Gemini's function-calling schema validator does
#: NOT accept. A tool whose `input_schema` carries any of these (the MCP
#: tools ship full Draft-07 schemas, and numeric bounds like
#: `exclusiveMaximum` are common) makes the whole generateContent request
#: fail with HTTP 400 "Unknown name ...", taking every other tool in the
#: same call down with it. They are stripped recursively before the call.
_GEMINI_SCHEMA_DROP = frozenset({
    "$schema", "$id", "$ref", "$defs", "definitions", "additionalProperties",
    "exclusiveMinimum", "exclusiveMaximum", "const", "examples", "default",
    "patternProperties", "unevaluatedProperties", "if", "then", "else",
    "allOf", "oneOf", "not", "contentMediaType", "contentEncoding",
    "minLength", "maxLength", "pattern", "minItems", "maxItems",
    "minimum", "maximum", "multipleOf", "uniqueItems",
})
_GEMINI_ALLOWED_FORMATS = frozenset({"enum", "date-time", "int32", "int64", "float", "double"})


def _sanitize_gemini_schema(node: Any) -> Any:
    """Recursively keep only the schema shape Gemini accepts."""
    if isinstance(node, list):
        return [_sanitize_gemini_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    clean: dict[str, Any] = {}
    for key, value in node.items():
        if key in _GEMINI_SCHEMA_DROP:
            continue
        if key == "format" and value not in _GEMINI_ALLOWED_FORMATS:
            continue
        if key in ("properties", "$defs", "definitions"):
            clean[key] = {k: _sanitize_gemini_schema(v) for k, v in (value or {}).items()}
        elif key == "items":
            clean[key] = _sanitize_gemini_schema(value)
        else:
            clean[key] = _sanitize_gemini_schema(value)
    return clean


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
        # A new AsyncClient per request redid the TCP+TLS handshake for
        # every call - pure latency and connection churn. One pooled
        # client keeps connections warm for the process lifetime.
        self._client: httpx.AsyncClient | None = None
        #: Optional QuotaBudgeter (app.routing.quota_budgeter), attached at
        #: wiring time. When present, requests are PACED before they are
        # sent and daily-quota 429s teach the budgeter the real allowance.
        self.budgeter: Any = None

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    def _pooled_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def _paced_post(self, url: str, headers: dict, payload: dict, model: str) -> httpx.Response:
        """POST with quota pacing: reserve the request first, send once,
        and let a daily 429 teach the budgeter the real allowance so the
        router moves traffic to sibling models instead of rediscovering
        the limit."""
        from app.routing.quota_budgeter import QuotaWaitTimeout

        budgeter = getattr(self, "budgeter", None)
        if budgeter is not None:
            try:
                await budgeter.acquire("google", model)
            except QuotaWaitTimeout:
                # Bounded pacing wait elapsed: surface as an ordinary
                # (non-daily) rate limit so existing health cooldown and
                # fallback machinery routes elsewhere.
                raise ProviderRateLimitError(
                    f"Pacing window full for {model}", daily_quota=False
                )
        response = await self._pooled_client().post(url, headers=headers, json=payload)
        if response.status_code == 429:
            daily = _is_daily_quota(response)
            if daily and budgeter is not None:
                budgeter.clamp_daily("google", model)
            raise ProviderRateLimitError(
                f"Google rate limit for {model}", daily_quota=daily
            )
        return response

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
        response = await self._paced_post(url, self._auth_headers(), payload, request.model)
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
                        "parameters": _sanitize_gemini_schema(
                            tool.parameters or {"type": "object", "properties": {}}
                        ),
                    }
                    for tool in tools
                ]
            }]

        response = await self._paced_post(url, self._auth_headers(), payload, request.model)
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

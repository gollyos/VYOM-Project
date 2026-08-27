from __future__ import annotations

from typing import Any

import httpx

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult

ADVICE_URL = "https://api.adviceslip.com/advice"
FACT_URL = "https://uselessfacts.jsph.pl/api/v2/facts/random"
JOKE_URL = "https://official-joke-api.appspot.com/random_joke"


class TriviaFactsTool(BaseTool):
    """Free, no-API-key personality/small-talk lookups: a random piece of
    advice, a random useless fact, or a random joke. This is what makes
    VYOM feel conversational rather than purely a task-executor. Read-only,
    so every action is L0."""

    metadata = ToolMetadata(
        name="facts",
        description=(
            "Fetch a random piece of advice, a useless fact, or a joke using free, "
            "keyless public APIs (Advice Slip, Useless Facts, Official Joke API). "
            "Actions: advice, fact, joke."
        ),
        category="utility",
        required_permissions=[PermissionLevel.L0],
        risk_level="low",
    )

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L0

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            if self._client is not None:
                response = await self._client.get(url)
            else:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    response = await client.get(url)
        except httpx.HTTPError as exc:
            raise ToolValidationError(f"Lookup failed: could not reach {url} ({exc})") from exc
        if response.status_code >= 400:
            raise ToolValidationError(f"Lookup failed: {url} returned {response.status_code}")
        return response.json()

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", "advice"))

        if action == "advice":
            data = await self._get_json(ADVICE_URL)
            advice = (data.get("slip") or {}).get("advice", "")
            if not advice:
                raise ToolValidationError("No advice returned")
            output = {"advice": advice}
            summary = advice
        elif action == "fact":
            data = await self._get_json(FACT_URL)
            fact = data.get("text", "")
            if not fact:
                raise ToolValidationError("No fact returned")
            output = {"fact": fact, "source": data.get("source_url")}
            summary = fact
        elif action == "joke":
            data = await self._get_json(JOKE_URL)
            setup = data.get("setup", "")
            punchline = data.get("punchline", "")
            if not setup or not punchline:
                raise ToolValidationError("No joke returned")
            output = {"setup": setup, "punchline": punchline, "type": data.get("type")}
            summary = f"{setup} ... {punchline}"
        else:
            raise ToolValidationError("Unsupported facts action (use 'advice', 'fact', or 'joke')")

        evidence = EvidenceItem(type="tool_result", summary=f"Facts {action}", data=output)
        return ToolResult.completed(summary, output=output, evidence=[evidence])
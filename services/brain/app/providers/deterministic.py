from __future__ import annotations

import asyncio

from app.schemas.routing import UsageRecord

from .base import BaseProvider, ProviderRequest, ProviderResponse


class DeterministicProvider(BaseProvider):
    name = "local"

    def __init__(self, delay_seconds: float = 0) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds
        self.call_count = 0
        self.fail_next = False

    @property
    def configured(self) -> bool:
        return True

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.call_count += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Injected deterministic provider failure")

        intent = request.profile.intent
        if intent == "plan_today":
            text = "Your day is planned around one protected focus block, two meetings, and one approval window."
        elif intent == "daily_status":
            text = "You have 12 tasks, 4 active agents, 2 meetings, and 3 approvals today."
        else:
            text = "The request was processed by VYOM's limited local rules provider."
        self._last_usage = UsageRecord(total_tokens=0, estimated_cost=0)
        return ProviderResponse(text=text, structured={"intent": intent}, usage=self._last_usage)


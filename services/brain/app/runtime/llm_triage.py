"""One cheap model call that understands what keywords cannot.

The classifier's keyword tables are a fast path, not a brain. When they
decline ("aaj ka kaam sambhalo" matches no phrase list), the old
behaviour guessed: a short utterance with no known action verb was
declared 'conversational' and answered by a text model with no tools -
the single biggest reason VYOM felt like a chatbot instead of an
assistant. Triage asks the cheapest capable model ONE structured
question: is this a request for ACTION or conversation, and how urgent
is the user's tone?

Cost discipline: triage runs ONLY after both keyword layers decline
(the common paths stay free), it routes through the ModelRouter (so
quota spreading, pacing and fallbacks all apply), and any failure
returns None - the caller then behaves exactly as before. Triage can
only UPGRADE an utterance to actionable; it never talks a real action
verb out of the mission path.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("vyom.runtime.triage")

_TRIAGE_SYSTEM = (
    "You are the intent gate for a personal assistant. Classify the user's "
    "utterance. Answer ONLY with a JSON object with these keys: "
    '"actionable" (true if the user wants the assistant to DO something - '
    "open/close/search/create/plan/manage/track/operate the PC or web - "
    "false if it is small talk, a greeting, or a standalone question that "
    "needs no tool), "
    '"intent_hint" (short snake_case label of the request, or \'none\'), '
    '"tone" (one of: neutral, urgent, frustrated, cheerful, curious), '
    '"urgency" (one of: low, normal, high). '
    "The user speaks Hinglish (Hindi+English) - understand the MEANING, "
    "not the keywords. Example: 'aaj ka kaam sambhal lo' means 'take charge "
    "of today's work' -> actionable true, intent_hint manage_daily_work."
)


class LLMTriage:
    def __init__(self, model_router, providers):
        self._router = model_router
        self._providers = providers

    async def classify(self, task, profile, text: str) -> dict[str, Any] | None:
        """Structured triage of an unrecognised utterance.

        Returns {"actionable": bool, "intent_hint": str, "tone": str,
        "urgency": str} or None (unroutable / provider failure / quota) -
        None always means 'fall back to the existing behaviour'."""
        text = (text or "").strip()
        if not text:
            return None
        try:
            routing = await self._router.route(task, profile)
        except Exception:
            return None
        provider = self._providers.get(routing.primary_provider)
        if provider is None:
            return None
        try:
            from app.schemas.routing import RoutingDecision  # noqa: F401  (shape doc)

            from app.providers.base import ProviderRequest

            request = ProviderRequest(
                model=routing.primary_model,
                user_request=text[:2000],
                system_instruction=_TRIAGE_SYSTEM,
                profile=profile,
            )
            response = await provider.structured_output(request)
        except Exception:
            # Rate limits, out of quota, provider down: triage is an
            # upgrade, never a dependency. Existing behaviour continues.
            return None
        structured = response.structured or {}
        raw = {}
        if structured:
            raw = structured
        else:
            try:
                raw = json.loads(response.text.strip().removeprefix("```json").removesuffix("```").strip())
            except (ValueError, AttributeError):
                return None
        if not isinstance(raw, dict) or "actionable" not in raw:
            return None
        actionable = bool(raw.get("actionable"))
        return {
            "actionable": actionable,
            "intent_hint": str(raw.get("intent_hint") or "none")[:60],
            "tone": str(raw.get("tone") or "neutral")[:20],
            "urgency": str(raw.get("urgency") or "normal")[:10],
            "model": routing.primary_model,
        }

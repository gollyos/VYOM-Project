"""Repair D — the soul fix: real understanding where keywords gave up.

Triage asks one cheap model call what the phrase tables could not answer:
is this utterance a request for ACTION or just conversation, and what is
the user's tone. It can only upgrade toward action, never downgrade; any
failure leaves behaviour exactly as before.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.base import ProviderRequest, ProviderResponse
from app.research.orchestrator import DeepResearchTask
from app.research.schemas import Claim, ResearchPlan
from app.research.synthesizer import ResearchSynthesizer
from app.runtime.llm_triage import LLMTriage
from app.schemas.tasks import Task, TaskProfile


class _StubProvider:
    """Records calls; answers with a canned structured payload."""

    name = "stub"

    def __init__(self, response: ProviderResponse):
        self.response = response
        self.calls: list[ProviderRequest] = []
        self.response_cache = None

    @property
    def configured(self) -> bool:
        return True

    async def structured_output(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        return self.response


class _BrokenProvider(_StubProvider):
    async def structured_output(self, request: ProviderRequest) -> ProviderResponse:
        raise RuntimeError("provider down")


class _StubRouter:
    def __init__(self, provider, model="gemini-3.1-flash-lite"):
        self.provider = provider
        self.model = model

    async def route(self, task, profile):
        class _D:
            primary_model = self.model
            primary_provider = "stub"

        return _D()


class _StubProviders:
    def __init__(self, provider):
        self._provider = provider

    def get(self, name):
        return self._provider if name == "stub" else None


def _task_and_profile():
    return Task(goal="manage today's work", user_request="aaj ka kaam sambhal lo"), TaskProfile()


def _triage_response(payload: dict) -> ProviderResponse:
    return ProviderResponse(text="{}", structured=payload)


# -- triage gate -------------------------------------------------------------


async def test_triage_understands_actionable_hinglish():
    provider = _StubProvider(_triage_response({
        "actionable": True, "intent_hint": "manage_daily_work",
        "tone": "urgent", "urgency": "high",
    }))
    triage = LLMTriage(_StubRouter(provider), _StubProviders(provider))
    task, profile = _task_and_profile()
    result = await triage.classify(task, profile, "aaj ka kaam sambhal lo")
    assert result is not None
    assert result["actionable"] is True
    assert result["tone"] == "urgent"
    assert result["urgency"] == "high"
    assert "Hinglish" in provider.calls[0].system_instruction


async def test_triage_failure_returns_none_and_changes_nothing():
    provider = _BrokenProvider(_triage_response({}))
    triage = LLMTriage(_StubRouter(provider), _StubProviders(provider))
    task, profile = _task_and_profile()
    assert await triage.classify(task, profile, "kuch bhi") is None


async def test_triage_rejects_shapeless_answers():
    provider = _StubProvider(ProviderResponse(text="sounds good!", structured={}))
    triage = LLMTriage(_StubRouter(provider), _StubProviders(provider))
    task, profile = _task_and_profile()
    assert await triage.classify(task, profile, "hello") is None


async def test_triage_parses_json_from_plain_text():
    provider = _StubProvider(ProviderResponse(
        text='{"actionable": false, "intent_hint": "greeting", "tone": "cheerful", "urgency": "low"}',
        structured={},
    ))
    triage = LLMTriage(_StubRouter(provider), _StubProviders(provider))
    task, profile = _task_and_profile()
    result = await triage.classify(task, profile, "hello ji")
    assert result is not None and result["actionable"] is False


async def test_triage_empty_text_short_circuits():
    provider = _StubProvider(_triage_response({"actionable": True}))
    triage = LLMTriage(_StubRouter(provider), _StubProviders(provider))
    task, profile = _task_and_profile()
    assert await triage.classify(task, profile, "   ") is None
    assert provider.calls == []


# -- deterministic engine labels are honest -----------------------------------


def test_no_pseudo_model_names_anywhere_in_the_runtime():
    """`local-phase8-runtime-v1` presented a deterministic workflow as a
    MODEL selection. Those labels are gone: workflows say workflow:,
    gates say gate: - observability no longer stages model theatre."""
    import subprocess

    result = subprocess.run(
        ["git", "grep", "-l", r"local-phase.-runtime-v1", "--", "services/brain/app"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2],
    )
    # git grep exits 1 when nothing matches - that is the passing case.
    assert result.stdout.strip() == ""


# -- research synthesis ------------------------------------------------------


async def test_synthesis_uses_model_over_extracted_claims():
    provider = _StubProvider(ProviderResponse(
        text="Tumhare research ke mutabik: pricing data strong hai, positioning clear hai.",
        structured={},
    ))
    synthesizer = ResearchSynthesizer()
    plan = ResearchPlan(goal="Competitor pricing research")
    claims = [Claim(statement="Pricing is $10/mo", confidence=0.9, supporting_sources=["s1"])]
    text = await synthesizer.synthesize_async(
        plan, claims, [], [], provider=provider, model="gemini-3.1-flash-lite",
    )
    assert "Tumhare research" in text
    # The model only ever sees the EXTRACTED claims, never free rein.
    assert "Pricing is $10/mo" in provider.calls[0].user_request


async def test_synthesis_falls_back_to_template_without_provider():
    synthesizer = ResearchSynthesizer()
    plan = ResearchPlan(goal="Anything")
    claims = [Claim(statement="Fact one", confidence=0.8, supporting_sources=["s1"])]
    text = await synthesizer.synthesize_async(plan, claims, [], [], provider=None, model=None)
    assert "Fact one" in text


async def test_synthesis_survives_provider_failure():
    provider = _BrokenProvider(ProviderResponse(text="x"))
    synthesizer = ResearchSynthesizer()
    plan = ResearchPlan(goal="Anything")
    claims = [Claim(statement="Fact one", confidence=0.8, supporting_sources=["s1"])]
    text = await synthesizer.synthesize_async(
        plan, claims, [], [], provider=provider, model="m",
    )
    assert "Fact one" in text  # deterministic template answered


async def test_synthesis_refuses_to_invent_from_nothing():
    synthesizer = ResearchSynthesizer()
    plan = ResearchPlan(goal="Empty research")
    provider = _StubProvider(ProviderResponse(text="I made this up", structured={}))
    text = await synthesizer.synthesize_async(
        plan, [], [], [], provider=provider, model="m",
    )
    # No supported claims -> template honest "no findings", model bypassed.
    assert "No sufficiently supported findings" in text

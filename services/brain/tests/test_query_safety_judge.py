"""Tests for the AI-as-a-judge query-safety gate (app/safety/query_judge.py),
the pattern learned from the LangGraph agentic data-agent tutorial. It
decides whether a model-generated SQL/query is safe to run (read-only
retrieval only). Two layers: a deterministic keyword pre-check (no LLM
cost) and an LLM judge pass bound to a strict schema.

The design is deliberately CONSERVATIVE (fail-to-unsafe): a generative
query the judge can't verify is treated as unsafe, never silently
allowed. These tests prove both layers and the fail-safe behaviour.
"""
from __future__ import annotations

import pytest

from app.safety.query_judge import JudgeResult, QuerySafetyJudge


@pytest.mark.asyncio
async def test_destructive_insert_is_rejected_without_llm():
    calls = []

    async def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return '{"safe": true, "reason": "fine"}'

    judge = QuerySafetyJudge(llm_call=fake_llm)
    result = await judge.judge("INSERT INTO orders VALUES (1, 'x')")
    assert result.safe is False
    assert "destructive" in result.reason.lower()
    assert calls == [], "a deterministic destructive keyword must be rejected WITHOUT an LLM call"


@pytest.mark.asyncio
async def test_delete_is_rejected_deterministically():
    async def fake_llm(prompt: str) -> str:
        return '{"safe": true}'

    judge = QuerySafetyJudge(llm_call=fake_llm)
    result = await judge.judge("DELETE FROM users WHERE id = 5")
    assert result.safe is False
    assert "destructive" in result.reason.lower()


@pytest.mark.asyncio
async def test_drop_semicolon_injection_is_rejected_deterministically():
    """A classic injection vector: a read-only SELECT followed by a ';'
    then a destructive statement. Must be caught by the deterministic
    layer, not the LLM."""
    async def fake_llm(prompt: str) -> str:
        return '{"safe": true}'

    judge = QuerySafetyJudge(llm_call=fake_llm)
    result = await judge.judge("SELECT * FROM users; DROP TABLE users")
    assert result.safe is False
    assert "destructive" in result.reason.lower()


@pytest.mark.asyncio
async def test_non_select_query_is_rejected():
    async def fake_llm(prompt: str) -> str:
        return '{"safe": true}'

    judge = QuerySafetyJudge(llm_call=fake_llm)
    result = await judge.judge("SHOW TABLES")
    assert result.safe is False
    assert "read-only select" in result.reason.lower()


@pytest.mark.asyncio
async def test_empty_query_is_rejected():
    judge = QuerySafetyJudge(llm_call=lambda p: _never())
    result = await judge.judge("   ")
    assert result.safe is False
    assert "empty" in result.reason.lower()


@pytest.mark.asyncio
async def test_safe_select_passes_deterministic_layer_then_llm():
    async def fake_llm(prompt: str) -> str:
        return '{"safe": true, "reason": "read-only select"}'

    judge = QuerySafetyJudge(llm_call=fake_llm)
    result = await judge.judge("SELECT id, name FROM users WHERE active = 1")
    assert result.safe is True
    assert "read-only select" in result.reason.lower()


@pytest.mark.asyncio
async def test_llm_failure_falls_through_to_unsafe():
    """Fail-to-unsafe: if the judge LLM call raises, the query is treated
    as unsafe, never allowed."""
    async def fake_llm(prompt: str) -> str:
        raise RuntimeError("provider down")

    judge = QuerySafetyJudge(llm_call=fake_llm)
    result = await judge.judge("SELECT * FROM users")
    assert result.safe is False
    assert "could not run" in result.reason.lower()


@pytest.mark.asyncio
async def test_unparsable_llm_output_falls_to_unsafe():
    async def fake_llm(prompt: str) -> str:
        return "I think it is probably fine to run this query."

    judge = QuerySafetyJudge(llm_call=fake_llm)
    result = await judge.judge("SELECT * FROM users")
    assert result.safe is False
    assert "no parsable verdict" in result.reason.lower()


@pytest.mark.asyncio
async def test_string_answer_is_rejected_not_coerced_to_safe():
    """A judge that answers with the string 'true' instead of a boolean is
    ambiguous and must NOT be treated as safe."""
    async def fake_llm(prompt: str) -> str:
        return '{"safe": "true", "reason": "ok"}'

    judge = QuerySafetyJudge(llm_call=fake_llm)
    result = await judge.judge("SELECT * FROM users")
    assert result.safe is False
    assert "explicit boolean" in result.reason.lower()


@pytest.mark.asyncio
async def test_fenced_json_output_is_parsed():
    async def fake_llm(prompt: str) -> str:
        return '```json\n{"safe": false, "reason": "updates a row"}\n```'

    judge = QuerySafetyJudge(llm_call=fake_llm)
    result = await judge.judge("SELECT * FROM users")
    assert result.safe is False
    assert "updates a row" in result.reason.lower()


async def _never() -> str:
    raise AssertionError("LLM call should not happen")

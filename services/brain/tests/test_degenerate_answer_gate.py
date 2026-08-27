"""The structural Verifier used to report ANY non-empty response as
COMPLETE with score 1.0. Three real production non-answers slipped
through and were spoken back to the user as if they were real:

  - "India — is a"                 (a knowledge fact's "{subject} —
                                    {predicate}" label leaked out with no
                                    value - the humaniser reads `title`
                                    first)
  - "Completed: x; Completed: y"   (operational task-log rows stitched
                                    together as prose)
  - "[{'title': ...}]"             (a raw tool payload)

`_degenerate_answer` catches these shapes so the task fails honestly,
while genuine terse answers ("New Delhi.", "Yes.", "42") still pass.
"""
from __future__ import annotations

import pytest

from app.runtime.verifier import Verifier, _degenerate_answer
from app.schemas.results import ExecutionResult
from app.schemas.tasks import Task


@pytest.mark.parametrize(
    "response, reason",
    [
        ("India — is a", "cut-off fragment"),
        ("Python is a", "cut-off fragment"),
        ("The framework was created", "cut-off fragment"),
        ("Completed: review the inbox; Completed: say hello", "task-log sediment"),
        ("[{'title': 'India', 'summary': 'x'}]", "raw tool payload"),
        ('{"title": "x"}', "raw tool payload"),
    ],
)
def test_degenerate_shapes_are_flagged(response: str, reason: str) -> None:
    assert _degenerate_answer(response) == reason


@pytest.mark.parametrize(
    "response",
    [
        "New Delhi.",
        "New Delhi hai, Boss.",
        "Yes.",
        "42",
        "The capital of India is New Delhi.",
        "Boss, aapki favourite adrak-elaichi wali kadak chai hai jo aap shaam ko lete ho.",
        "I could not find that information. Nothing is stored and research came back empty.",
    ],
)
def test_real_answers_pass(response: str) -> None:
    assert _degenerate_answer(response) is None


async def test_verifier_fails_a_cutoff_fragment() -> None:
    verifier = Verifier()
    task = Task(goal="India ki capital kya hai?", user_request="India ki capital kya hai?")
    result = ExecutionResult(response="India — is a")
    verdict = await verifier.verify(task, result)
    assert verdict.passed is False
    assert "not a real answer" in verdict.summary


async def test_verifier_fails_task_log_sediment() -> None:
    verifier = Verifier()
    task = Task(goal="baat karo", user_request="Yaar main bore ho raha hoon, kuch baat karo.")
    result = ExecutionResult(
        response="Completed: Meri favourite chai kaunsi hai?; Completed: Say hello",
    )
    verdict = await verifier.verify(task, result)
    assert verdict.passed is False


async def test_verifier_passes_a_real_answer() -> None:
    verifier = Verifier()
    task = Task(goal="India ki capital kya hai?", user_request="India ki capital kya hai?")
    result = ExecutionResult(response="New Delhi hai, Boss.")
    verdict = await verifier.verify(task, result)
    assert verdict.passed is True
    assert verdict.score == 1

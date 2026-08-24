from __future__ import annotations

import pytest

from app.runtime.task_runtime import _humanize_goal_evidence


@pytest.mark.parametrize("raw,expected", [
    (
        "search_performed: the browser was opened but no search or navigation was observed",
        "the browser was opened but no search or navigation was observed",
    ),
    (
        "tab_opened: a new tab was opened; app_launched: 1 app(s) launched",
        "a new tab was opened; 1 app(s) launched",
    ),
    ("nothing was observed that could satisfy it", "nothing was observed that could satisfy it"),
])
def test_internal_check_names_are_stripped_from_user_facing_evidence(raw, expected):
    """GoalVerifier.verify_goal() prefixes each clause with its internal
    check name ("search_performed: ...") for task.metadata, where it is
    useful diagnostic grouping. That same prefixed string used to be
    spoken/shown to the user verbatim - "The goal was not achieved:
    search_performed: the browser was opened but no search or navigation
    was observed" - internal jargon nobody asked to hear."""
    assert _humanize_goal_evidence(raw) == expected


def test_empty_and_blank_segments_do_not_produce_stray_separators():
    assert _humanize_goal_evidence("search_performed: ok; ; tab_opened: also ok") == "ok; also ok"

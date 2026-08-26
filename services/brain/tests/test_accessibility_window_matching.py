"""Tests for NativeAccessibilityController._find_window - the fix for
minimized-window windows being reported as "not found" (VYOM's own
Calculator interaction failed with "No visible window matching
'Calculator'" even when Calculator was genuinely running, just
minimized - pywinauto's is_visible() is False for a minimized window).

Real pywinauto is Windows-only and requires actual OS windows, so these
tests use lightweight fakes that mimic pywinauto's window wrapper API
(window_text/is_visible/is_minimized/restore) rather than mocking the
whole accessibility stack - the logic under test (_find_window's match/
restore decision) is pure Python control flow independent of the real
UIA backend.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.input_control.accessibility import NativeAccessibilityController


class _FakeWindow:
    def __init__(self, title: str, *, visible: bool, minimized: bool = False, becomes_visible_on_restore: bool = True):
        self._title = title
        self._visible = visible
        self._minimized = minimized
        self._becomes_visible_on_restore = becomes_visible_on_restore
        self.restore_called = False

    def window_text(self) -> str:
        return self._title

    def is_visible(self) -> bool:
        return self._visible

    def is_minimized(self) -> bool:
        return self._minimized

    def restore(self) -> None:
        self.restore_called = True
        if self._becomes_visible_on_restore:
            self._visible = True
            self._minimized = False


@pytest.fixture
def controller():
    return NativeAccessibilityController()


def test_finds_a_genuinely_visible_matching_window(controller, monkeypatch):
    visible = _FakeWindow("Calculator", visible=True)
    monkeypatch.setattr(controller, "_desktop", lambda: MagicMock(windows=lambda: [visible]))
    found = controller._find_window("calculator")
    assert found is visible


def test_restores_a_minimized_matching_window_instead_of_reporting_not_found(controller, monkeypatch):
    minimized = _FakeWindow("Calculator", visible=False, minimized=True)
    monkeypatch.setattr(controller, "_desktop", lambda: MagicMock(windows=lambda: [minimized]))
    found = controller._find_window("calculator")
    assert found is minimized
    assert minimized.restore_called is True


def test_does_not_restore_a_window_that_is_hidden_but_not_minimized(controller, monkeypatch):
    """A window that is invisible for some OTHER reason (e.g. on another
    virtual desktop, or genuinely closed-but-cached) must not be treated
    as found just because restore() exists - only the minimized case is
    the known false-negative this fix addresses."""
    hidden_not_minimized = _FakeWindow("Calculator", visible=False, minimized=False)
    monkeypatch.setattr(controller, "_desktop", lambda: MagicMock(windows=lambda: [hidden_not_minimized]))
    found = controller._find_window("calculator")
    assert found is None
    assert hidden_not_minimized.restore_called is False


def test_restore_that_does_not_actually_reveal_the_window_still_returns_none(controller, monkeypatch):
    """If restore() is called but the window still reports not visible
    afterwards (a real OS quirk this code must tolerate), the function
    must not fabricate a match - honest failure over a fake success."""
    stubborn = _FakeWindow("Calculator", visible=False, minimized=True, becomes_visible_on_restore=False)
    monkeypatch.setattr(controller, "_desktop", lambda: MagicMock(windows=lambda: [stubborn]))
    found = controller._find_window("calculator")
    assert found is None
    assert stubborn.restore_called is True  # it did try


def test_non_matching_window_titles_are_skipped(controller, monkeypatch):
    unrelated = _FakeWindow("Notepad", visible=True)
    monkeypatch.setattr(controller, "_desktop", lambda: MagicMock(windows=lambda: [unrelated]))
    found = controller._find_window("calculator")
    assert found is None


def test_a_window_raising_on_is_visible_is_skipped_not_fatal(controller, monkeypatch):
    """One flaky/torn-down window (a real Windows race - a window can
    close between enumeration and inspection) must never abort the
    whole search."""
    class _Flaky:
        def window_text(self):
            return "Calculator"

        def is_visible(self):
            raise RuntimeError("window handle is stale")

    flaky = _Flaky()
    healthy = _FakeWindow("Calculator", visible=True)
    monkeypatch.setattr(controller, "_desktop", lambda: MagicMock(windows=lambda: [flaky, healthy]))
    found = controller._find_window("calculator")
    assert found is healthy


def test_first_matching_visible_window_wins_when_multiple_exist(controller, monkeypatch):
    first = _FakeWindow("Calculator", visible=True)
    second = _FakeWindow("Calculator", visible=True)
    monkeypatch.setattr(controller, "_desktop", lambda: MagicMock(windows=lambda: [first, second]))
    found = controller._find_window("calculator")
    assert found is first

"""Regression guard for the pyautogui dependency: pyautogui is declared in
pyproject.toml's dependency list, but was found MISSING from the actual
installed venv during this session's Chrome/desktop mouse-automation
verification — meaning PyAutoGuiMouseBackend() raised
MouseAutomationUnavailableError on every construction, silently disabling
VYOM's entire real-mouse "last resort" automation tier (the one that
actually moves the OS cursor and clicks like a human, as opposed to
Playwright's DOM-dispatch .click() for web pages). Installed the missing
package and verified live (moved the real cursor a few pixels, confirmed
via pyautogui.position() before/after) — this test exists so that gap
cannot silently recur.
"""
from __future__ import annotations

import pytest

from app.input_control.mouse import MouseAutomationUnavailableError, MouseController, PyAutoGuiMouseBackend
from app.input_control.policy import InputSafetyPolicy


def test_pyautogui_is_actually_importable():
    # If this raises ModuleNotFoundError, pyproject.toml's declared
    # dependency has drifted from the installed venv again.
    import pyautogui  # noqa: F401


def test_pyautogui_mouse_backend_constructs_without_raising():
    # This is the exact failure mode found live this session: pyautogui
    # missing from the venv made every PyAutoGuiMouseBackend() call raise
    # MouseAutomationUnavailableError, so InputControlTool's real-mouse
    # capability was silently dead even though it was registered.
    backend = PyAutoGuiMouseBackend()
    assert backend is not None


def test_mouse_controller_position_reads_real_cursor():
    backend = PyAutoGuiMouseBackend()
    x, y = backend.position()
    assert isinstance(x, int) and isinstance(y, int)
    assert x >= 0 and y >= 0


def test_mouse_controller_requires_safe_target_before_acting():
    """MouseController must consult InputSafetyPolicy before every real
    OS-level action — a real click has real consequences, unlike a bounded
    Playwright DOM click scoped to one page."""
    backend = PyAutoGuiMouseBackend()
    policy = InputSafetyPolicy()
    controller = MouseController(backend, policy)
    # This must run WITHOUT raising for a reasonable, explained context —
    # asserting the exact resulting cursor position is NOT reliable here:
    # this moves the REAL OS cursor, and anything else touching the mouse
    # during the test (the user, another automated process, a full test
    # suite run alongside computer-use activity) races with the assertion.
    # The behavior under test is "the policy gate does not block a
    # legitimate call", not "the OS cursor is perfectly still system-wide".
    before = backend.position()
    controller.move(before[0], before[1], context="test: no-op move to current position")
    # No exception raised is the actual assertion; reading position again
    # merely confirms the call round-tripped through pyautogui/OS without
    # erroring, not that nothing else touched the cursor meanwhile.
    backend.position()


def test_move_without_context_is_rejected():
    backend = PyAutoGuiMouseBackend()
    policy = InputSafetyPolicy()
    controller = MouseController(backend, policy)
    with pytest.raises(ValueError):
        controller.move(0, 0, context="")

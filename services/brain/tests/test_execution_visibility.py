"""Tests for the per-task execution-visibility decision
(app/execution/visibility.py). VYOM decides BEFORE executing a task
whether to run it in the BACKGROUND (headless browser, invisible backend
work) or VISUALLY on the user's screen (a real, on-screen browser
window / real OS mouse the user can watch).

Since the Aug-2026 window-stability pass the classifier errs toward
VISUAL by default: an invisible action the owner cannot see was the
root cause of "chrome kholo" complaints where nothing appeared on
screen. Explicit background markers ("in the background", "quietly")
still force BACKGROUND; these tests pin that behaviour and the
realistic phrasings a user actually types.
"""
from __future__ import annotations

from app.execution.visibility import TaskVisibility, classify_visibility


# -- visual: the default, see-the-work direction ------------------------------

def test_send_email_is_visual():
    assert classify_visibility("send an email to test@example.com with subject hi") == TaskVisibility.VISUAL


def test_backend_calculation_is_visual():
    assert classify_visibility("run the monthly sales calculation for this quarter") == TaskVisibility.VISUAL


def test_data_fetch_is_visual():
    assert classify_visibility("get me the TSLA stock price") == TaskVisibility.VISUAL


def test_empty_or_blank_request_is_background():
    assert classify_visibility("") == TaskVisibility.BACKGROUND
    assert classify_visibility(None) == TaskVisibility.BACKGROUND
    assert classify_visibility("   ") == TaskVisibility.BACKGROUND


# -- visual: explicit "I want to watch / show me / demo" --------------------

def test_show_me_how_is_visual():
    assert classify_visibility("show me how you search for that") == TaskVisibility.VISUAL


def test_watch_me_is_visual():
    assert classify_visibility("watch me open chrome and show the login page") == TaskVisibility.VISUAL


def test_demo_is_visual():
    assert classify_visibility("demo this automation for me on screen") == TaskVisibility.VISUAL


def test_let_me_see_is_visual():
    assert classify_visibility("let me see the browser, actually open it") == TaskVisibility.VISUAL


def test_open_the_app_is_visual():
    assert classify_visibility("open the calculator app for me") == TaskVisibility.VISUAL


# -- visual: interaction with a real desktop surface ------------------------

def test_click_element_is_visual():
    assert classify_visibility("click the green button on the site") == TaskVisibility.VISUAL


def test_fill_form_is_visual():
    assert classify_visibility("fill the signup form with my details") == TaskVisibility.VISUAL


def test_move_mouse_is_visual():
    assert classify_visibility("move the mouse to the top-right corner") == TaskVisibility.VISUAL


# -- negative markers win over visual keywords ------------------------------

def test_negating_phrase_overrides_watch_keyword():
    """'in the background' wins over a keyword like 'open' that would
    otherwise flip it visual."""
    assert classify_visibility("open the app but keep it in the background") == TaskVisibility.BACKGROUND


def test_do_it_quietly_is_background():
    assert classify_visibility("show me doing it, no wait - just do it quietly") == TaskVisibility.BACKGROUND

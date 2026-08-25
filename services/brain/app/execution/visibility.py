from __future__ import annotations

import re
from enum import Enum

# Keywords that signal the user explicitly WANTS to watch the automation
# happen on their screen (a real, non-headless browser / on-screen
# mouse) rather than have VYOM quietly do it in the background.
_VISUAL_MARKERS = (
    "show me", "show this", "let me see", "i want to see", "watch me",
    "show me how", "show me where", "demo", "demonstrate", "walk me through",
    "show it to me", "let me watch", "i want to watch", "take me to",
    "open the ", "open it", "let's open", "show on screen", "on my screen",
    "show me the", "show me your", "display it", "show the results",
    "show me in", "show it on", "look at this", "show me what",
)

# Tasks that inherently NEED a visible/on-screen surface to be meaningful
# (an app the user must interact with, or something being demonstrated).
_VISUAL_DOMAIN_MARKERS = (
    "click the", "click on", "type in the app", "type into the", "fill the form",
    "fill in the", "fill out the", "fill the", "sign up", "signup", "drag the",
    "open the app", "move the mouse", "click here", "double click", "right click",
    "enter my details", "enter your details", "log in", "login", "paste the",
)

_NEGATIVE_VISUAL_MARKERS = (
    "in the background", "quietly", "silently", "don't show", "minimize",
    "without opening", "just do it", "don't bother showing", "background",
)


class TaskVisibility(str, Enum):
    """How VYOM should present a task to the user.

    BACKGROUND : work invisibly (headless browser, backend API calls,
                 an email send, a calculation) — VYOM's own window may
                 minimize/hide while it works.
    VISUAL     : run on the user's visible screen — open a real, non-
                 headless browser (or move the real OS mouse) the user
                 can actually watch.
    """

    BACKGROUND = "background"
    VISUAL = "visual"


def classify_visibility(request: str) -> TaskVisibility:
    """Rule-based decision of whether a task should run in the background
    or be shown on the user's screen. Deliberately simple and
    conservative: an explicit request to WATCH (show me / demo / open /
    let me see) or an interaction with a real desktop surface is VISUAL;
    everything else defaults to BACKGROUND. This is NOT perfect AI
    intent-sensing — it is a deterministic, honest default that errs
    toward running invisibly unless the user asked to see something,
    which is the safe (non-disruptive) direction."""
    text = (request or "").lower().strip()
    if not text:
        return TaskVisibility.BACKGROUND

    # A negating phrase ("in the background", "just do it, don't show me")
    # wins over any keyword that would otherwise flip it visual.
    for marker in _NEGATIVE_VISUAL_MARKERS:
        if marker in text:
            return TaskVisibility.BACKGROUND

    # Explicit "I want to watch" phrasing.
    for marker in _VISUAL_MARKERS:
        if marker in text:
            return TaskVisibility.VISUAL

    # A task touching a real desktop surface (click/fill/drag/mouse) is
    # inherently visible to be meaningful.
    for marker in _VISUAL_DOMAIN_MARKERS:
        if marker in text:
            return TaskVisibility.VISUAL

    return TaskVisibility.BACKGROUND

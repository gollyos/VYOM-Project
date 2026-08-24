"""The Chrome extension bridge: VYOM's real-browser channel.

Everything under app.browser.* (playwright_manager.py, browser_session.py)
drives a SEPARATE, isolated Chromium instance VYOM launches itself - never
the user's actual signed-in Chrome. Everything under app.desktop.* reads the
user's real Chrome window through Windows UI Automation - real, but limited
to whatever text is visibly on screen, with no DOM access.

This package is a third channel: a paired Chrome extension running INSIDE
the user's real browser, holding a live WebSocket back to this Brain
instance. It gets VYOM genuine DOM access (full page text, not just visible
labels), tab control, and page interaction in the browser and profile the
user is actually signed into - the "find/analyze/act on what I'm looking
at" capability a screen-reader-style tool can only approximate.

It is additive, never a dependency: every ActionEngine browser handler
tries the extension first when connected and falls back to the existing
UI-Automation path on any failure, exactly like LLMTriage falls back to
old behaviour - an upgrade that can never become a new way to fail.
"""

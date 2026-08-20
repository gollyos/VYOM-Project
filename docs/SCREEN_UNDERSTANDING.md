# VYOM Screen Understanding

## Purpose

`services/brain/app/screen/` upgrades screenshot capture into structured
screen understanding, on request only. There is no continuous desktop
recording anywhere in this layer.

## Capture

`ScreenCapture` supports `full_screen`, `monitor` (via `WindowManager.
displays()`), `window` (via a matched `WindowInfo`'s bounds), and an
explicit `region`. `tools_builtin/screenshot.py` (extended from Phase 5,
not duplicated) exposes all four as the `screenshot` tool's `target`
values and emits a `screen_captured` event on every call. Capturing a
window whose title matches a configured sensitive-content hint is
refused outright.

## Privacy filter

`PrivacyFilter` does two things before any screen content reaches a
model: `is_sensitive_window(title)` blocks capture entirely for windows
that look like password managers, banking apps, private messaging, or
similar (`config` hints, extensible); `redact_text(text)` masks
API-key-, password-, card-number-, and private-key-shaped substrings in
any text pulled from the screen. Both are exercised before a
`ScreenObservation` is returned or a screenshot is sent onward.

## ScreenObservation

```text
active_application, active_window, visible_text, interactive_elements,
layout_summary, important_regions, possible_actions, confidence,
screenshot_path, redacted_secret_count, captured_at
```

`ScreenObserver.observe_active_window` populates what is deterministically
knowable (active app/window, geometry, a capture path) without inventing
`visible_text` — that field, along with `interactive_elements` and
`possible_actions`, is only populated when a vision-capable model or
accessibility text extraction actually enriches the observation. VYOM
never claims to have read on-screen text it did not actually read.

## "What am I looking at?"

`Phase9Engine._screen_context` implements: capture the active window (not
the whole desktop, since one window is sufficient) → observe → render a
`screenshot-preview` Composer object with the observed window/app and a
confidence score. If no window can be identified, the response says so
rather than guessing.

## Verification

A mouse click or app action is not evidence of success. `ScreenVerifier.
verify(observation, expected_application=..., expected_window_contains=...)`
checks the *observed* post-action state — used by
`Phase9Engine._open_project` to confirm the VS Code window is actually
visible before reporting the project as opened.

## Prompt-injection isolation

Text visible on screen (page content, dialog text, another app's window)
is untrusted data. Nothing in this layer evaluates `visible_text` as an
instruction to the Brain; a phrase like "ignore previous instructions"
appearing on screen is stored as inert observation data with no path to
changing permission level or tool selection (see
`test_screen_observation_text_from_untrusted_content_stays_inert_data`).

## Multi-monitor

`DisplayInfo` carries `display_id, resolution, position, scale, primary`
for every connected monitor; window-placement workflows never assume a
single display.

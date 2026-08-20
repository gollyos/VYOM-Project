# VYOM Desktop Security

## Principle

Desktop/device control extends the existing Phase 5 Execution Security
boundary; it does not weaken it. Every desktop, screen, input, or device
action still passes through the Permission Engine, the Tool Registry, and
the evidence/audit log — nothing in Phase 9 calls the OS directly outside
a registered tool.

## Permission table (extends docs/AUTONOMY_POLICY.md)

| Level | Examples |
| --- | --- |
| L0 | system status, list windows, read app/process status, startup status |
| L1 | open app, focus app, move/resize/minimize/maximize/restore window, send notification, clipboard read/write/clear, accessibility actions |
| L2 | close application, submit forms, enable/disable auto-start, stop a managed process, bounded mouse/keyboard fallback actions |
| L3 | install software, admin/elevated action, security changes, financial action (no execution path exists in Phase 9) |

## Input safety

`InputSafetyPolicy` (`services/brain/app/input_control/policy.py`)
enforces, on every mouse/keyboard fallback call: a known, non-empty
target/context (`require_safe_target`); rejection of sensitive-looking
fields — password, MFA/OTP/2FA, card number, recovery/seed phrase,
private key, PIN (`require_not_sensitive`, raises
`SensitiveInputBlockedError`); a bounded action count per sequence
(`check_sequence_bounds`); and a full action log
(`InputActionLogEntry`). If a sensitive field appears, the workflow must
pause and request user action — VYOM never guesses or bypasses it.

## Emergency pause

`EmergencyPauseState` is checked at the start of every mouse/keyboard
action via `InputSafetyPolicy.require_safe_target`. It is engaged by
`POST /api/desktop/emergency-pause` (which also cancels every active
task) and can be triggered by the global shortcut
(`CommandOrControl+Shift+Escape`, `src-tauri/src/lib.rs`), the tray, or a
voice "stop." Safety stop always takes priority over normal execution;
`resume` requires a separate explicit call
(`/api/desktop/emergency-resume`).

## Application trust

`ApplicationTrust` (`trusted | restricted | unknown`) gates how much
automation an app should receive; an `unknown` application discovered at
runtime is never assumed safe for sensitive input automation.

## Screen privacy

`PrivacyFilter` refuses to capture windows matching a sensitive-title
hint (password managers, banking, private messaging, security dialogs)
and redacts secret-shaped text before it reaches a model. See
`docs/SCREEN_UNDERSTANDING.md`.

## Untrusted content

Screen text and application state are data, never instructions. Nothing
in the desktop/screen/input layers evaluates observed text as a command
to the Brain; only the user's own request text drives the Permission
Engine's classification.

## Downloads and installation

Downloaded files remain untrusted per the Phase 8 Browser Agent policy —
recorded with metadata, never auto-executed. Phase 9 adds no software
installation path; VYOM may research or prepare an installation, but
actual system installation with elevated permissions requires explicit
approval and never bypasses UAC/admin prompts (no such bypass exists in
this codebase).

## Explicitly not implemented

Stealth/background screen recording, credential/password capture,
keylogging, security-control or MFA bypass, unrestricted remote access
from unknown devices, unrestricted admin commands, silent software
installation, autonomous financial actions, unrestricted deletion, or any
persistence mechanism designed to resist user removal. VYOM remains
user-controlled and auditable: `GET` the audit log / evidence bundle for
"what did you do on my PC?" answers real recorded events, never an
invented summary.

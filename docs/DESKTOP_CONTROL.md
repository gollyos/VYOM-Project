# VYOM Desktop Control

## Purpose

`services/brain/app/desktop/` gives VYOM safe, user-controlled native
desktop capabilities: application launching, window management,
clipboard, notification dispatch policy, system status, and
launch-at-login preference. `DesktopController` is the facade;
`tools_builtin/desktop.py` wraps it as the registered `desktop` tool so
every action still passes through the Permission Engine, evidence
collector, and audit log exactly like every other VYOM tool.

## Auto-start

`StartupController` enables/disables/reads Windows launch-at-login via a
user-scoped `HKCU\...\Run` registry value (`WindowsRegistryStartupBackend`)
that requires no elevated permission. The default is **disabled**
(`config/desktop.yaml`) and nothing in the codebase calls `enable()`
automatically — not on startup, not in tests. Tests use
`InMemoryStartupBackend`, which never touches the real registry. When
enabled, the flow is: PC login → VYOM desktop app starts → Brain
service starts/reconnects → task/automation recovery runs → the neural
biome enters Idle.

## System tray

The native tray (`src-tauri/src/desktop.rs`) exposes Open VYOM, Listen,
Pause VYOM, Pause Automations, Resume Automations, Current Tasks, and
Quit. Closing the main window hides it to the tray
(`install_close_to_tray`) rather than exiting — VYOM keeps running and
continues permitted background work until Quit is chosen explicitly. Only
"Open VYOM" and "Quit" are handled natively; every other item is relayed
to the frontend as a `tray-action` event, which calls the corresponding
Brain API (`/api/desktop/automations/pause-all`, `/resume-all`) or local
action (voice start, task cancel).

## Native notifications

`NotificationDispatcher` + `NotificationPolicy` decide *whether* a
notification is meaningful enough to show (approval required, reply
received, automation completed, task failed, meeting soon, coding task
completed, needs intervention) and rate-limit bursts
(`config/desktop.yaml`). The Brain has no window handle, so actual OS
toast delivery happens in the frontend: `use-vyom-runtime.ts` maps a
handful of existing Brain events to a title and calls the Tauri
`show_native_notification` command (`tauri-plugin-notification`).

## Windows and displays

`WindowManager` (pygetwindow) implements `window.list/focus/move/
resize/minimize/maximize/restore` through native Win32 window APIs — no
mouse dragging. `displays()` (screeninfo) reports `display_id,
resolution, position, primary` for every connected monitor, so window
placement commands ("put the editor on the left, browser on the right")
compute real geometry instead of assuming a single 1920×1080 screen.

`app_status`/`app_close` additionally verify against the visible window,
not just the launcher PID: some modern Windows apps (Windows 11's
re-hosted Notepad/Calculator) exit their launcher process moments after
starting, so PID-only tracking would under- or over-report app state.

## Clipboard

`ClipboardController` (pyperclip) exposes deliberate, single-shot
`clipboard.read/write/clear`. There is no continuous clipboard
monitoring, and sensitive-looking content (`looks_sensitive`) is never
automatically persisted into Phase 6 memory.

## System status

`SystemStatusService` (psutil) reports CPU/memory/storage/battery/network
and a count of VYOM-managed processes, computed on request — this is not
a permanent diagnostics dashboard. `Phase9Engine._system_status_explain`
turns "Why is my PC slow?" into safe-metric-based reasons (high CPU/
memory, low disk, no network) without inventing a cause it cannot
observe.

## Permission boundary

| Level | Desktop examples |
| --- | --- |
| L0 | system status, list windows, read app/process status, startup status |
| L1 | open app, focus app, move/resize/minimize/maximize/restore window, send notification, clipboard read/write/clear |
| L2 | close application, enable/disable auto-start, stop a VYOM-managed process |
| L3 | install software, admin/elevated action, security changes (not implemented in Phase 9) |

See `docs/DESKTOP_SECURITY.md` for the full rule set and
`docs/AUTONOMY_POLICY.md` for how this extends the existing L0–L3 table.

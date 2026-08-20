# VYOM Native App Automation

## Preferred execution order

```text
Native API / CLI / app integration
  -> accessibility / semantic UI automation
  -> browser automation (existing Browser Agent 2.0)
  -> controlled visual mouse/keyboard fallback
```

Screen coordinates are never the preferred method anywhere in this stack.

## Adapter architecture

`services/brain/app/native_apps/` defines `AppAdapter` (open/focus/close/
status) and `NativeAppAdapterRegistry`. Two real adapters exist:
`VSCodeAdapter` (CLI: `code <path>`) and `TerminalAdapter` (CLI: `wt`).
`VisualFallbackAdapter` is the generic fallback for any application
without a dedicated adapter — it still uses the Application Registry and
native OS process/window APIs only, never mouse/keyboard automation
directly. `tools_builtin/desktop.py`'s `app_open`/`app_focus` prefer a
registered adapter when one exists and fall back to the generic
`AppLauncher` otherwise.

Per item 19's own scope: this is architecture-first. Two adapters prove
the pattern; more (Cursor, file explorer, media/communication apps) can
be added without changing the registry.

## Application Registry

`ApplicationRegistry.from_config(config/applications.yaml)` resolves each
app's executable via `shutil.which` over a list of candidate names —
VYOM never assumes a hard-coded filesystem path exists. A record carries
`app_id, name, executable, launch_method, supported_actions,
integration_type, permissions, trust, health`. `discover()` can register
a not-yet-known app the same way, always starting `trust=unknown`.

## VS Code / editor integration

For coding, VYOM prefers filesystem, terminal, Git, and the Coding Worker
over typing into the editor. `VSCodeAdapter` only opens/focuses the
editor for the user; it never issues keystrokes into it. Autonomous code
changes remain file/tool based, matching the existing Phase 5 Coding
Worker boundary.

## Capability discovery

`register_adapter_capabilities` publishes one capability per (adapter,
action) — e.g. `native_app.vscode.open` — into the shared
`CapabilityRegistry`, so Discovery Engine and general capability search
can answer "does VYOM already have this?" for native-app work exactly
like tools/skills/agents/models/integrations.

## Application trust

`ApplicationTrust` is `trusted`, `restricted`, or `unknown`.
`config/applications.yaml` seeds VS Code, Windows Terminal, Notepad, and
File Explorer as `trusted`, and Chrome as `restricted` (its integration
type is `visual_fallback`, not a dedicated CLI/API). An `unknown`
application discovered at runtime never automatically receives sensitive
automation.

## Desktop workflow example

"Open my VYOM project" (`Phase9Engine._open_project`): resolve the
project path → open the VS Code adapter with that path → capture the
active window → verify the observed window is actually VS Code before
reporting success. No step assumes success without observing it.

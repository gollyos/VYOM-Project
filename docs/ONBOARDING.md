# VYOM Onboarding (Phase 13)

Modules: `services/brain/app/setup/` (schemas, onboarding, setup_state,
provider_setup, integration_setup, permission_setup, connection_test).
API: `/api/setup/*`. Frontend: `src/components/onboarding-overlay.tsx`.

## First run

The VYOM Core appears over the neural biome — never a generic SaaS
dashboard — with a minimal immersive flow: "Welcome. I'm VYOM." Then
only what is necessary is configured.

## Flow (13 steps, order-driven, dynamic)

intro → preferences → voice test → microphone → privacy → provider →
workspace → integrations → autonomy → notifications → startup →
diagnostics → ready

Required: intro, privacy, ready. Everything else is skippable
("Skip for now"); voice failing falls back to text — setup never
blocks on any optional piece.

## Voice test

A deliberate short sample with clearly visible microphone activity →
transcription check → response check. Failure keeps text available.

## AI provider setup

Dynamic from the Model Registry — no per-provider hardcoded UI:
select provider → enter credential (stored in the SecretStore
immediately, value never persisted elsewhere) → real health test →
available models/capabilities → save. A provider is only "connected"
after a real minimal interaction (`connected / authentication_failed /
rate_limited / network_error / unsupported_model / unconfigured`);
never merely because a key exists.

## Privacy choices (defaults are privacy-conscious)

external model usage (ask/allowed/local-only) · screen capture
(on-request/off) · personal memory (on/off) · crash-report sharing
(local by default) · telemetry (off; no cloud telemetry exists).

## Autonomy setup

Three understandable presets — Conservative / Balanced / Autonomous —
shown with exactly what each allows. Internally the L0–L3 rules are
unchanged; no preset can bypass L2/L3 approvals.

## Workspace setup

Register project/work roots explicitly ("Add my development folder"):
select path → inspect → Project metadata → permissions → verify
filesystem/Git/tool access. The entire filesystem is never granted.

## Startup preference

Optional launch-at-login, default disabled, never auto-enabled.

## State, resume, reset

`setup-state.json` persists `onboarding_version`, per-step status
(completed/skipped), preferences, privacy choices, and the preset.
Interrupted setup resumes from the persisted step without losing
already-stored credentials. New onboarding versions add steps without
forcing completed ones to repeat; a finished onboarding never
reappears (verified across restarts). Reset clears setup configuration
only — memories, projects, and secrets are untouched.

## After onboarding

PC startup/login → VYOM launches per preference → Brain connects →
health checks → neural biome → VYOM Core Idle. No dashboard. No setup
page. No chat page. Degraded layers surface only when relevant.

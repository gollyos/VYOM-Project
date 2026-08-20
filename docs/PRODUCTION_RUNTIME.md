# VYOM Production Runtime (Phase 13)

Modules: `services/brain/app/production/` (startup_checks, shutdown,
readiness, configuration, compatibility, middleware) and
`app/migrations/` (manager, validator, rollback).

## Configuration layers

`defaults < machine < user < runtime overrides`, kept separate; secrets
are not a config layer (SecretStore only). `ConfigValidator` strictly
validates every YAML at startup: parseability, known keys (strict for
`security.yaml`/`deployment.yaml`), version keys, and transport-safety
(any non-loopback bind is flagged). Invalid production configuration
fails clearly rather than silently using dangerous defaults.

## Startup

`StartupChecks` validates configuration, database, migration state,
secret store, required directories, and internal services. Optional
providers/integrations may stay disconnected. Outcomes:

- **ready** — all pass; `/readyz` returns 200.
- **degraded** — core healthy, warnings present (e.g. missing optional
  config keys); VYOM starts, `/readyz` 503 with reasons.
- **failed** — a required system failed; startup report records it and
  readiness stays down (never "pretend healthy").

`/healthz` = alive; `/readyz` = ready (alive-but-not-ready is a real,
distinguishable state — e.g. a failed migration).

## Graceful shutdown

`GracefulShutdown` (runs in lifespan teardown): stop accepting new
work (supervisor, scheduler, sync bridge) → checkpoint active tasks →
cancel/park remaining work → close action engine, browser, Playwright
→ flush and close the database last. Task state is never corrupted by
an abrupt exit.

## Database migrations

`MigrationManager` applies versioned migrations (`schema_migrations`
table): each has statements + a validation query; the applied record
is written only after validation passes. A failed migration marks
startup degraded/failed and surfaces recovery steps — never continues
pretending the database is healthy. Rollbacks are restore-based from
the pre-update backup (`migrations/rollback.py` plans and records
them; it never mutates the live database itself).

## Versioning & compatibility

`config/release.yaml` tracks app/brain/schema/protocol versions and
the release channel (development/alpha/beta/stable). The
`CompatibilityChecker` enforces deterministic schema/protocol ranges
for the database and connecting nodes; incompatible is rejected, not
guessed. `/api/production/version` shows versions + channel.

## Degraded mode behavior

Missing optional layers (Gemini, Gmail, an offline node) never block
startup; the UI shows only the relevant degradation ("Gemini is
unavailable. Local desktop commands and other providers remain
available."), and user-facing errors are actionable messages — raw
stack traces go to diagnostics/logs, not the Core.

## Alpha mode

Channel `alpha`: richer diagnostics and occasional reliability notices
are allowed, risky integrations stay disabled by default, and normal
interaction is never littered with developer/debug UI. The completed-
onboarding home remains the neural biome — no dashboard, no setup
page, no chat page.

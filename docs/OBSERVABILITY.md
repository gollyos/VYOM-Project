# VYOM Observability (Phase 13)

Modules: `services/brain/app/observability/` (structured_logging,
metrics, tracing, correlation, performance, cost_metrics,
crash_reports). Policy: `config/observability.yaml`.

## Correlation IDs

Every external request receives `request_id` + `trace_id` (middleware
honors incoming `x-request-id`/`x-trace-id`, echoes them and
`x-response-time-ms` on responses). ContextVars propagate the IDs
through Brain → task → tool → evidence; logs and spans carry them, so
failures trace end-to-end without exposing hidden reasoning.

## Structured logging

One JSON line per record: `timestamp, level, service, logger,
request_id, trace_id, [task_id], event, message/details, [error]`.
Levels DEBUG→CRITICAL; production default INFO. Size-based rotation
(`brain.log`, 5 MB × 5 backups). Redaction happens in the formatter —
before persistence. Hidden chain-of-thought is never captured
anywhere, and secrets never reach the file.

## Metrics

`MetricsRegistry`: counters/gauges/histograms with labels
(`task_success_total`, `task_failure_total`, `model_calls`,
`model_failures`, `tool_failures`, `queue_depth`, `model_cost`, ...)
exposed at `/api/observability/metrics`. Bounded sample windows; for
monitoring and diagnostics — never a permanent UI.

## Tracing

`Tracer` builds in-memory span trees (name, parent, duration, status)
with optional redacted JSONL export. `/api/observability/traces`.

## Performance monitoring

`PerformanceMonitor` records real timings against configurable
budgets from `observability.yaml` (command latency, planning, tool,
model, memory retrieval, health, reconnect, desktop startup) and
reports p95-vs-budget breaches at `/api/observability/performance`.
Results are measured, never invented.

## Cost observability

`CostTracker` aggregates live per-call records (provider, model, day:
calls, tokens, cost, failures, retries) plus the persisted
`model_performance` rows. `"How much did VYOM cost today?"` returns
real tracked data at `/api/observability/cost?days=N`, and the
Phase13Engine renders it as summoned Composer surfaces (metric +
provider table), not a billing dashboard.

## Crash reports

`CrashReporter` writes local, redacted crash files (versions, OS,
stack, recent safe events, correlation IDs, component health) under
`data/crash-reports` with retention bounds. No secrets, no raw
sensitive user data. External upload is opt-in only and not
implemented by design.

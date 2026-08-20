# VYOM Reliability (Phase 12)

Modules: `services/brain/app/reliability/` (health, supervisor,
recovery, watchdog, checkpoints, circuit_breaker, updates).

## Health

`HealthAggregator` registers lightweight checks for Brain, database,
task runtime, model providers, tool registry, MCP, email, calendar,
browser worker, desktop/mobile nodes, and the automation scheduler.
States: `healthy | degraded | offline | unknown` (unconfigured
integrations report `unknown`, never fake `healthy`). Checks are cheap
and deterministic — health monitoring never makes LLM calls. Exposed at
`GET /api/health`; degraded transitions emit `health_degraded` events.

## Leases

One node holds a task lease at a time (TTL from
`config/reliability.yaml`, default 120s). Workers heartbeat to extend.
On expiry the coordinator emits `task_lease_expired` and decides safe
handoff (portable tasks) or honest waiting.

## Checkpoints

Long-running tasks save `TaskCheckpoint`s (SQLite): task state, current
plan step, completed steps/tool calls, evidence references, pending
approval, budget consumed, artifacts. Hidden model reasoning is never
persisted. `GET /api/health/checkpoints/{task_id}`.

## Crash recovery

At Brain startup, `RecoveryService.recover()` inspects every persisted
active task:

```
checkpoint exists                     -> resume
consequential + external evidence     -> needs_review (never auto-retry)
consequential + tool calls executed   -> needs_review
lease held elsewhere, no checkpoint   -> retry
otherwise                             -> pause
```

Decisions are auditable at `GET /api/health/recovery`. A restart never
blindly repeats a consequential external action — the idempotency
records in `ownership.py` are the hard backstop.

## Circuit breakers

`CircuitBreakerRegistry` (closed → open → half-open) guards providers,
tools, MCP, integrations, and network paths. After N consecutive
failures (default 5) the breaker opens, dependent workflows stop
retrying (no retry storms), and after the cooldown it probes recovery.
Open transitions emit `circuit_breaker_opened`. Status:
`GET /api/health/circuit-breakers`.

## Watchdog (bounded recovery)

Stuck-task detection from real signals only: no progress event within
the stall window, expired lease, or repeated identical failures.
Response order: inspect → bounded retry (max_recovery_attempts,
default 3) → pause and notify the user. Never restart endlessly.

## Idempotency / duplicate-action prevention

Consequential actions reserve a durable `idempotency_records` key
before executing; a failover node attempting the same action key finds
the reservation and skips. This is the no-double-send guarantee for
email sends, calendar creation, bookings, client deliveries, and
payments (payment execution itself remains unimplemented by policy).

## Metrics

`ReliabilityMetrics` tracks task success rate, recovery count, uptime,
automation/provider outcomes, queue depth, and average task latency
from real recorded outcomes (`GET /api/health/metrics`) — for
reliability monitoring, not permanent UI clutter.

## Update foundation

`UpdateStateMachine` models
`available → downloaded → ready → installed` with `failed`/`rolled_back`
terminals and illegal-transition rejection. Phase 12 ships only this
foundation: no silent self-update of a production core. See
`docs/UPDATE_POLICY.md`.

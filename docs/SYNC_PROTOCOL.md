# VYOM Sync Protocol (Phase 12)

Modules: `services/brain/app/sync/` (schemas, journal, engine,
conflict_resolver, offline_queue, replication, bridge).

## What syncs

Only shared operational state:

```
tasks, task_events, approvals, agents, automations,
memory metadata (never memory content), goals, notifications,
device states
```

Large private files never replicate automatically; artifacts stream on
authenticated request only. Mobile receives a restricted entity set
(see `ReplicationManager.MOBILE_ENTITIES`).

## Event journal

`sync_journal` is append-only with a monotonically increasing `seq`.
Nodes reconcile by pulling `since(last_seq)`; history is never mutated.
`SyncEventBridge` streams selected Brain events (task lifecycle,
approvals, automations, node presence) into the journal so every device
can catch up from one place.

## Conflict policies (explicit, never blind last-write-wins)

| Entity | Policy |
| --- | --- |
| tasks | terminal state wins (completed/failed/cancelled is final) |
| approvals, agents, notifications, device states, task events | coordinator wins (conflict still recorded) |
| goals, automations | field-level merge with `_base`; fields edited on both sides are flagged and the coordinator value kept |

Every conflict is persisted in `sync_conflicts` for user review.

## Freshness

Each entity has a freshness window (`FRESHNESS_WINDOWS`). A cached
view older than its window carries `stale: true` — a device must never
present stale cache as live state (e.g. showing "running" when the
Brain knows "failed").

## Offline queue

Commands created offline are queued with an expiry:

- safe commands (L0/L1): TTL 24h, submit exactly once on reconnect
- consequential commands (L2/L3): TTL 5 minutes AND reconfirmation
  required — an offline "send email" never fires hours later silently

Expired commands are reported (`offline_command_expired`), never
executed.

## Replication policy

Per-node snapshots (`snapshot_for`) respect the node's entity set,
online status, and network class: large transfers defer on cellular
rather than retrying endlessly. Presence metadata (battery, network
type) is volunteered by nodes with heartbeats only — VYOM never
continuously collects device telemetry.

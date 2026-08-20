# VYOM Distributed Runtime (Phase 12)

VYOM may run across multiple trusted nodes:

```
Desktop (Tauri app)          — client + execution node
Laptop                       — client + execution node
Mobile (companion app)       — client device
Home Server (Docker/host)    — worker + execution node
Optional Cloud Worker        — worker (opt-in, never required)
```

## Roles

| Role | Responsibility |
| --- | --- |
| Brain Coordinator | the FastAPI Brain: node registry, leases, dispatch, sync journal, approvals |
| Execution Node | runs tasks that match its registered capabilities |
| Client Device | issues commands/approvals (desktop UI, mobile) |
| Worker Node | always-on background execution (automations, research, artifacts) |

A device may hold multiple roles. Roles are declared at registration
(`DeviceNode.roles`) and tracked in the durable node registry.

## Modules (`services/brain/app/distributed/`)

- `leases.py` — SQLite-backed task leases: one node owns a task at a
  time; missed heartbeats expire the lease and the coordinator decides
  safe retry/handoff.
- `ownership.py` — task ownership + durable idempotency records so a
  node failover can never double-execute a consequential action
  (email/booking/payment).
- `node_router.py` — deterministic placement: capable, online, trusted
  nodes only; preferred/fallback order; privacy, GPU, battery and
  network awareness. No model call is involved.
- `task_dispatcher.py` — router → lease → budget check → audit → event.
  Deferred (`deferred_budget`) or honest (`no_capable_node`) when it
  cannot place work; it never pretends a capability exists.
- `task_handoff.py` — portable tasks (no local files/project/GPU
  dependency) hand off to another eligible node; non-portable tasks
  wait for their owner, honestly.
- `coordinator.py` — node lifecycle with protocol-version gating,
  presence transitions, expired-lease handling, global
  pause-everything/resume, and the cross-node network summary.
- `budgets.py` — global 24/7 budgets (model cost, research calls,
  concurrency, agents, browser sessions) with hard-limit enforcement.
- `audit.py` — append-only distributed audit ("which device ran
  this?").
- `oversight.py` — "What did VYOM do while I was away?" built only
  from real persisted records.

## Home Server / always-on node

`deploy/docker-compose.yml` runs the Brain as a persistent service
(brain + scheduler + worker responsibilities). The desktop gaming/work
PC is never required to stay powered on: research/email/calendar/
automation workloads route to the home server through capability-based
placement. Desktop-only capabilities (local coding, screen, apps)
simply wait for the Desktop Node to come online.

## Workload placement examples

```
Email research                -> Home Server (task.research)
Compile local Windows project -> Desktop Node (task.coding + local files)
Mobile notification           -> Mobile Node (notifications.send)
GPU-heavy local model         -> capable node only (compute.gpu)
```

## Background automation 24/7

The Phase 7 Automation Runtime already persists definitions/runs with
schedule-slot idempotency. Phase 12 keeps it on the always-on Brain
process so desktop UI closure never stops permitted automations; the
Supervisor (`reliability/supervisor.py`) expires stale leases and
surveys health alongside it. Automations may declare
`required_capabilities`/`preferred_node`/`fallback_nodes` through the
same `TaskRequirements` placement contract.

## Explicitly out of scope

Unrestricted remote desktop, stealth remote access, arbitrary device
takeover, remote keylogging, background microphone/camera, silent
public internet exposure, unapproved remote installation, autonomous
real-money execution. See `docs/NODE_SECURITY.md`.

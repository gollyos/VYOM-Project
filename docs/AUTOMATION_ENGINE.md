# Durable Automation Engine

Supported definitions are one-time, scheduled, recurring, and conditional. Every automation declares timezone, action, permission level, and budgets for daily runs, runtime, tool calls, and cost tier.

Definitions and runs persist in SQLite. The scheduler polls in the Brain background, recovers only a bounded number of due items, and uses a hash of automation ID plus scheduled slot as an idempotency key. One-time/scheduled work completes once. Recurring work advances from the observed completion time, avoiding an unbounded missed-run backlog.

Failures pause an automation. Daily run limits pause runaway work. Unknown actions fail closed. The first registered background action prepares a source-aware agency briefing and performs no external side effect.

L2/L3 definitions cannot be auto-enabled. Future consequential automations must create a fresh per-run approval; an approval never authorizes an unlimited schedule. Default limits live in `config/automations.yaml`.

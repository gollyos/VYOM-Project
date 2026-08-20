# VYOM Data Handling (Phase 13)

Policy: `config/production.yaml` (`data:` section).

## Data classification

Every piece of runtime data carries an explicit classification:

- **real** — produced by a live provider/integration/tool interaction
- **mock** — deterministic fixture/demo data (always labeled; e.g.
  `local-fixture` market data is labeled `mock` in every payload)
- **cached** — stored copy of earlier real data with an as-of stamp
- **stale** — cached data past its freshness window (never shown live)

Mock/demo data is isolated from production data: tests use temp
databases, demo providers are labeled, and the production runtime
never presents a mock value as real (regression-tested).

## Retention

| Data | Retention |
| --- | --- |
| Structured logs | size-rotated (5 MB × 5) |
| Security audit events | 365 days (append-only) |
| Audit/evidence JSONL | durable, bounded by usage |
| Screenshots | 14 days (on-request captures only) |
| Crash reports | newest 20 |
| Temporary artifacts | cleaned after 72 h (never user files) |
| Backups | newest N (default 10), versioned |

## Temporary files

Controlled temp storage with safe stale-cleanup (Doctor's only
automatic repairs). Cleanup never deletes user files.

## File permissions

Sensitive state (database, secrets metadata, logs, backups) lives
under per-user directories; the DPAPI secret vault is
current-user-only by construction. Avoid world-readable sensitive
state: on Windows, user-profile ACLs provide this by default; server
deployments must set equivalent ownership.

## Export / portability

Non-secret configuration and data can be exported (backup manifest
JSON, CRM/task exports through existing APIs). Secrets never appear
in plain exports — the vault is excluded from backups and exports by
design.

## Telemetry

None. VYOM functions fully without cloud telemetry; if ever added it
must be opt-in, minimal, documented, and redacted. Crash-report
upload is opt-in only and currently not implemented at all.

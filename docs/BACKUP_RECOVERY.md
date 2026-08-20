# VYOM Backup & Recovery (Phase 12)

Modules: `services/brain/app/backup/` (snapshot, validation, restore,
manager). API: `/api/backup`.

## What gets backed up

- The SQLite Brain database (via sqlite3's online backup API — safe
  while the Brain runs): tasks, automations/runs, CRM, goals, habits,
  memory, nodes/tokens(hashed), leases, sync journal, audit.
- `config/` (YAML policy).
- `data/` artifacts: skills, agents, artifacts (versioned).

## Exclusions

Secrets (`services/brain/data/secrets`, any `secrets` directory) are
always excluded — backups never contain plaintext credentials.
`node_modules`, caches, and build outputs are excluded too.

## Schedules and versioning

`manual | daily | weekly` (default manual, per
`config/reliability.yaml`). Every backup is a new timestamped directory
with a `manifest.json` (per-part sha256, size, app/schema versions) —
a backup never overwrites the only known-good copy. Retention keeps the
newest N (default 10) and prunes older ones.

## Encryption

Sensitive backups support an encryption flag in the manifest; the
snapshot format reserves `encrypted: true`. (OS-level/disk encryption
plus the secrets exclusion is the current default posture; a built-in
encryption passphrase flow is intentionally not hand-rolled in
Phase 12.)

## Validation

A restore can only proceed if the backup passes `BackupValidator`:
manifest parseable, every part's sha256 matches, and the embedded
database passes `PRAGMA integrity_check`. Corrupt backups are rejected
loudly (`409`), never restored.

## Restore flow

```
select backup → validate → show metadata (preview endpoint)
→ stop relevant services safely (scheduler/supervisor quiesce)
→ copy database through a verified temporary file
→ integrity re-check → replace live database
→ restart_required flagged (operator restart; never silent)
```

Restore refuses to run without `confirm: true`.

## Disaster recovery playbook

| Scenario | Recovery |
| --- | --- |
| Corrupt DB | stop Brain → restore newest valid backup → restart → `GET /api/health/recovery` |
| Failed update | restore the pre-update backup; update state machine supports `rolled_back` |
| Lost node | revoke the node's credentials from any trusted device |
| Provider failure | circuit breaker opens; work defers; degrade is visible in `/api/health` |
| Worker failure | lease expires; portable tasks hand off; others wait honestly |
| Damaged config | `config/` is inside every backup; restore or re-place the YAML |

## Database lifecycle safety

Schema changes only add tables/columns through `CREATE TABLE IF NOT
EXISTS` — migrations never drop or silently rewrite existing user data;
restore-time integrity checks guard against partial schema drift.

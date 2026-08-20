# VYOM Update Policy (Phase 12)

Foundation only: `reliability/updates.py` models the update lifecycle.
Phase 12 deliberately implements **no silent self-update** and no
forced updates.

## States

```
available → downloaded → ready → installed
                  └───────┴──→ failed (terminal)
installed → rolled_back (terminal)
```

Illegal transitions raise — an update can never skip states or
un-fail itself in code.

## Safety sequence (when updates are implemented)

```
check compatibility (protocol/schema versions)
→ checkpoint (database + config snapshot)
→ backup (BACKUP_RECOVERY.md flow)
→ apply
→ health checks (/api/health overall healthy)
→ rollback from the pre-update backup if critical failure
```

## Rules

1. Updates are always user-initiated and user-visible.
2. A pre-update backup is mandatory before apply.
3. Nodes report app/protocol/schema versions; the coordinator rejects
   protocol-incompatible nodes rather than mixed-version chaos.
4. Rollback restores the pre-update backup; the update state moves to
   `rolled_back` and stays visible.
5. VYOM never self-modifies its core/security code autonomously (same
   boundary as the Phase 6 learning policy).

## Current state

The desktop build is produced via `npm run desktop:build` and
distributed as a native executable (`bundle.active` remains false; no
auto-updater is wired). The Brain updates by redeploying the process/
container. This document defines the contract future updater work must
follow.

## Phase 13 status

The update state machine, backup-before-update policy, restore-based
rollback plan, release channels (alpha current), and release
manifest/checksum tooling are implemented and tested. Signed
auto-update distribution is architecture-only: **no signing keys are
configured in this environment**, so updater artifacts are not
produced and the end-to-end update flow is UNVERIFIED.

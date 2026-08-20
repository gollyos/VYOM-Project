# VYOM Release Engineering (Phase 13)

Config: `config/release.yaml`. Scripts (repo `scripts/`):
`package-release.py`, `verify-release.py`, `production-check.py`,
`security-check.py`, `smoke-test.py`.

## Release channels

`development | alpha | beta | stable` (current: **alpha**). The
channel is visible in diagnostics/version info. Development/test
databases are always separate from production data (tests use temp
directories; `VYOM_BRAIN_DATABASE` points production elsewhere).

## Packaging

Primary OS: Windows. The Tauri app builds an NSIS current-user
installer (`VYOM_<version>_x64-setup.exe`). The installer installs
VYOM and creates application directories. It never silently enables
startup, opens firewall ports, installs unrelated software, or sends
telemetry.

## Release pipeline (`scripts/package-release.py`)

```
tests (pytest, required)
→ frontend build (required)
→ Tauri build + NSIS package (required)
→ release manifest
```

Any failed required step stops the release. The manifest
(`release/manifest-<version>-<channel>.json`) records version,
channel, build timestamp, brain/schema/protocol versions, included
migrations, and sha256 checksums of every artifact.
`scripts/verify-release.py` re-validates the manifest.

## Production gate (`scripts/production-check.py`)

Brain tests → strict config validation → Brain boot + startup report
(ready/degraded) → doctor + security audit → frontend build →
`cargo check`. Documented invocation:
`python scripts/production-check.py` (`--skip-native` to skip Rust).

## Updates

- Never silent auto-install; user-initiated only.
- Sequence: preflight → backup (BACKUP_RECOVERY.md) → update →
  migrations → health checks → accept; on critical failure, restore
  the pre-update backup (`rolled_back` state in the update machine).
- Signed-update architecture is required for production distribution;
  no signing keys are configured in this environment, so updater
  artifacts are NOT produced — **UNVERIFIED**, honestly. The staging
  foundation (state machine, backup-before-update policy, rollback
  plan) is implemented and tested.
- Update UI is transient ("VYOM Alpha 0.2 is available" with changes/
  risk/restart), never a permanent page.

# VYOM Legacy Cleanup Report — 2026-08-20

Baseline: 15.07 GiB, 31,881 files. Recovery checkpoint: `8ab1fc88003d93a9574799e7fae9fdcd60827ac1`.

| Path | Size | Category | Reference/import evidence | Runtime usage evidence | Risk | Action |
| --- | ---: | --- | --- | --- | --- | --- |
| `src-tauri/target/debug/` | 12,234.47 MiB | GENERATED_SAFE_TO_DELETE | Ignored by Git; no source/build reference consumes pre-existing debug objects | Recreated by Cargo when tests/dev builds run | Low | Delete; rerun Rust tests later, then remove regenerated debug objects after recording results |
| `src-tauri/target/release/` | 2,878.71 MiB | OLD_BUILD_SAFE_TO_DELETE | Ignored build output | Contains the current 2026-08-19 executable and installer used by the last mic preflight | Medium | Keep until the exact new release is built; afterward retain `vyom.exe` and installer, remove intermediate dependency/incremental objects only |
| `node_modules/` | 266.02 MiB | CACHE_SAFE_TO_DELETE | Lockfile is authoritative; directory is ignored | Needed locally for frontend/release builds | Low | Keep during reconstruction; optional deletion only after final release verification |
| `dist/` | 1.07 MiB | GENERATED_SAFE_TO_DELETE | Vite output; ignored | Current frontend bundle consumed by Tauri builds | Low | Keep current verified build; it will be replaced by the final frontend/release build |
| `.vyom-build-check/` | 1.05 MiB | GENERATED_SAFE_TO_DELETE | Explicit fallback output documented in project memory; ignored | Used only when `dist` is locked | Low | Delete; recreated on demand |
| `.pytest_cache/`, `services/brain/.pytest_cache/`, `.pytest-run-20260820*` | <0.05 MiB | CACHE_SAFE_TO_DELETE | No runtime references | Pytest metadata/temp only | Low | Delete |
| `%SystemDrive%/ProgramData/Microsoft/Windows/Caches/` | 0.94 MiB | GENERATED_SAFE_TO_DELETE | No repository references; literal `%SystemDrive%` directory proves an unresolved-variable test artifact | Not under any configured runtime data path | Low | Delete entire literal `%SystemDrive%` subtree |
| `services/brain/services/brain/data/phase5-verification*` | 0.89 MiB | GENERATED_SAFE_TO_DELETE | No imports or config point at the nested `services/brain/services` path | Phase 5 test DB/audit output; production DB is `services/brain/data/vyom-brain.db` | Low | Delete nested test-artifact subtree |
| `phase5-test-note.txt`, `vyom-runtime-test.txt` | 0.1 KiB | GENERATED_SAFE_TO_DELETE | The first is only the default name for a test write and is recreated by the capability; the second has no references | Not read during startup/runtime | Low | Delete files |
| Root `brain-*.log`, `services/brain/data/logs/*`, `services/brain/data/tool-audit.jsonl` | 0.75 MiB | LOG_SAFE_TO_ROTATE | Referenced as physical/runtime evidence by the reconstruction mandate and ledger | Newest physical-user truth source | Medium | Preserve through this pass; rotate only after user mic acceptance |
| `services/brain/data/vyom-brain.db*` and `.bak` | 29.0 MiB | REQUIRED | Authoritative configured persistence plus recovery backup | Active durable tasks, memory, experience, commitments, sync, and evidence | Critical | Never delete in cleanup |
| `data/backups/` | 3.2 MiB | REQUIRED | Backup subsystem output | User recovery material | High | Keep |
| Root phase scripts and `services/brain/scripts/p0_replay*.py` | <0.1 MiB | LEGACY_RUNTIME_CANDIDATE | Not imported by production | Repro/verification utilities only | Medium | Keep for reproducibility; consider archiving after physical acceptance |
| Phase engine modules (`phase8`, `phase9`, `phase10`, `phase11`, `phase13`) | source | REQUIRED | Instantiated once in `app/main.py` and delegated by the authoritative Task Runtime | Live production registrations and tests | High | Keep; these are feature delegates, not duplicate Brains |
| Specialized verifiers (`browser`, `screen`, `coding`, booking/delivery/research) | source | REQUIRED | Called under their domain engines/tools; `runtime/verifier.py` remains whole-goal owner | Domain observations feed the whole-goal verifier | High | Keep; responsibility is layered, not duplicate terminal authority |

## Source-duplication conclusion

The repository has one production `TaskRuntime`, one `MissionLoop`, one `EventBus`, one general `Planner`, one `ToolRegistry`, one `CapabilityRegistry`, one `ActionEngine`, one `MemoryStore`/`MemoryRetriever`, one `ModelRouter`/`ProviderHealth`, and one `SecretStore`. `AutomationScheduler` owns durable automations; `RoutineScheduler` adapts routines onto that service rather than creating a second autonomous scheduler. The generic reliability circuit-breaker registry and provider-health breaker serve different domains. No source deletion is justified by the current import/runtime evidence.

## Final cleanup outcome

- Final measured workspace: **0.33 GiB / 15,127 files** (baseline: 15.07
  GiB / 31,881 files).
- Removed verified generated material: Rust debug objects, 11 reconstruction
  pytest temp trees, two temporary Brain launch logs, literal unresolved-path
  test artifacts, nested Phase 5 test data, and obsolete test-note files.
- After the successful final release build, removed 2.8 GiB of Rust release
  compiler intermediates (`deps`, `build`, fingerprints, library/link outputs)
  while retaining the exact verified deliverables:
  `src-tauri/target/release/vyom.exe`, its diagnostic PDB, and
  `src-tauri/target/release/bundle/nsis/VYOM_0.2.0_x64-setup.exe`.
- Preserved the production Brain database, backup data, audit/evidence logs,
  lockfile, dependencies needed to run the current project, source, tests, and
  reconstruction checkpoint commit.

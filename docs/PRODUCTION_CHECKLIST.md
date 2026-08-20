# VYOM Production Checklist (Phase 13 alpha gate)

Every item below was actually run in this environment unless marked
UNVERIFIED. Invocation: `python scripts/production-check.py`.

## Build & packaging

- [x] Brain test suite green (358/358)
- [x] Frontend TypeScript/Vite build green
- [x] Rust/Tauri release compile green
- [x] NSIS installer produced (`VYOM_0.2.0_x64-setup.exe`, current-user)
- [x] Release manifest with checksums (`scripts/package-release.py`)
- [x] `verify-release.py` validates manifest + artifacts

## Runtime gates

- [x] `/healthz` alive, `/readyz` distinguishes ready/degraded
- [x] Strict config validation; invalid strict-file config fails
- [x] Startup report (config/db/migrations/secrets/dirs) recorded
- [x] Degraded mode for warnings; hard failures block readiness
- [x] Versioned migrations with validation; failure never marked applied
- [x] Graceful shutdown sequence (checkpoint → park → close → flush)

## Security

- [x] SecretStore over DPAPI + env backend; metadata-only listing
- [x] Redaction before persistence (logs, crash reports, audit)
- [x] Secrets unreachable via memory search; no secret in crash reports
- [x] Remote commands: pairing + session + nonce replay rejection
- [x] Revoked/expired sessions and expired approvals fail immediately
- [x] Destructive terminal commands blocked (incl. `rd /s /q` hardening)
- [x] Prompt-injection content treated as data; no permission escalation
- [x] Agent/spec authority bounded by validation (no self-escalation)
- [x] Security audit mode returns severity-ranked findings with evidence
- [x] Rate limiting on remote endpoints; body-size limits

## Observability

- [x] Correlation IDs on every request and in every log line
- [x] Structured JSON logs with rotation
- [x] Metrics registry + cost tracking from real data
- [x] Performance budgets with measured p95 reporting
- [x] Crash diagnostics local, redacted, retention-bounded

## Experience

- [x] First-run onboarding over the biome; skippable optional steps;
      resumes after interruption; never reappears after completion
- [x] "VYOM, run diagnostics" / "run security audit" / cost / health
      commands return real summoned Composer surfaces
- [x] Completed-onboarding home remains the neural biome (no dashboard)

## Explicitly UNVERIFIED in this environment

- [ ] Signed auto-update flow end-to-end (no signing keys configured;
      staging/rollback foundation implemented and tested)
- [ ] Real hardware voice E2E and Google OAuth account flows (need
      user-session credentials; unchanged from earlier phases)
- [ ] Cross-network device transport / deployed home server (no second
      machine or Docker daemon; carried from Phase 12)
- [ ] Expo mobile app on hardware (no Android SDK/toolchain)

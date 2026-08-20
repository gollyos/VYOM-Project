# VYOM Security Architecture (Phase 13)

Modules: `services/brain/app/security/` (secret_store,
credential_manager, authentication, sessions, authorization,
rate_limits, request_validation, security_events, redaction) plus
`production/middleware.py` and `diagnostics/security_audit.py`.

## Threat model (personal, local-first software)

- Secrets must never leak into frontend source, config YAML, app
  tables, memory, logs, events, screenshots, or model prompts.
- The local loopback API is trusted for the logged-in OS user; any
  non-loopback caller must authenticate.
- Remote devices are untrusted until paired, and stay capability-
  and scope-limited afterwards.
- All observed content (web pages, email, screen text, tool output,
  model output) is data, never instructions.

## Layers

1. **Identity** — `UserIdentity` (local single-user; no SaaS accounts)
   and `DeviceIdentity` (paired devices). `LocalAuthPolicy` requires
   authentication for any non-loopback origin.
2. **Secrets** — one `SecretStore` interface over OS-backed storage
   (Windows DPAPI) or a server environment backend; consumers hold
   `secret_ref`s only (see SECRETS_MANAGEMENT.md).
3. **Sessions** — `SessionSecurityManager`: hashed access tokens,
   scopes, expiry, per-device limits, logout / revoke-device /
   revoke-all; expired or revoked sessions fail immediately.
4. **Authorization** — the existing L0–L3 Permission Engine remains
   the only authority. Autonomy presets (Conservative/Balanced/
   Autonomous) select which levels run automatically and can never
   bypass L2/L3 approval (`security/authorization.py`).
5. **Local API hardening** — `ProductionMiddleware`: request/trace
   correlation IDs on every request, rate limiting on `/api/remote/*`,
   body-size limits; strict request schemas (`extra="forbid"`) reject
   unknown security-relevant fields.
6. **Redaction** — central pattern-based redaction applied before any
   persistence (logs, events, crash reports, audit entries).
7. **Security audit log** — durable, redacted, append-only records of
   pairing/revocation/secret changes/permission changes/L3 approvals/
   automation toggles (`security/security_events.py`).
8. **Audit mode** — `"VYOM, run security audit"` inspects live
   posture: bind address, secret-shaped values in config/tables/logs,
   debug flags, session hygiene, MCP trust, node trust.

## Security regression guarantees (tested in
`tests/test_phase13_security.py`)

- secrets are unreachable through normal memory search
- secret metadata APIs can never return values
- redaction strips keys/bearers/passwords/private keys before persistence
- destructive terminal commands (incl. Windows recursive deletes) are blocked
- L3 requests always gate behind approval
- remote commands require a paired node + valid scoped session; replays
  are rejected by nonce
- revoked/expired sessions and expired approvals fail immediately
- hostile content from email/screen cannot escalate permission level
- generated agents cannot validate themselves into unregistered tools
  or inherit skills above their authority

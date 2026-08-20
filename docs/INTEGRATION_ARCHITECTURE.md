# VYOM Integration Architecture

Phase 7 introduces integrations as replaceable Brain-side providers. The React/Tauri presentation layer receives health, events, and validated compositions; it never receives OAuth tokens or provider secrets.

## Runtime boundary

```text
command / local API
  -> Integration Registry and capability health
  -> domain service (email, calendar, contacts, research)
  -> provider adapter
  -> verifier (provider IDs / read-back evidence)
  -> business event + contextual UI composition
```

`config/integrations.yaml` declares identity, category, enabled state, and capabilities. Disabled or disconnected providers remain visible as unavailable. Registration does not grant authority. Reads use L0, local drafts and CRM writes use L1, and external sends/bookings use L2 approval.

## OAuth and secrets

OAuth starts and completes only through the local Brain. State values are random, one-time, and compared in constant time. Token bundles are written through `SecretVault`. The production Windows adapter protects bytes with current-user DPAPI and writes only ciphertext under Brain data. The in-memory adapter exists only for tests. Tokens are never returned by an API, event, composition, log, memory, or frontend state.

Gmail, Google Calendar, Contacts, and lead research are disabled by default. Their contracts exist, but Phase 7 does not claim a live connection without configured OAuth transport and successful health.

## Health and failure

Statuses are disconnected, connecting, connected, degraded, error, and reauth-required. Missing configuration produces an explicit unavailable result. External fixtures are labeled `test-fixture` and cannot be mistaken for live business data.

# VYOM Secrets Management (Phase 13)

Module: `services/brain/app/security/secret_store.py` +
`credential_manager.py`.

## What counts as a secret

AI provider API keys, OAuth/refresh tokens, MCP credentials,
integration secrets, device credentials, future broker credentials.

## Where secrets may live

- Desktop/local machine: the OS secure store — Windows current-user
  DPAPI (`WindowsDPAPISecretVault`), ciphertext only on disk.
- Server deployment: process environment / secret-manager backend
  (`EnvironmentSecretBackend`, read-only, `VYOM_SECRET_<KIND>_<OWNER>`
  naming).

## Where secrets never live

React source, config YAML, normal application SQLite tables, Memory,
logs, task events, screenshots, crash reports, model prompts (unless a
tool specifically needs the credential inside the trusted layer).

## The one interface

```python
set_secret(ref, value, kind=, owner=)
get_secret(ref)                 # trusted execution layer only
delete_secret(ref)
has_secret(ref)
rotate_secret(ref, new_value)
list_secret_metadata()          # metadata only — can never return values
```

Refs look like `provider/openai/default`, `integration/gmail/default`.
Metadata (kind, owner, created/rotated/last-used timestamps) persists
beside the vault; values never do.

## Secret references

Application data stores `secret_ref` strings, never values. The
`CredentialManager` resolves refs inside the trusted execution layer
(with optional environment fallback per provider) and exposes only a
`[REDACTED]` description for logs/audit. Models never see secrets.

## Rotation and revocation

`rotate_secret` replaces the value atomically and stamps `rotated_at`.
Device revocation (`/api/nodes/{id}/revoke`) deletes the device
credential hash and invalidates its sessions. Secret changes are
recorded in the security audit log (without values).

## Backups

Backups exclude secret storage entirely (see BACKUP_RECOVERY.md); a
restored backup re-attaches to the machine's existing OS vault.

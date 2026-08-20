# VYOM Integration Setup (Phase 13)

Modules: `app/setup/integration_setup.py`, `provider_setup.py`,
`connection_test.py`; MCP setup rides the existing restricted-trust
MCP registry (`docs/MCP_ARCHITECTURE.md`).

## Dynamic integration wizard

Built from the Integration Registry — Gmail, Calendar, Contacts, and
future integrations appear automatically; nothing is hardcoded per
provider in the UI. Flow:

```
select integration → see requested scopes BEFORE connecting
→ authenticate → inspect granted permissions
→ real connection test → capability discovery → save
```

Nothing authenticates silently, and scopes are always shown first.

## Provider setup wizard

Built from the Model Registry: provider list with per-provider model/
capability metadata and credential hints. Credentials go straight
into the SecretStore as `provider/<name>/default`; the value is
consumed in-setup and never persisted anywhere else. Connection
outcomes are honest (`connected / authentication_failed /
rate_limited / network_error / unsupported_model / unconfigured`) —
a stored key alone never marks a provider connected.

## MCP setup

Trusted MCP servers can be configured through setup. Before enabling,
VYOM shows server, source, transport, exposed tools, permissions, and
trust level. A new MCP server stays restricted until explicitly
trusted under the existing Phase 5 policy — setup cannot grant trust.

## Workspace setup

Project/work roots are registered explicitly; VYOM inspects the path,
creates project metadata, applies permissions, and verifies
filesystem/Git/tool access. Only selected roots are granted — never
the whole filesystem.

## Connection testing

`ConnectionTest` performs real minimal health interactions with
timeouts, mapping failures to precise outcomes so the setup UI can
say "authentication expired — reconnect" instead of a stack trace.

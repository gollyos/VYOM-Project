# VYOM Node Security (Phase 12)

Modules: `devices/` (pairing, authentication, registry, heartbeat,
store), `remote/` (session, command_gateway, approvals, notifications),
`distributed/coordinator.py` (version gating).

## Pairing

```
device requests pairing (8-char code, TTL 5 min)
→ user approves on an existing trusted device/user context
→ credentials exchanged once; node registered as TRUSTED
→ node heartbeats; capabilities granted ⊆ allow-list
```

Pairing is never silent. Pairings, hashed tokens, trust levels, and
revocations are durable (SQLite `nodes`/`node_tokens`) so they survive
Brain restarts.

## Device identities and credentials

- `node_id` + long random token, stored server-side as SHA-256 only.
- Plaintext tokens exist once, in the pairing/rotation response.
- Mobile stores its token in the OS-backed secure store
  (`expo-secure-store`); VYOM never stores custom PINs.
- Credential rotation: `DevicePairingService.rotate()` replaces the
  hash; old token immediately fails authentication.

## Transport

- The Brain binds `127.0.0.1` by default. Remote access is only through
  a user-configured secure channel (private network / reverse proxy
  with TLS + device tokens). VYOM never silently exposes ports and
  never hardcodes port-forwarding.
- Production deployments should run TLS + device authentication +
  token rotation + revocation + rate limiting at the proxy edge.

## Remote command security

Every remote command envelope carries `command_id`, `source_node`,
`session_id`, `timestamp`, `nonce`, `permission_context`. The gateway
rejects, in order: unknown node → untrusted node → invalid/expired
session → timestamp outside the acceptance window (default 120s) →
replayed nonce (durable uniqueness). Only then does the command enter
the normal Permission Engine path.

## Remote approvals

Approval views always show requested action, reason, impact, agent,
evidence, and risk. L2 approvals can be decided remotely. L3 requires
strong verification — the device's biometric/OS secure confirmation
attestation — and the Brain refuses one-tap blind approval otherwise.
Approvals expire (default 30 min); expired approvals can never execute
without re-evaluation.

## Revocation

`POST /api/nodes/{id}/revoke` revokes trust, deletes the credential,
invalidates all active sessions for that node, stops accepting its
commands, and records the audit trail. A lost phone is neutralized from
any trusted device; VYOM does not perform destructive remote wipes of
the user's whole device.

## Version compatibility

Nodes report app/protocol/schema versions. The coordinator rejects
protocol-major mismatches (`409`) rather than accepting an incompatible
node.

## Least privilege

- Capability grants are intersected with the explicit allow-list.
- Mobile invokes Brain capabilities; it never receives provider keys.
- Secrets stay node-local and never replicate to other nodes.
- Command routing still refuses capabilities a node was not granted.
- Remote "desktop control" is limited to high-level registered Phase 9
  tools (open project, run task, pause VYOM) — no raw mouse/screen
  streaming.

## Phase 13 additions

`SessionSecurityManager` adds scoped, expiring, hashed-token sessions
with logout/revoke-device/revoke-all; `ProductionMiddleware` rate-
limits remote endpoints and stamps correlation IDs; the security audit
command inspects bind posture, secret-shaped leakage, and session
hygiene. All remote-facing rules above remain unchanged.

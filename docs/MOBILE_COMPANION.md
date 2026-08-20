# VYOM Mobile Companion (Phase 12)

App: `apps/mobile/` (React Native + Expo). Secure pairing, authenticated
commands and durable result delivery are implemented. Dependencies are
installed and strict TypeScript compilation passes. Real-device E2E remains
deferred because no Android SDK/emulator or physical phone is available.

## Architecture

Mobile is a **client device**, not a Brain. It holds:

- device identity + one pairing token (OS secure store only)
- a session ID from `POST /api/remote/session`
- minimal cached state (offline queue, last summaries)

It never holds provider/model credentials and never runs tools itself.

## Authentication

Pairing (8-char code → user approval on a trusted device) → token →
one-time mobile claim → session. Pair approval is local-PC only. Wrong/expired credentials are rejected 401; revoked nodes lose
their sessions immediately.

## Command flow

```
voice/text command
→ POST /api/remote/command  (id, source_node, session, timestamp,
                             nonce, permission context)
→ Brain validates + Permission Engine
→ Task Runtime creates the task (L2/L3 still gate to approvals)
→ terminal result enters the node's durable authenticated delivery inbox
→ mobile reads and acknowledges it
```

Voice commands from desktop and mobile route to the same Brain/context
system; conversation context is reconstructed from structured task/
session state (`remote/session.py`), never raw model context. Voice
session handoff ("How far did you get?" on mobile after starting on
desktop) resolves through the persisted active-task context.

## Approvals

`GET /api/remote/approvals` requires a node-bound session and returns full context (action, reason,
impact, agent, evidence, risk). Decisions: approve / reject / modify /
pause / cancel. L3 remains denied by the current mobile UI because OS biometric
attestation is not implemented; no one-tap blind approval is claimed.

## Notifications

Routing by priority: informational → desktop/batch; urgent approvals →
mobile + desktop; critical → all trusted active devices (respecting
quiet mode). Push payloads are sanitized — sensitive content is
replaced with "Details require unlocking VYOM." Read/acted/dismissed
state syncs through the journal, so reading on mobile stops desktop
nagging.

## Offline behavior

- Allowed offline: view cached status (always labeled cached, never
  live), queue commands, write notes, record reminders.
- Queued commands submit exactly once on reconnect.
- Consequential (L2/L3) queued commands expire in 5 minutes and always
  require reconfirmation — never a delayed silent send.

## Limitations (honest)

- The Expo app compiles but is not yet run on hardware here.
- Push notifications use a provider abstraction with no live push
  provider configured yet.
- Physical-phone connections must use HTTPS (local TLS proxy/VPN); plain LAN
  HTTP is rejected by the client.
- No watch/wearable, no home-screen widgets, no background location.

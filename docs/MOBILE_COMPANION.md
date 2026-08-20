# VYOM Mobile Companion (Phase 12)

App: `apps/mobile/` (React Native + Expo scaffold). In-repo
verification path: `services/brain/scripts/phase12_mobile_mock.py`
(mock node) + Phase 12 tests. Real-device E2E is deferred — the Expo
toolchain is not installed in this environment.

## Architecture

Mobile is a **client device**, not a Brain. It holds:

- device identity + one pairing token (OS secure store only)
- a session ID from `POST /api/remote/session`
- minimal cached state (offline queue, last summaries)

It never holds provider/model credentials and never runs tools itself.

## Authentication

Pairing (8-char code → user approval on a trusted device) → token →
session. Wrong/expired credentials are rejected 401; revoked nodes lose
their sessions immediately.

## Command flow

```
voice/text command
→ POST /api/remote/command  (id, source_node, session, timestamp,
                             nonce, permission context)
→ Brain validates + Permission Engine
→ Task Runtime creates the task (L2/L3 still gate to approvals)
→ progress streams through the sync journal
→ notification when relevant
```

Voice commands from desktop and mobile route to the same Brain/context
system; conversation context is reconstructed from structured task/
session state (`remote/session.py`), never raw model context. Voice
session handoff ("How far did you get?" on mobile after starting on
desktop) resolves through the persisted active-task context.

## Approvals

`GET /api/remote/approvals` returns full context (action, reason,
impact, agent, evidence, risk). Decisions: approve / reject / modify /
pause / cancel. L3 requires the device biometric/OS confirmation flag —
no one-tap blind approval. Approvals expire after 30 minutes.

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

- The Expo app is scaffolded, not yet built/run on hardware here.
- Push notifications use a provider abstraction with no live push
  provider configured yet.
- No watch/wearable, no home-screen widgets, no background location.

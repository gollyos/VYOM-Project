# VYOM Mobile Companion (Phase 12 scaffold)

React Native + Expo companion for the VYOM Brain. Mobile is **not** a
clone of the desktop neural canvas: it is a voice-first command surface
with the simplified VYOM Core presence, quick commands, approvals,
notifications, and device status.

## Status

Architecture and screens scaffolded; not yet built or run on a device
in this environment (no Expo toolchain/Android SDK installed here).
The in-repo verification path for mobile flows is the Brain-side mock
mobile node (`services/brain/scripts/phase12_mobile_mock.py`) plus the
Phase 12 API tests — real device E2E is explicitly deferred.

## Pairing

1. Brain: `POST /api/devices/pair` → 8-char code.
2. User approves on an existing trusted device (desktop) →
   `POST /api/devices/pair/{request_id}/approve` returns the node +
   one-time token.
3. Mobile stores the token with `expo-secure-store` (OS-backed, never
   plaintext). No PINs are ever stored by VYOM itself.

## Command flow

`vyomClient.command(text)` → `POST /api/remote/command` with
`command_id`, `source_node`, `session_id`, `timestamp`, `nonce`,
`permission_context`. The Brain rejects replayed, expired, or
unauthenticated commands before anything executes. Consequential
(L2/L3) commands still flow through the existing Permission Engine.

## Approvals

`GET /api/remote/approvals` returns the full context (action, reason,
impact, agent, evidence, risk). L3 approvals require the device's
biometric/OS secure confirmation flag — the Brain refuses one-tap
blind approval of L3 actions.

## Offline

Commands created offline queue locally (AsyncStorage) and flush exactly
once on reconnect. The Brain expires consequential queued commands
quickly (default 5 minutes) and requires reconfirmation — an offline
"send email" never fires hours later silently. Cached data is always
labeled "Offline — cached", never shown as live.

## Running (requires local Expo toolchain)

```bash
cd apps/mobile
npm install
npx expo start
```

The Brain URL defaults to `http://127.0.0.1:7788` (use a real device's
reachable address on your network; see docs/DEPLOYMENT.md for secure
remote access — never expose the Brain's raw API to the internet).

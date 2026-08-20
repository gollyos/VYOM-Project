# VYOM Mobile Companion

React Native + Expo companion for the VYOM Brain. Mobile is **not** a
clone of the desktop neural canvas: it is a voice-first command surface
with the simplified VYOM Core presence, quick commands, approvals,
notifications, and device status.

## Status

Secure pairing, remote commands and durable result delivery are implemented.
Declared Expo dependencies are installed and strict TypeScript compilation
passes. The app has not been run on Android/iOS hardware in this environment
because no Android SDK/emulator or physical phone is available.

## Pairing

1. Brain: `POST /api/devices/pair` → 8-char code.
2. User approves locally on the VYOM desktop with
   `POST /api/devices/pair/{request_id}/approve`.
3. Mobile claims the approved identity once with its original code at
   `POST /api/devices/pair/{request_id}/claim` and stores the token with
   `expo-secure-store` (OS-backed, never
   plaintext). No PINs are ever stored by VYOM itself.

## Command flow

`vyomClient.command(text)` → `POST /api/remote/command` with
`command_id`, `source_node`, `session_id`, `timestamp`, `nonce`,
`permission_context`. The Brain rejects replayed, expired, or
unauthenticated commands before anything executes. Consequential
(L2/L3) commands still flow through the existing Permission Engine.

## Approvals

`GET /api/remote/approvals` requires the node and session headers and returns the full context (action, reason,
impact, agent, evidence, risk). The current app sends no strong-verification
claim, so L3 approval remains denied until a real OS biometric integration is
added; a plain boolean is not presented as biometric proof.

Completed remote tasks are placed in the durable authenticated
`/api/remote/deliveries` inbox. Mobile acknowledges each delivery only after it
has read it; session IDs travel in headers rather than URLs.

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

The pairing screen defaults to `https://vyom.local`. Mobile rejects plain HTTP
for non-loopback hosts so its pairing token/session cannot cross a LAN in
plaintext. Put a local TLS reverse proxy/VPN in front of the loopback-bound
Brain; never expose the raw Brain API to the internet.

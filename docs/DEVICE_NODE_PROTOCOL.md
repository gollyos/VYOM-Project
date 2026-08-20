# VYOM Device Node Protocol

## Purpose

`services/brain/app/devices/` is the foundation for future trusted
devices (laptop, mobile, home server) exposing approved capabilities to
VYOM. Phase 9 delivers the protocol and local-node testing only — no real
remote network transport is implemented yet (`node_server.py`'s
`MockLocalDeviceNode` stands in for a second physical machine).

## DeviceNode

```text
node_id, name, device_type, platform, capabilities, trust_level,
online, last_seen, permissions, version
```

`device_type` is `desktop_pc | laptop | mobile | home_server`.
`trust_level` is `unpaired | pending | trusted | revoked`. `online` is
`online | offline | degraded`, computed live from `HeartbeatMonitor`, not
stored as a stale flag.

## Pairing and authentication

```text
pair -> approve -> authenticate -> rotate -> revoke
```

`DevicePairingService.start_pairing` issues a random, TTL-bound code
(`config/devices.yaml`, default 300s, bounded pending-request count).
`approve` intersects the device's *requested* capabilities with an
explicit *allowed* list — a device never receives more than it was
granted, even if it asked for more — and returns a bearer token whose
SHA-256 hash is stored; the plaintext token is returned exactly once and
never persisted. `authenticate` uses constant-time comparison.
`rotate`/`revoke` are available for credential hygiene. No
unauthenticated command is ever accepted:
`DevicePairingService.authenticate` raises for an unknown node rather
than silently denying.

## Capabilities

`DeviceCapability` is `screen.capture | notifications.send | file.read |
file.write | app.open | location.read | camera.capture | microphone`.
`config/devices.yaml`'s `capability_allow_list` is the ceiling; approval
can only grant a subset of it, and a node's own capability claims are
never trusted beyond what was explicitly approved.

## Command routing

`DeviceCommandRouter.route` checks, in order: node exists → node is
`TRUSTED` → token authenticates → node is `online` (per current
heartbeat, not a cached flag) → node has the specific capability. Only
then is a `DeviceCommand` handed to a transport (today, `
MockLocalDeviceNode.execute`). A remote node never receives unlimited
authority, and every command still passes through the same Permission
Engine boundary as any other VYOM action once a real transport exists.

## Heartbeat

`HeartbeatMonitor` reports `online` while a heartbeat arrived within half
the configured `offline_after_seconds`, `degraded` up to the full window,
and `offline` beyond it (`config/devices.yaml`, default 60s). A device
with no recorded heartbeat is `offline` by default — VYOM never pretends
an unreachable device completed an action.

## API surface

`api/devices.py`: `POST /api/devices/pair`, `POST /api/devices/pair/
{request_id}/approve`, `GET /api/devices`, `POST /api/devices/{node_id}/
heartbeat`, `POST /api/devices/{node_id}/revoke`.

## Future work

A real authenticated network transport (WebSocket/HTTPS) for genuinely
remote nodes, a durable multi-machine registry backing store, and routing
real device commands (e.g. "open this file on my laptop") through the
same flow once a second physical node exists.

# VYOM Deployment (Phase 12)

Topology config: `config/deployment.yaml`; compose files in `deploy/`.

## 1. Local Desktop Only (default)

```
Windows PC
├─ VYOM Tauri desktop app (native, fullscreen Living Core)
└─ VYOM Brain (uvicorn, 127.0.0.1:7788) — tasks, automations, memory
```

- Requirements: Python 3.12 (`pip install -e services/brain[prod]`),
  Node 20+, Rust/Tauri toolchain for the desktop build.
- Ports: Brain binds loopback 7788 only. No external exposure.
- Secrets: node-local (DPAPI vault under `services/brain/data/secrets`).
- Persistence: `services/brain/data/vyom-brain.db` (+ WAL).
- Backups: `data/backups` (see BACKUP_RECOVERY.md).
- Security: everything stays on-device; the desktop app connects over
  localhost. Automations run while the Brain process is up; the desktop
  window may be closed as long as the Brain process keeps running
  (tray minimization keeps the app alive).

## 2. Desktop + Home Server (always-on worker)

```
Home Server (Docker host / mini PC / NAS / Linux box)
└─ vyom-brain container (deploy/docker-compose.yml)
     brain + scheduler + 24/7 automations + research/artifact worker

Windows Desktop
└─ VYOM desktop app + local Brain (or remote Brain URL)
```

- Requirements: Docker/Podman on the server; ~512 MB RAM is ample for
  the worker profile.
- Run: `docker compose -f deploy/docker-compose.yml up -d --build`.
- Ports: published to `127.0.0.1:7788` on the host by default. Reach it
  across your LAN only deliberately, and prefer a private network
  (Tailscale/WireGuard-style) or a local reverse proxy with TLS and
  device tokens. Never port-forward the raw API to the internet.
- Secrets: provider keys stay per-node (environment of the container /
  DPAPI on the desktop). Secrets never replicate between nodes.
- Persistence: named volume `vyom-data`; back it up by scheduling
  `/api/backup` (daily) and copying `data/backups` off-host.
- Node registration: desktop/home-server nodes register as TRUSTED via
  the operator endpoint (`POST /api/nodes/register`); phones/laptops go
  through the explicit pairing flow.

## 3. Optional Cloud Worker

Cloud mode is **opt-in and never required** — local-first remains the
default for sensitive data. Capability requirements by location:

```
local-only : filesystem, terminal, browser, native apps, screen
server     : research, email, calendar, automations, artifact generation
cloud-optional : extra research capacity, backup offloading
```

A cloud worker runs the same Brain image, registers as a worker node,
and only receives work explicitly marked cloud-acceptable
(`privacy: cloud_ok`); `local_only` work can never route to it. Do not
point a cloud deployment at your desktop's secret vault.

## Safety invariants (all modes)

- No silent public internet exposure; no hardcoded port-forwarding.
- Remote devices authenticate (pairing + session + nonce).
- The desktop Tauri app remains a native/local install — it is never
  converted into a hosted web app.
- `Ctrl+Shift+Escape` emergency pause and tray Quit always work on the
  desktop; nothing prevents the user from disabling or removing VYOM.

# VYOM Project Continuation Instructions

These instructions apply to the entire repository.

## Required context before implementation

1. Treat `docs/VYOM_PROJECT_MEMORY.md` as the repository-local product requirements source of truth. Its historical source is `C:\Users\GunjanAdmin\Downloads\VYOM_PROJECT_MEMORY.md`.
2. Read `VYOM_IMPLEMENTATION_STATUS.md` to learn what is already implemented, verified, deferred, or limited.
3. Do not repeat a full audit of completed work unless a relevant regression or contradiction is found.

## Required status maintenance

After every material implementation pass and before handing work back to the user:

1. Update the timestamp and relevant status entries in `VYOM_IMPLEMENTATION_STATUS.md`.
2. Add the completed work to its change log.
3. Record only tests/builds/runtime checks that were actually performed.
4. Record unresolved errors and environmental limitations explicitly.
5. Never mark an item complete until it has been verified in proportion to its risk.

Keep the ledger concise enough to resume work quickly, but complete enough that the next session does not need to rediscover project history.

## Permanent architecture boundary

VYOM is a native desktop application built with Tauri 2, Vite, React, TypeScript, Three.js, and React Three Fiber. Do not convert it into a website, SaaS dashboard, Next.js application, SSR application, or marketing-page structure. Preserve the Living Core as the home experience and add later capabilities as modular native features only when requested.

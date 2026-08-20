# VYOM — Native Living Core V0

VYOM is a native personal AI environment. The current implementation includes the Living Core, Dynamic UI Composer, Gemini Live voice runtime, persistent local VYOM Brain, and a controlled Phase 5 tool-execution layer inside a Tauri desktop shell.

`voice/text → classify → plan → select registered tools → permission check → execute → verify → evidence → structured UI composition → return to calm`

For the authoritative record of what is implemented, verified, deferred, and next, read [`VYOM_IMPLEMENTATION_STATUS.md`](./VYOM_IMPLEMENTATION_STATUS.md) before starting work.

## Stack

- Tauri 2 native desktop shell
- Vite + React + TypeScript
- Three.js + React Three Fiber
- Gemini Live WebSocket bridge in Rust
- Python + FastAPI asynchronous Brain service
- SQLite task and model-performance persistence
- Registered filesystem, terminal, Git, Playwright browser, screenshot, and safe system tools
- YAML tool/model registries, evidence audit, cancellation, and process tracking
- Local-first, fullscreen runtime

## Development

```powershell
npm install
npm run desktop:dev
```

The native command requires the Rust toolchain and Windows WebView2 build prerequisites. `npm run dev` runs only the Vite preview surface for frontend iteration.

## Brain development

Install once:

```powershell
cd "C:\VYOM Project\services\brain"
python -m pip install -e ".[test]"
```

Run the Brain in one terminal, then the native app in another:

```powershell
cd "C:\VYOM Project\services\brain"
python -m uvicorn app.main:app --host 127.0.0.1 --port 7788
```

```powershell
cd "C:\VYOM Project"
npm run desktop:dev
```

The Brain uses `config/models.yaml` and `config/tools.yaml`. External model providers require both a backend API key and an explicit model ID from `services/brain/.env.example`. Phase 5 tool demos use the deterministic `local-tool-planner-v1`, so they do not require or spend paid-model tokens. Allowed filesystem roots and tool availability remain backend-owned.

Run verification with:

```powershell
cd "C:\VYOM Project\services\brain"
python -m pytest -q
python scripts\smoke_demo.py
python scripts\phase5_smoke.py
```

Phase 5 demo commands:

- `Inspect this project and tell me if it builds correctly.`
- `Create a simple test file in the project, verify it exists, then show me what you did.`
- `Open the project's local app and verify the home screen loads.`
- `Run the tests.`
- `Show me what changed.`
- `Delete that file.` — pauses for L3 approval.

## Voice configuration

Gemini credentials are read only by the Rust/Tauri process. They are never bundled into frontend JavaScript or returned to the webview.

```powershell
$vyomGeminiKey = Read-Host "Gemini API key" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new("", $vyomGeminiKey).Password
Remove-Variable vyomGeminiKey
npm run desktop:dev
```

Optional runtime overrides are `VYOM_GEMINI_LIVE_MODEL` (default `gemini-3.1-flash-live-preview`) and `VYOM_GEMINI_VOICE` (default `Kore`). Set persistent credentials through Windows user environment settings rather than committing them to the repository.

## V0 boundary

V0 now contains the desktop shell, Living Core states, neural biome, text fallback, UI Composer, voice runtime, persistent tasks, model routing, structured planning, permission approvals, registered tools, real filesystem/terminal/browser execution, coding verification, WebSocket events, evidence, cancellation, and contextual execution visuals. Unrestricted shell/PC control, email, deployment, trading, real agents, durable workers, and production automation remain intentionally unavailable.

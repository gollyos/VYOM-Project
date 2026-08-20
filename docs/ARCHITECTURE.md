# VYOM Architecture

## Runtime shape

VYOM remains a native Tauri 2 desktop application. The React/TypeScript webview owns presentation only: the Living Core, neural biome, voice controls, and schema-driven UI Composer. It does not contain provider credentials or provider-specific task logic.

```text
Tauri desktop
  -> local Brain API (HTTP + WebSocket)
  -> Task Runtime
  -> classifier / permission engine / planner
  -> Model Router
  -> provider adapter OR controlled Tool Execution Layer
  -> verifier / persistence / performance memory
  -> operational events + structured UI composition
  -> existing UI Composer over the neural biome
```

The Brain is an asynchronous Python/FastAPI service under `services/brain`. SQLite is the Phase 4 persistence adapter, not a domain dependency. Task and performance stores isolate the runtime from the database so PostgreSQL or a durable workflow engine can replace it later.

## Responsibility boundaries

- Desktop: microphone, audio playback, native window, visual state, command entry, and rendering.
- Brain API: local transport, validation, task control, approvals, model/provider visibility, and event streaming.
- Task Runtime: lifecycle orchestration and truthful state transitions.
- Classifier: deterministic classification for obvious requests; no expensive model call for simple commands.
- Permission Engine: L0–L3 enforcement before consequential work.
- Planner: concise structured steps and dependencies; never private chain-of-thought.
- Model Router: cheapest reliable capable model, bounded fallbacks, optional verifier.
- Provider adapters: credentials, request/response normalization, health and usage.
- Verifier: structured checks and evidence before completion.
- UI Composer: renders only validated structured visualization requests; it remains data-driven and page-free.

## Phase 5 Tool Execution Layer

```text
Task Runtime
  -> deterministic tool intent / structured plan
  -> Tool Registry (`config/tools.yaml`)
  -> Permission Engine
  -> Action Engine
  -> registered filesystem / terminal / Git / Playwright / screenshot / system / MCP tool
  -> bounded observation, retry, cancellation, and process tracking
  -> Evidence Collector
  -> Verifier
  -> operational events + contextual UI composition
```

The `ActionEngine` handles known tool workflows without requiring a paid model. The first Coding Worker discovers each workspace's stack and runnable commands instead of assuming one framework. Real tool output is normalized through `ToolResult`; failed builds/tests/browser checks cannot become verified tasks.

Browser automation uses semantic Playwright actions and a reusable session. Background dev processes are task-owned and cleaned up on cancellation or Brain shutdown. MCP tools are adapters beneath the same registry and permission boundary.

## Phase 6 Long-term Intelligence Layer

```text
Task Runtime
  -> scoped memory retrieval + provenance
  -> unified Capability Registry
  -> equivalent Skill / Agent search
  -> bounded Skill Executor or Agent delegation
  -> central tools, permissions, budgets, audit, evidence, verifier
  -> outcome/failure analysis
  -> consolidated memory + performance metrics
  -> contextual memory / skill / agent / lesson UI objects
```

SQLite now persists typed memory and lightweight relationships. Hybrid retrieval combines structured scope, keyword and provider-independent local semantic signals with recency, importance, confidence, verification, and relationships. Superseded or forgotten records do not remain active context.

Skills and agents are versioned declarative artifacts under `data/`; they do not become independent authority. Generated L0/L1 skills must pass sandbox policy tests before activation. Agents must inherit permissions, use scoped memory, respect budgets, validate capabilities, and pass a sample mission. The first real reusable skill and dynamic agent reuse the Phase 5 Coding Worker rather than duplicating execution code.

Learning remains event-driven. Verified failures may produce explicitly inferred, evidence-linked lessons under controlled rules. The improvement layer may tune memory, declarative procedures, configurations, and performance preferences, but cannot rewrite the permission engine, security/secret boundaries, approval policy, or production bootstrap.

Phase 6 adds `memory`, `skills`, `agents`, `capabilities`, and `learning` modules plus local APIs. The UI Composer gained memory-cluster and skill-procedure primitives and continues deriving agent/learning work surfaces from structured runtime data instead of routes or dashboards.

## Phase 7 Daily-work Operating Layer

```text
Task Runtime / local domain API
  -> Business Engine
  -> Integration Registry + current health
  -> Email / Calendar / Contacts / CRM / Agency / Meetings services
  -> permission-scoped external provider adapter
  -> provider-ID verifier + business events
  -> durable automation / source-aware briefing
  -> contextual Composer objects over the Living Core
```

Internal CRM, drafts, approvals, automation definitions, and runs persist in SQLite. Gmail, Calendar, Contacts, and lead research are provider abstractions and stay disconnected until configured. Windows OAuth token bundles are protected with current-user DPAPI outside frontend state and model memory.

The scheduler is a bounded Brain worker with timezone-aware definitions, idempotent schedule-slot runs, restart recovery, daily/runtime budgets, failure pause, and no missed-run avalanche. Consequential recurring actions cannot auto-enable; L2 sends and meeting creation require scoped approval and provider confirmation IDs.

## Phase 8 Web Intelligence and Delivery Layer

```text
Task Runtime
  -> Phase8Engine (mirrors BusinessEngine/IntelligenceEngine)
  -> DeepResearchTask (plan / discover / rank / extract / cross-check / synthesize / verify)
  -> Browser Agent 2.0 (semantic observe/act/verify over the registered browser tool)
  -> Discovery Engine (capability/subscription/MCP/API/SaaS)
  -> Booking Engine (search/compare/reserve/verify, provider-pluggable, disconnected by default)
  -> Artifact Engine (render/validate/version real report/diagram/spreadsheet/presentation files)
  -> Client Delivery (quality-gated package + duplicate-safe send)
  -> Phase 8 events + contextual Composer objects over the Living Core
```

Research, browser automation, discovery, booking, and artifact generation
are tools the central Brain composes through `Phase8Engine` — the desktop
shell gains no new browser-wrapper surface. All Phase 8 orchestration is
deterministic (no paid model call) and routes through the existing
Permission Engine, Tool Executor, and evidence collector; nothing here
bypasses them. See `docs/RESEARCH_ARCHITECTURE.md`,
`docs/BROWSER_AGENT.md`, `docs/DISCOVERY_ENGINE.md`,
`docs/BOOKING_POLICY.md`, `docs/ARTIFACT_ENGINE.md`, and
`docs/CLIENT_DELIVERY.md`.

Booking and client-delivery providers default to disconnected, matching the
Phase 7 integration honesty pattern; the research module's
`LocalFixtureSearchProvider` is the one Phase 8 exception, and it is always
explicitly labeled `local-fixture`, never presented as live data.

## Phase 9 Native Desktop / Device Execution Layer

```text
Task Runtime
  -> Phase9Engine (mirrors BusinessEngine/IntelligenceEngine/Phase8Engine)
  -> desktop tool (apps, windows, clipboard, notifications, system status, startup)
  -> screenshot / screen_observe tools (on-request capture + structured ScreenObservation)
  -> input_control tool (accessibility-first, bounded mouse/keyboard fallback)
  -> Native App Adapters (VS Code, Windows Terminal, generic visual fallback)
  -> Device Node protocol (pairing/heartbeat/command routing, local-node tested)
  -> Phase 9 events + contextual Composer objects over the Living Core
```

Every desktop/screen/input action still executes through the existing
Tool Registry, `ToolExecutor`, Permission Engine, and evidence collector
— Phase 9 adds capability, not a bypass. The Rust/Tauri shell
(`src-tauri/src/desktop.rs`) owns what only the native process can own:
system tray, native notification delivery, and the emergency-pause global
shortcut; the Brain owns everything else. See `docs/DESKTOP_CONTROL.md`,
`docs/SCREEN_UNDERSTANDING.md`, `docs/NATIVE_APP_AUTOMATION.md`,
`docs/DEVICE_NODE_PROTOCOL.md`, and `docs/DESKTOP_SECURITY.md`.

Startup (auto-start-at-login) defaults to disabled and is never enabled
by code, dev runs, or tests. Device nodes are a local protocol foundation
only in this phase — no real remote transport is configured, matching the
Phase 7/8 integration honesty pattern.

## Phase 10 Finance Intelligence and Paper Trading Layer

```text
Task Runtime
  -> Phase10Engine (mirrors BusinessEngine/Phase8Engine/Phase9Engine)
  -> market_data (provider-independent quotes/candles/fundamentals + freshness)
  -> finance (Instrument/Watchlist/Portfolio + P&L/exposure/metrics)
  -> market_intelligence (technical analysis, regime, catalysts, thesis)
  -> trading (position sizing, PaperBroker, journal)
  -> risk (config/risk.yaml rules, PASS/REDUCE/REJECT engine, kill switches)
  -> strategies (structured StrategySpec, versioned)
  -> backtesting (deterministic simulation, lookahead-protected)
  -> alerts (deterministic condition checking, cooldown)
  -> Phase 10 events + contextual Composer objects over the Living Core
```

Market data, portfolio analytics, trading analysis, and backtesting are
tools the central Brain composes through `Phase10Engine` — the desktop
shell gains no permanent trading-terminal surface. All Phase 10
orchestration is deterministic (no paid model call), routes through the
existing Permission Engine and evidence collector, and terminates at a
local, clearly-labeled `PaperBroker` — no live order execution path
exists anywhere in this codebase. See `docs/FINANCE_ARCHITECTURE.md`,
`docs/MARKET_DATA_POLICY.md`, `docs/TRADING_RISK_POLICY.md`,
`docs/PAPER_TRADING.md`, `docs/BACKTESTING.md`, and
`docs/FINANCIAL_DATA_MODEL.md`.

The market-data provider defaults to `local-fixture` (deterministic,
offline, always labeled `mock`), matching the Phase 7/8 integration
honesty pattern; a real live-data provider entry exists in
`config/market_data.yaml` but has no working adapter or credentials
configured in this repository.

## Phase 11 Personal Operating System and Chief-of-Staff Layer

```text
Task Runtime
  -> Phase11Engine (mirrors BusinessEngine/Phase8Engine/Phase9Engine/Phase10Engine)
  -> personal (PersonalProfile, preferences, commitments, context boundary)
  -> goals (structured Goal/Milestone, deterministic planning, evidence-based progress)
  -> habits (explicit check-ins, pattern analysis, evidence-gated insight, respectful interventions)
  -> routines (structured steps through existing permission-gated tools, adaptive on repeated failure)
  -> productivity (focus sessions, work patterns, workload, energy patterns)
  -> chief_of_staff (priority engine, risk/opportunity detection, one strong recommendation)
  -> proactive (importance/actionability/timing/duplicate gate before any interruption)
  -> notifications (priority, batching, quiet hours, preferences)
  -> daily_review (morning briefing, evening/weekly/monthly review from real recorded events)
  -> Phase 11 events + contextual Composer objects over the Living Core
```

Personal life management and Chief-of-Staff orchestration are tools the
central Brain composes through `Phase11Engine` — VYOM gains no permanent
habit-tracker dashboard or second UI surface. All Phase 11 orchestration
is deterministic (no paid model call), reuses the existing Automation
Runtime for scheduling rather than a second scheduler, and consumes the
existing Permission Engine, Risk Engine, and CRM/task systems rather than
bypassing them. See `docs/PERSONAL_OS.md`, `docs/HABIT_ARCHITECTURE.md`,
`docs/GOALS_AND_ROUTINES.md`, `docs/CHIEF_OF_STAFF.md`,
`docs/PROACTIVE_INTELLIGENCE.md`, `docs/NOTIFICATION_POLICY.md`, and
`docs/DAILY_REVIEW_SYSTEM.md`.

## Local prototype lifecycle

The Brain listens on `127.0.0.1:7788` by default. The desktop connects to `/ws/events` and creates tasks through `/api/tasks`. Cloud credentials are process environment variables read only by the Brain. A limited `local-rules` provider supports the Phase 4 demonstration commands without implying general AI capability.

Incomplete tasks are persisted. On service restart, queued and in-flight non-approval tasks are safely re-queued. Approval-paused, explicitly paused, cancelled, completed, and failed tasks are not silently resumed.

## Remaining native lifecycle boundary

The Brain still runs as a separately started local service rather than a packaged Tauri sidecar. Phase 7 includes email/calendar/agency contracts and local operating workflows, but real Google OAuth transport remains unconfigured. Phase 8 adds research/browser/discovery/booking/artifact/delivery capabilities behind the same boundary; live web search, real booking providers, and real client-delivery transports remain unconfigured. Phase 9 adds native desktop/device control (apps, windows, clipboard, notifications, screen understanding, bounded input fallback, device-node foundation); production deployment tooling and a real remote device transport remain absent. Phase 10 adds market data, portfolio analytics, trading research, backtesting, and paper trading behind the same boundary; a real live market-data feed and any real brokerage integration remain unconfigured, and no real-money execution path exists. Phase 11 adds goals, habits, routines, focus sessions, Chief-of-Staff prioritization, proactive suggestions, notification policy, and daily/weekly/monthly reviews; there is still no continuous surveillance of any kind (microphone/webcam/screen/keylogging), and no permanent personal-data dashboard was introduced.

## Phase 13 production-hardening layer

```text
Tauri desktop (native shell)
  -> ProductionMiddleware (request IDs, rate limits, size limits)
  -> local Brain API
  -> startup checks (config/db/migrations/secrets/dirs) -> readiness
  -> Task Runtime (+ Phase13Engine diagnostics/observability intents)
  -> SecretStore (OS vault / env) behind CredentialManager refs
  -> structured logs / metrics / tracing / cost tracking (redacted)
  -> VYOM Doctor + Security Audit + onboarding/setup services
```

New Brain packages: `security/` (secret store, credentials,
authentication, sessions, authorization, rate limits, request
validation, security events, redaction), `observability/`, 
`diagnostics/`, `setup/`, `production/`, `migrations/`, `phase13/`.
See SECURITY_ARCHITECTURE, OBSERVABILITY, PRODUCTION_RUNTIME,
ONBOARDING, and RELEASE_ENGINEERING for the layer contracts.

## Phase 14 adaptive layer

```text
Task Runtime --(events)--> AdaptiveLearningBridge
  -> Experience records (SQLite, migration v2) with fingerprints,
     failure signatures, conditions, verification
  -> StrategyEngine (context-aware, decayed, sample-gated)
  -> AdaptivePolicyEngine (mutable preferences vs protected boundaries)
  -> AdaptiveContextService (compact planner context, continuity)
```

One compact package (`app/adaptive/`), no new services or databases;
see docs/ADAPTIVE_INTELLIGENCE.md.

## Phase 13.5 external capability intake

```text
research/inspect -> ExternalCapabilityIntake (license/security/sandbox/benchmark)
  -> EXISTING Capability Registry (external metadata + intake state)
  -> CapabilityBackendRouter (preferred backend + health + fallback)
     web.extract:  Defuddle -> Playwright
     code.structure: codebase-memory MCP -> filesystem/search
  -> Composio (optional transport behind every VYOM boundary)
```

See docs/EXTERNAL_CAPABILITIES.md. No new registries, databases, or
services; VYOM Core boots with every external capability disabled.

## Phase 15 structured intelligence

```text
Cognitive namespaces (coding/research/agency/web/media/finance/personal/
people/projects/system/preferences) -> EXISTING typed memory store
ResolutionChain: memory -> experience -> knowledge -> skill -> tool ->
                 external research (never auto-run)
SafeSelfImprovement: observe -> hypothesize -> isolated git branch ->
                 modify -> test -> benchmark -> verifier -> promote/rollback
                 (protected paths blocked: security/permissions/secrets/
                 auth/risk limits)
UniversalWorkbench: ONE surface (browser/coding/image/audio/video/
                 documents/presentations/spreadsheets/pdf/convert/desktop)
                 reusing existing components; honest availability;
                 every execution feeds Phase 14 Experience learning
```

Persistent intelligence lives ONLY in structured stores — never
thousands of .md/.txt files. Applications open only with an explicit
task reason (live-app tests require VYOM_LIVE_APP_TESTS=1).

## Phase 16 cognitive runtime integration

```text
TaskRuntime.run -> CognitiveRuntime.prepare (LIVE, every task)
  Memory -> Experience -> Knowledge -> Skill -> Tool -> research marker
  -> task.metadata["cognitive"] + operational events
LearnedRouter -> ModelRouter.route (evidence bias, router authoritative)
             -> preferred_tool (per-condition, min 2 samples)
MissionLoop -> resolve -> plan -> execute -> verify -> bounded retry
             -> checkpoint (existing store) -> learn -> report
Workbench + media.py -> ffmpeg 9.0 (audio/video, ffprobe-verified)
                     -> PyMuPDF (pdf, reopen-verified)
```

See docs/COGNITIVE_RUNTIME.md. No new databases, services, or agents.

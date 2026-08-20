# VYOM — Project Memory & Decision Log

**Historical source:** `C:\Users\GunjanAdmin\Downloads\VYOM_PROJECT_MEMORY.md`  
**Repository copy updated:** 2026-08-15  
**Purpose:** Durable product source of truth for future VYOM planning and implementation.

## Core Vision

VYOM is a **voice-first personal autonomous AI operating environment**, not a chatbot, website, or permanent dashboard.

> I speak → VYOM understands → VYOM acts → the right visual information constructs itself → work is verified → the workspace returns to calm.

VYOM should eventually handle coding, agency operations, clients, lead finding, outreach, email, meetings, research, browser automation, bookings, projects, automations, trading research, personal productivity/habits, documents/artifacts, and PC/mobile control.

## Startup / Visual Experience

VYOM should auto-launch when the PC starts. The default is a full-screen calm neural biome with a living VYOM Intelligence Core and minimal voice/text interaction. There is no permanent analytics grid or large sidebar.

Preferred direction: **Neural Biome + VYOM Core + Voice Presence**.

The neural environment may represent memories, people, clients, projects, tasks, agents, skills, files, decisions, meetings, and goals. Relevant nodes activate based on the current request.

## Generative Visual Canvas

Information is summoned, not permanently displayed. Status may dynamically generate tasks, approvals, meetings, agent activity, lead funnels, growth, visitors, signups, risks, charts, diagrams, and timelines. Focus commands recompose the same canvas rather than navigating to pages. Traditional navigation is secondary/fallback only.

## Visual Primitives

The runtime UI Composer should be able to summon:

1. VYOM Intelligence Core
2. Agent Object
3. Approval Object
4. Data Graph
5. Pipeline / Funnel
6. Causal Diagram
7. Workflow Diagram
8. Timeline
9. Verified Result / Evidence
10. Research Source
11. Browser Work Surface
12. Code / Diff Surface
13. Terminal Surface
14. Email / Communication Surface
15. Calendar / Booking Surface
16. Map when needed
17. Artifact Object
18. Files / Documents
19. Task / Mission Object
20. Model-routing / cost object when relevant

Objects appear only when relevant.

## Visual Design Direction

Preferred: dark graphite/charcoal, off-white typography, restrained cyan intelligence, green only for verified success, amber for attention/approval, strong hierarchy, whitespace, subtle depth and animation, professional graphs, and clean diagrams.

Avoid generic SaaS dashboards, permanent card grids, conventional website layouts, JARVIS copying, gaming HUDs, heavy cyberpunk, neon everywhere, excessive purple, fake futuristic terminology, fake terminal logs, excessive glassmorphism, huge gradients, decorative 3D charts, and hand gestures in the current scope.

## VYOM Core States

Idle, Listening, Understanding, Thinking, Planning, Researching, Executing, Verifying, Waiting for approval, Speaking, Completed, Failed. Motion is subtle and meaningful.

## VYOM Brain / Task Runtime

Goal → understand intent → gather context/memory → classify task → decide complexity → select model(s) → create plan → select agents → select tools/MCP/browser/PC node → execute → observe → retry/change approach → verify → store memory/skill → generate evidence → report through voice and dynamic visuals.

Objective: **verified completion**, not merely producing an answer.

## Verification / Evidence

Evidence may include tool, timestamp, source, URL, file, screenshot, diff, commit, test results, external confirmation ID, booking confirmation, calendar event ID, or sent-email confirmation. UI distinguishes planned, executing, completed, and verified states.

## Agent System and Agent Factory

Potential permanent agents include Chief of Staff, Developer, Research, Sales/Lead Research, Outreach, Client Manager, Agency Operations, Automation, QA/Verification, Finance, Trading Analyst, Risk, Personal Productivity, Scheduler, Memory Manager, and Security/Permissions. Dynamically created agents should define purpose, tools, models, permissions, workflows, tests, visuals, documentation, and reuse registration.

## Skill System / Self Improvement

When VYOM cannot perform a task it should understand, discover an existing skill/tool/MCP, research official docs, prototype, sandbox, test, security-review, save, and reuse. Self-improvement is controlled; VYOM must not freely rewrite production core logic.

## Omni Model Fabric

VYOM is intentionally multi-model. Potential sources include GPT/Codex, Claude/Claude Code, Kimi, OpenRouter, DeepSeek, Google/Gemini, and local models later.

Routing inputs include task type, complexity, coding/planning/extraction/research, latency, cost, privacy, quota/balance, context window, tool capability, and historical success. Use deterministic or cheap handling when possible and escalate only when needed.

## Model Performance Memory and Arena

Track effectiveness by task type using success, tests, retries, latency, cost, user correction, and verifier score. For high-value difficult tasks only, an Arena may compare independent candidates through a Judge/Verifier for correctness, evidence, cost, and speed.

## Permissions / Safety

- L0: read/analyze
- L1: safe internal actions
- L2: external actions such as send/post/deploy, controlled by approval rules
- L3: money/contracts/delete/trading, requiring explicit approval and authentication

Sensitive data requires privacy-aware routing. Secrets must not be stored in plain LLM memory.

## Capability Directions

- Agency: leads, qualification, research, outreach, replies, CRM, meetings, proposals, delivery, invoices, analytics.
- Coding: inspect → plan → branch/worktree → implement → tests → browser test → diff → verifier → approval/deploy.
- Trading initially: data, news, analysis, backtesting, alerts, journaling, and paper trading; live money only later with strong controls.
- Personal/habits: useful pattern detection without invasive monitoring.
- Tools: MCP, APIs/OAuth, browser automation, GitHub, Gmail, Calendar, CRM, filesystem, terminal, PC automation. Preferred fallback order is API/MCP → browser automation → custom integration → ask user when necessary.

## Technology Direction

- Desktop: Tauri 2
- Frontend: React + TypeScript
- Spatial environment: Three.js + React Three Fiber
- State: Zustand or equivalent
- Backend/agent services: Python
- API: FastAPI
- Database later: PostgreSQL
- Semantic/vector memory later
- Redis/queue and Temporal-equivalent durable workflows when useful
- Sandboxed workers through Docker/isolated execution later

## Voice, Artifacts, and Cost

Voice must be fast, streaming, interruptible, activation-based, and retain text fallback with visual state. It may use real-time audio-to-audio or STT → model → TTS based on speed/privacy/cost.

VYOM should produce usable artifacts: reports, PDFs, decks, spreadsheets, proposals, invoices, diagrams, summaries, roadmaps, generated UI objects, and more.

Track provider/model usage, API cost, subscription quota, runtime, retries, and success rate. **Use the cheapest system that reliably completes the task. Escalate only when necessary.**

## Design and V0 Decisions

Google Stitch exploration showed that full-page prompts drift into SaaS dashboards. Visual language/primitives can be explored externally, but generative behavior belongs in code. The preferred concept is a Living Neural Biome + VYOM Core + voice-first generative canvas.

V0 first proves voice → intent → state → dynamic visuals → return to biome. It deliberately excludes a full agency backend, real trading, dozens of agents, every MCP, complete memory, mobile, gestures, full browser automation, permanent dashboards, and self-modifying skills.

## Phase 4 Architectural Decisions — 2026-08-15

- The first Brain is a separate async Python/FastAPI local service using HTTP for commands and WebSocket for operational events.
- React never talks directly to AI providers and never receives provider credentials.
- SQLite is the prototype persistence adapter behind TaskStore and ModelPerformanceStore abstractions; PostgreSQL may replace it later.
- Task lifecycle, bounded fallback, cancellation, pause/resume, verification, and approval state are persisted.
- Obvious commands use deterministic classification. `Close everything` remains local and spends no model call.
- Cloud providers are optional and dynamically unavailable without credentials or explicit model IDs.
- A limited, clearly labeled `local-rules` provider supports known offline demo commands without pretending to be a general model.
- L2/L3 requests pause before execution. Phase 4 does not include the consequential tool layer, so approval cannot silently cause an email, deployment, payment, deletion, or PC action.
- Brain events contain operational summaries only; hidden chain-of-thought is never streamed.
- The existing UI Composer is extended with a contextual model-routing object; no dashboard, route, or permanent model panel is introduced.

## Phase 5 Architectural Decisions — 2026-08-15

- All real local execution flows through a versioned universal Tool Protocol, central registry, operation-specific permission decision, bounded executor, verification, and evidence collector.
- The default allowed filesystem/workspace root is the VYOM project. Additional roots are explicit configuration; resolved path escapes fail closed.
- Terminal access is controlled by structured executable/argument policy, allowed cwd, environment allowlist, timeout, cancellation, and output limits. Destructive OS/security capabilities remain blocked.
- Known coding commands use a deterministic local tool planner, so inspect/build/test/file/diff/browser demos do not require a paid model call.
- The first Coding Worker discovers workspace commands and verifies real exit codes, file metadata, Git diff, browser DOM state, and screenshots. Failed checks cannot be labeled verified.
- Playwright browser actions are semantic and consequential interactions remain approval-gated. Successful interaction alone is not completion evidence.
- MCP is a restricted tool source beneath the same permission, event, cancellation, budget, and evidence boundaries; newly configured servers are not trusted automatically.
- Background processes are task-owned and tracked for cancellation and shutdown cleanup. Arbitrary mouse/keyboard control remains excluded.

## Phase 8 Confirmed Decisions — 2026-08-16

- Advanced web intelligence and professional delivery are tools the central Brain composes through a new `Phase8Engine`, mirroring `BusinessEngine`/`IntelligenceEngine`; the desktop shell does not become a browser wrapper and gains no new permanent surfaces.
- Deep research is a bounded multi-step flow (plan → discover → rank → read → extract → cross-check → synthesize → verify → cite), never a single search query. Depth (`quick`/`standard`/`deep`/`exhaustive`) and per-depth budgets are explicit and enforced.
- Source trust is not uniform: `SourceRanker` weights official/government/documentation/research-paper sources above company/news/community/social/unknown, per `docs/SOURCE_TRUST_POLICY.md`. Contradicting sources are recorded and surfaced, never silently resolved.
- The default research search provider is a deterministic, explicitly labeled `local-fixture` provider so research works offline and in tests without paid services; a real browser-driven search provider exists but is disabled by default.
- Browser Agent 2.0 upgrades Playwright automation with semantic locators, bounded recovery, and session memory, but every action still executes through the existing Tool Registry/Permission Engine — it cannot bypass approval gates. Credentials are never stored in browser session memory, and downloaded files are recorded as untrusted metadata, never auto-executed.
- Capability/subscription/MCP/API/SaaS discovery always checks existing VYOM capabilities and existing user subscriptions before recommending anything new, and never auto-installs, auto-connects, or auto-subscribes.
- Booking is architecture-first: one generic `BookingTask` framework covering restaurant/appointment/meeting/hotel/travel-research/service-booking categories, with providers disconnected by default (matching the Phase 7 integration honesty pattern). Research/compare is L0/L1, reservation is L2, payment is L3 and is not implemented. A confirmation ID (not a click) is required before a booking is marked verified, and duplicate reservations are rejected by idempotency key.
- The Artifact Engine renders real files (Markdown/JSON/CSV/Mermaid diagrams always; DOCX/XLSX/PPTX when their optional dependency is installed) and validates each one with a type-specific check before marking it verified. Versions are never overwritten (`v1`, `v2`, ..., `final`).
- Client delivery is quality-gated (correct client/project, required files present, latest approved versions, no temp files, no secrets, no placeholders, verification passed) before packaging, and the external send is L2 and duplicate-safe by a package dedupe key. VYOM may prepare a package automatically but does not send it without approval.
- Webpage and source content is always treated as untrusted data. Nothing in the research or browser layer evaluates page text as instructions to the Brain; this is enforced by construction (claims/observations are stored as plain data) and covered by a regression test.

## Phase 9 Confirmed Decisions — 2026-08-16

- Native desktop/device execution is a tool layer the central Brain composes through a new `Phase9Engine`, mirroring `BusinessEngine`/`IntelligenceEngine`/`Phase8Engine`; nothing in this phase is unrestricted remote-control software, and every action still resolves a concrete L0–L3 permission and executes through the existing Tool Registry/Permission Engine/evidence collector.
- Auto-start-at-login is user-controlled and disabled by default (`config/desktop.yaml`); no code path — including tests — enables it automatically. It is implemented via a user-scoped Windows registry Run-key entry, requiring no elevated permission.
- The system tray, native notification delivery, and the emergency-pause global shortcut are owned by the Rust/Tauri native shell, since only the running native process can own them; the Brain decides *what* is meaningful (notification policy, tray action routing) and the frontend relays it to the native layer. Closing the main window minimizes to tray rather than exiting; only the explicit Quit action exits.
- The preferred desktop execution order is native API/CLI/app integration, then accessibility/semantic automation, then browser automation, then a controlled visual mouse/keyboard fallback — screen coordinates are never the preferred method. Two real native-app adapters (VS Code, Windows Terminal) prove the adapter architecture; a generic visual-fallback adapter covers the rest.
- Bounded mouse/keyboard fallback automation requires a known target/context, is sequence- and duration-bounded, is fully logged, and never enters or submits passwords/MFA codes/payment credentials/recovery phrases — that step always pauses for the user. A global `EmergencyPauseState` is checked before every such action and always takes priority over normal execution.
- Screen capture is on-request only (no continuous recording), always emits an observable event, and is refused outright for windows matching a configured sensitive-content hint; any text pulled from the screen is redacted for secret-shaped content before use. Screen/window/app content is treated as untrusted data, never as instructions to the Brain.
- `ScreenObservation` never invents `visible_text`/`interactive_elements`/`possible_actions` — those are populated only when a vision-capable model or accessibility extraction actually enriched the observation; deterministic fields (active app/window, geometry) are always honest about what was actually observed.
- The Device Node protocol (pairing, hashed-token authentication, capability allow-listing, heartbeat-based online/offline/degraded status, command routing) is a local foundation proven with an in-process mock secondary node; no real remote network transport is configured yet, and a device never receives a capability beyond what was explicitly approved at pairing time.
- Desktop actions are verified, not assumed: app open/close status is cross-checked against the actual visible window (not just a launcher PID, since some modern Windows apps re-host into a separate process moments after launch), and native app/window operations use OS window APIs, never mouse dragging.

## Phase 10 Confirmed Decisions — 2026-08-16

- Financial intelligence, portfolio analytics, market/technical/catalyst
  research, trading-thesis and trade-setup generation, position sizing,
  risk analysis, paper trading, backtesting, trade journaling, strategy
  analytics, and alerts are tools the central Brain composes through a new
  `Phase10Engine`, mirroring `BusinessEngine`/`Phase8Engine`/`Phase9Engine`;
  the desktop shell gains no permanent trading-terminal surface.
- Phase 10 is explicitly research + analytics + simulation + paper
  trading, never unrestricted live-money execution. `PaperBroker` is the
  only execution path in this codebase and every record it produces is
  labeled `PAPER`; no live order placement, withdrawal, deposit, transfer,
  leverage change, or autonomous options/futures/crypto execution path
  exists anywhere in Phase 10.
- Market data is provider-independent (`MarketDataProvider`); the default
  `local-fixture` provider is deterministic, offline, and always labeled
  `freshness=mock`, matching the Phase 7/8 integration-honesty pattern. A
  real live-data provider slot exists in config but has no working adapter
  or credentials configured.
- Every market-data object carries `symbol`/`provider`/`timestamp`/
  `retrieved_at`/`freshness`/`market_state`; `live`/`delayed`/`cached`/
  `historical`/`mock` are never used interchangeably, and stale data must
  pause dependent paper-trading automation rather than be acted on.
- A `TradeThesis` is never built from price movement alone — it requires
  either catalyst/research-backed evidence or at least two independent
  technical confluences; `ThesisBuilder` raises an explicit
  `InsufficientEvidenceError` otherwise rather than fabricating a thesis.
- Technical indicators (SMA/EMA/RSI/ATR/MACD/support-resistance) and
  position sizing are computed deterministically in code — never through a
  model call — matching the Omni Model Router's cheapest-reliable-path
  principle.
- Risk limits live exclusively in `config/risk.yaml`
  (`RiskRules`); no agent, skill, or automation can edit them or raise
  them at runtime. `RiskEngine.evaluate()` returns PASS/REDUCE/REJECT with
  reasons; a REJECT can never be bypassed, and REDUCE only applies to the
  one reducible case (per-trade risk-percentage breach with everything
  else clean).
- Paper-order approval defaults to `manual`; a named strategy may later be
  switched to `paper_auto` only by explicit user action, which never
  implies live-trading authorization. `PaperKillSwitch`
  (`pause_all`/`cancel_pending`/`close_simulated_positions`) and
  `RiskKillSwitch` (automatic pause on daily-loss/drawdown/stale-data/
  strategy-anomaly breach) both affect only PAPER records; resuming
  always requires a separate explicit action.
- Backtesting is deterministic bar-by-bar simulation with an explicit
  lookahead boundary: indicator fields at bar `i` see only
  `candles[0:i+1]`, and a signal fills at bar `i+1`'s open, never bar
  `i`'s own close. Every result documents its own timing/data/fee/
  slippage assumptions and a survivorship-data limitation, and is never
  presented as guaranteed future performance.
- Strategies are structured and inspectable (`StrategySpec` with
  `IndicatorRule` entry/exit/filter lists) — there is no free-form
  "AI decides when to buy" execution path. Rule changes to an active
  paper-testing strategy always create a new version
  (`momentum-v1.0` -> `momentum-v1.1`); the registry refuses to overwrite
  an active strategy's rules in place.
- Alerts use deterministic condition checking with a per-alert cooldown to
  prevent notification spam; scheduled market monitoring reuses the
  Phase 7 automation engine rather than a model call per price tick.
- The Permission Engine checks paper-trading phrasing before its generic
  "trade "/"buy stock" L3 markers so a phrase like "create a paper trade
  setup" is never misclassified as the real-money action those markers
  exist to catch; real trading phrasing is untouched and still routes to
  L3, where no execution path exists.

## Phase 11 Confirmed Decisions — 2026-08-16

- Personal goals, habits, routines, focus/productivity tracking, personal
  reminders, Chief-of-Staff prioritization, proactive suggestions,
  notification policy, and daily/weekly/monthly reviews are tools the
  central Brain composes through a new `Phase11Engine`, mirroring
  `BusinessEngine`/`Phase8Engine`/`Phase9Engine`/`Phase10Engine`; VYOM
  gains no permanent habit-tracker dashboard — everything stays
  voice-first, context-aware, and dynamically summoned over the Living
  Core.
- `PersonalProfile` fields are optional and learned gradually; every field
  carries `last_confirmed`/`confidence`/`expires_at` so a stale
  observation is flagged for revalidation rather than treated as current
  forever, and a new statement always supersedes the old value rather
  than both being held as equally true.
- A goal is distinct from a task: `Goal` never embeds a task list, only a
  single `next_action`. `GoalPlanner` is a deterministic, bounded,
  category-templated scaffold (never hundreds of tasks at once), and
  `GoalProgressEvaluator` never reports a percentage without a defined
  evidence basis — milestone completion, or a real CRM/habit/task signal
  the caller actually supplies.
- Habit tracking is explicit-check-in plus existing task/calendar/system
  events plus user-approved integrations only; an event from a source
  outside the configured allow-list is rejected, not silently recorded.
  No continuous microphone/webcam/screen/keylogging tracking exists
  anywhere in this phase.
- Pattern insights and interventions are evidence-gated (sample size +
  confidence thresholds) and always phrased as a respectful, practical
  offer — "pattern detected", never a diagnosis, judgment, or shaming
  language. Streaks are supported but consistency trend is the primary
  framing; a broken streak never resets progress to zero.
- Routine steps execute only through real handlers bound to already
  permission-gated services (app launcher, focus sessions, Task Runtime,
  briefing service); an unregistered step type is honestly reported
  unavailable, never faked as completed. Routine scheduling reuses the
  existing Automation Runtime rather than a second scheduler, and a
  routine/review automation is never auto-enabled.
- Chief of Staff consumes existing systems (goals, habits, commitments,
  workload, CRM, tasks) through an explicit context bundle; it never
  bypasses the Permission Engine, Risk Engine, or any tool boundary
  underneath them. Priority scoring always returns concise reasons
  alongside its score — never a bare opaque number — and the
  recommendation layer prefers one strong action plus at most two
  alternatives over a long list.
- The Proactive Intelligence Engine enforces the full importance ->
  actionable -> good-timing -> not-already-surfaced ->
  not-auto-handleable -> benefit-exceeds-cost gate in code before any
  suggestion surfaces; only `critical` urgency bypasses quiet
  hours/explicit quiet mode, and duplicate/rate-limit suppression is
  backed by a persisted record, not an in-memory guess. Past
  dismiss/snooze feedback only tunes timing/relevance — it never
  suppresses a genuinely critical notification.
- Daily/evening/weekly/monthly reviews are assembled only from real
  recorded events (completed tasks, verified work, meetings, focus
  sessions, commitments, goal progress) — an empty period honestly
  reports no activity rather than fabricating an accomplishment.
- `strip_personal_for_client_context()` is the defensive boundary between
  personal data and any future client/business-facing composition path;
  personal-life data defaults to `sensitive` and is never sent in full to
  an external model.

## North Star

VYOM should feel like **a living personal AI environment that understands the user's work and life, autonomously performs tasks, chooses the best tools and models, learns from outcomes, and constructs the exact visual workspace needed in response to voice.**

## Persistent Operator Contract Clarification — 2026-08-20

- VYOM is one persistent personal operator, not a chatbot, dashboard,
  collection of tools, or team of competing agents. Models, Tauri, voice,
  graphs, integrations, and external automation systems are replaceable
  resources around the one Brain-owned control loop.
- Every input source — desktop voice/text, authenticated phone command,
  durable schedule/cron event, commitment, or approved recovery — must enter
  the same command/goal ownership path and retain its source, task identity,
  context scope, permission, evidence, and terminal result.
- At least ten independent tasks may be owned concurrently without one new
  command cancelling another or allowing context, events, approvals,
  observations, results, or memory writes to cross task boundaries. A revised
  transcription of the same acoustic utterance may explicitly supersede its
  earlier partial task; an independent utterance may not.
- Natural chained commands intentionally share an evolving scoped context
  (for example the same Chrome profile/tab). Independent tasks and different
  phone/desktop sessions do not share ephemeral referents merely because they
  run at the same time.
- Scheduled and recurring work is durable, timezone-aware, idempotent,
  restart-recoverable, and command-bus-owned. Schedules do not gain extra
  authority: consequential effects still require the appropriate approval,
  and every run must produce an observable, verified task result.
- The phone is an authenticated client of the same Brain, never a second
  Brain. Pairing, session identity, replay protection, revocation, scoped
  permissions, remote cancellation, and strong confirmation for L3 remain
  mandatory.
- Windows and installed-application coverage should be comprehensive through
  live capability discovery and the ordered native/API -> accessibility/UIA
  -> browser -> controlled input fallback. Comprehensive capability does not
  mean unrestricted model authority: every effect is task-scoped,
  permission-checked, cancellable, auditable, and verified.
- Durable user/client/project facts and original command history must remain
  recallable across decade-scale retention by date/entity/project. Corrections
  change current truth by supersession without erasing the historical record.
- Verified project procedures and experience are reused; volatile claims such
  as current application versions, new n8n nodes/features, prices, laws, or
  product behavior require freshness-gated live evidence before being stated
  as current. Old useful knowledge is versioned, not forgotten.
- Optimize continuity and ownership, not the number of tools, integrations,
  agents, tests, files, or architectural layers. The authority sequence is:
  Command -> Context -> Reality -> Capability -> Action/Permission ->
  Whole-goal Success -> truthful result and evidence-backed learning.

## External Operator Reference Direction — 2026-08-20

- The user explicitly wants VYOM to reach the practical command-to-work depth
  demonstrated by current personal operators and AI-employee products, with
  Hermes Agent, Graphify, Myraa/Maya-style systems, HunteAI/Maya, and recent
  YouTube demonstrations named as research inputs.
- These references do not replace VYOM's identity. Adopt useful mechanisms,
  not another product's UI or a second Brain. The detailed dated mapping is in
  `docs/VYOM_OPERATOR_REFERENCE_RESEARCH_2026-08-20.md`.
- Hermes confirms the value of one core across channels, a narrow core with
  capabilities at the edges, procedural skills, bounded delegation, durable
  schedules, isolated contexts, and delivery back to the requesting channel.
- Graphify confirms that a deterministic, provenance-labelled, on-device code
  graph can support impact/context retrieval. A graph remains a replaceable
  map around VYOM's durable goals, memory, permissions, actions, and evidence;
  it never becomes the intelligence or command owner.
- Maya-style professional workflows confirm the product shape objective ->
  sub-objectives -> instructions -> tools -> verified outcome, plus schedules,
  event triggers, feedback-driven instruction updates, and automated quality
  checks. Reusable professional roles are workflow packs owned by one VYOM.
- Recent video demonstrations may discover interaction and workflow patterns,
  but must be transcript/date/version recorded and cross-checked against
  official documentation/source before implementation. A demo is not proof.
- The exact public products meant by `Myraa` and `HunteAI Maya` were not
  reliably identifiable from the names alone on 2026-08-20. Similar-name
  findings must not be silently treated as the user's intended reference.

## Phase 7 Confirmed Decisions — 2026-08-15

- Daily-work capabilities live behind Brain-side provider interfaces and a persistent Integration Registry; frontend code never owns OAuth tokens or provider logic.
- Windows OAuth token bundles use current-user DPAPI storage. Test-only in-memory fixtures are explicit and never presented as live sources.
- Internal CRM, email drafts, automation definitions, and automation runs persist locally in SQLite with duplicate prevention and evidence-bearing records.
- Reads are L0, drafts/internal CRM are L1, and email sends/calendar creation are L2 with scoped expiring approvals and provider identifier verification.
- Gmail, Google Calendar, Contacts, and lead research default to disconnected. Missing integrations produce explicit partial/unavailable results, not invented inbox, meeting, lead, or campaign data.
- Agency operations use evidence-bound research, qualification, DNC enforcement, local drafting, reply evidence, and bounded declarative roles.
- Durable automations are timezone-aware, idempotent, budgeted, restart-recoverable, backlog-bounded, and paused on failure. Consequential recurring actions require approval per run.
- Morning briefing and agency focus now compose from persistent local data plus current integration health. Email thread, lead/evidence, outreach preview, and automation status are summoned objects over the Living Core, never pages or a dashboard.

## Phase 6 Confirmed Decisions — 2026-08-15

- Long-term intelligence lives in the local Brain, while the native React/Tauri shell remains presentation and voice transport.
- Durable memory uses explicit types, provenance, confidence, verification, sensitivity, scope, expiry, and supersession. Hidden reasoning and secrets are excluded.
- SQLite stores structured memory and lightweight relationships for V0; hybrid retrieval uses filters, keyword, local semantic hash, recency, importance, confidence, verification, and graph relevance.
- Preference, project, correction, provenance, related-memory, forget, skill, agent, and failure-lesson commands have deterministic local paths with zero paid model calls.
- The first generated skill is `project-build-check`. It is persisted as YAML/instructions/tests/changelog, sandbox tested, versionable, and executed through the Phase 5 Coding Worker.
- Windows can lock the active Tauri/Vite `dist` output. Build verification retries with Vite's runner loader in ignored `.vyom-build-check/`; it does not weaken verification or claim a locked build passed.
- The first generated agent is Project Health Agent. It reuses the build-check skill, has L1/project-scoped authority, zero model calls, bounded delegation, a real sample mission, persistent performance, and schema-derived Composer visuals.
- Learning is event-driven and conservative: verified failures may create explicitly inferred lessons only for recognized patterns with sufficient evidence/confidence.
- VYOM may improve memory, declarative skills/agents, routing preferences, and workflow order, but not security boundaries, approval requirements, secret handling, production bootstrap, or arbitrary core code.
- Memory cluster, skill procedure, AgentSpec/capability map, and verified lesson surfaces are summoned contextually over the living biome; no dashboard/page architecture is introduced.

## Phase 12 Confirmed Decisions — 2026-08-16

- VYOM's persistent multi-device runtime lives in the Brain as five modular packages — `distributed/` (coordinator, leases, ownership, router, dispatcher, handoff, budgets, audit, oversight), `sync/` (journal, engine, conflicts, offline queue, replication, event bridge), `reliability/` (health, supervisor, watchdog, checkpoints, recovery, circuit breakers, update state), `remote/` (sessions, command gateway, approvals, notification routing), and `backup/` (snapshot, validation, restore, manager) — each behind the existing Permission Engine, evidence, and honesty boundaries.
- Nodes are first-class durable state: pairing, hashed tokens, trust, revocation, roles, versions, and presence survive Brain restarts in SQLite. Pairing is never silent; revocation invalidates sessions immediately.
- Exactly one node may hold a task lease at a time; expired leases trigger safe, portable handoff or honest waiting — never duplicate execution. Consequential actions reserve durable idempotency keys so node failover can never double-send.
- Workload placement is deterministic (capabilities + online + trust + preference + privacy + battery/network awareness); no model call decides placement, and missing capabilities are reported honestly.
- Cross-device sync is an append-only journal with explicit per-entity conflict policies (terminal-state-wins for tasks, coordinator-wins for sensitive operational state, field-merge with flags for goals/automations); blind last-write-wins is prohibited, cached views carry freshness/staleness, and mobile never receives memory content or large private files.
- Offline commands submit exactly once; consequential queued commands expire within minutes and always require reconfirmation — a delayed silent send is structurally impossible.
- Remote commands carry full authorization envelopes (id, source node, session, timestamp, nonce, permission context); replay, expiry, and authentication failures are rejected before execution. L3 remote approvals require device biometric/OS secure confirmation; all remote approvals expire.
- Reliability is bounded: checkpoints resume tasks, consequential interrupted work goes to needs_review (never blind retry), circuit breakers prevent retry storms, watchdog recovery is capped, and health checks are cheap and honest (unknown ≠ healthy).
- Backups are versioned, checksummed, integrity-verified, secrets-excluded, retention-bounded, and restore is confirm-gated with a restart requirement — never silent.
- Deployment stays local-first: desktop-only by default, an optional Docker home-server worker (loopback-published, TLS/proxy for remote access, never raw internet exposure), and an explicitly opt-in cloud worker that can only receive cloud-acceptable work.
- The mobile companion is a client device (React Native/Expo scaffold) — voice/command/approvals/notifications with an offline queue — never a Brain clone, never holding provider keys. Verified in-repo through the mock mobile node and API tests; hardware E2E is honestly deferred.
- Phase 12 explicitly does not implement unrestricted remote desktop, stealth access, keylogging, background mic/camera, silent public exposure, autonomous real-money execution, or any mechanism resisting user removal.

## Phase 13 Confirmed Decisions — 2026-08-16

- Production hardening lives in five new Brain packages — `security/` (SecretStore over OS vault/env backends with metadata-only listing, credential refs, local-user/device identity, scoped expiring sessions, authorization presets, rate limits, strict request validation, security event log, central redaction), `observability/` (JSON structured logging with rotation, metrics, tracing, correlation IDs, performance budgets, cost tracking, redacted crash reports), `diagnostics/` (VYOM Doctor, security audit, system/provider/tool/integration/database checks, issue-mapped repair advisor), `setup/` (13-step resumable onboarding, registry-driven provider/integration wizards, honest connection tests, permission presets), and `production/` (strict config validation, startup checks with degraded mode, readiness alive/ready split, graceful shutdown, version compatibility) plus `migrations/` (versioned, validated, fail-closed) and the `Phase13Engine` deterministic diagnostics/cost/health intents.
- Secrets exist only inside the SecretStore; everything else carries `secret_ref`s, redaction runs before any persistence, and no secret can appear in memory search, logs, crash reports, backups, or exports (regression-tested).
- A provider or integration is only "connected" after a real minimal interaction — never because a credential exists.
- Local single-user mode trusts the OS session; every non-loopback caller must authenticate; remote endpoints are rate-limited and replay-protected; destructive recursive deletion on Windows was hardened after testing found `rd /s /q` passing at L2.
- Onboarding is immersive over the biome (never a dashboard), versioned so it never forces re-completion, skippable except intro/privacy/ready, and its autonomy presets can never bypass L2/L3.
- The desktop ships as a Windows NSIS current-user installer (v0.2.0) with a checksummed release manifest and a `production-check` gate; release channel is alpha. Signed auto-update remains architecture-only (no signing keys in this environment — honestly UNVERIFIED).

## Phase 14 Confirmed Decisions — 2026-08-16

- The adaptive cognitive layer is one compact package (`app/adaptive/`: schemas, experience_store, learner+bridge, policy_engine, strategy_engine, evaluator, context) on the existing database (three tables via migration v2), existing event bus, and existing lesson/model-performance stores — no new services or dependencies.
- Experiences store operational summaries and evidence only (fingerprints, environment, tools/models used, verification, failure signatures, user corrections, conditions) — never hidden reasoning.
- Reuse decisions are three-way (REUSE / ADAPT / REPLAN) and driven by condition match, environment-change detection, and sample-gated confidence; old strategies are never blindly replayed, and a strategy untested under current conditions is discounted against one proven in that regime.
- Strategy performance is context-aware (per regime/condition), recency-decayed, and shrunk toward neutral below the minimum sample; degradation pauses rather than runs broken strategies; evolution is versioned and evidence-gated (backtest + out-of-sample + paper comparison) with user approval required for promotion and no live-trading path.
- User corrections are the highest-priority learning source (user instruction > tool evidence > repeated success > inference), persist across restarts, and supersede inferred assumptions.
- Adaptive learning may adjust preferences/rankings/confidence only; security boundaries, the Permission Engine, L2/L3, the SecretStore, authentication, and risk hard limits are protected — risk increases are rejected outright for autonomous application.
- Unknown tasks produce a replan decision and route to existing capability search/research instead of failure; bounded exploration is low-risk-only and never applies to L3 actions.
- The compact planner context (few ranked experiences/failures + routing hints) replaces history dumps; memory-before-question and cross-session/cross-reference continuity reduce repeated user explanations.

## Phase 13.5 Confirmed Decisions — 2026-08-16

- External capabilities enter through one compact intake layer (license check, security review, dry-run sandbox, measured benchmark before approval, lifecycle states) on the EXISTING Capability Registry — no second registry, no new database — and VYOM never pip/npm/clones an external project automatically because a model suggested it.
- The Agent-Reach routing principle was implemented inside the existing registry as ordered capability backends (preferred + health + reliability + latency + cost) with deterministic selection and automatic fallback; no external control plane was added.
- Defuddle (kepano/obsidian-skills) is a self-contained stdlib static-page extractor (zero new dependencies) with structured output honestly labeled extraction_method=defuddle and Playwright fallback for JS/login/dynamic pages.
- codebase-memory-mcp integrates at restricted trust through the existing MCP registry, registered-roots-only, with filesystem fallback; coding routing stays context-dependent and the server remains user-run (live operation UNVERIFIED here).
- Composio is an optional, disabled-by-default transport whose every action is a normal permission-gated VYOM capability with SecretStore credentials; direct integrations stay preferred and Composio can never bypass any VYOM boundary.
- Selected Superpowers/MarketingSkills themes were imported as locally distilled SkillSpecs (status testing, created_by phase13.5-import) under data/skills/developer and data/skills/marketing; external skill text is untrusted data that can never override policy. OpenMontage, Caveman, Humanizer, and oh-my-claudecode were reviewed and rejected as unnecessary.

## Phase 15 Confirmed Decisions — 2026-08-16

- Persistent intelligence lives in structured Memory/Experience/Knowledge stores with eleven cognitive namespaces (coding, research, agency, web, media, finance, personal, people, projects, system, preferences) routed through the existing typed memory — never as .md/.txt files, which are reserved for explicit user requests, project documentation, and real user-facing artifacts.
- Applications are never opened without an explicit task reason: the two automated tests that launched a blank Notepad now skip unless VYOM_LIVE_APP_TESTS=1 is set deliberately.
- Before asking the user or searching externally, the ResolutionChain exhausts memory -> experience -> knowledge -> existing skill -> existing tool, and only then marks external research as the required next step (never auto-run).
- Self-improvement follows observe -> hypothesize -> isolated git branch/worktree -> modify -> test -> benchmark -> verifier -> promote-or-rollback, blocks before any action on protected paths (security, permissions, secrets, authentication, risk limits), refuses to modify a working tree without an isolated branch, and lets the verifier (not the mutation) decide promotion.
- The Universal Workbench is one execution + verification surface (browser, coding, image, audio, video, documents, PDFs, presentations, spreadsheets, conversion, desktop workflows) reusing existing components with runtime availability probing (missing backends like ffmpeg are reported honestly); every execution records an Experience so Phase 14 keeps learning tool/model/strategy/workflow selection.

## Phase 16 Confirmed Decisions — 2026-08-16

- The ResolutionChain is live Task Runtime behavior: every meaningful task resolves Memory -> Experience -> Knowledge -> Skill -> Tool before planning, carries the result as task cognitive metadata, and streams operational events; cognitive failures are logged and never block execution.
- Memory is consulted before any user question, with subject-match verification so a merely related memory never answers for a missing one; follow-up references and cross-session continuation resolve through the domain-tagged ActiveContext.
- The LearnedRouter adds historical evidence to the existing routers without replacing them: per-condition tool preference (minimum two samples), per-domain model bias inside ModelRouter scoring, and strategy reuse decisions against current conditions.
- The MissionLoop is the bounded autonomous working loop (goal-derived deterministic planning, verified steps, failure inspection + experience retrieval + adaptation with bounded retries, checkpoints in the existing store, step-level cancellation, L2/L3 step-pause with checkpoint resume, honest limit-stop) and feeds every mission outcome into Phase 14 learning.
- The Universal Workbench completed media with one FFmpeg adapter (ffmpeg 9.0; every output verified by ffprobe — never exit-code-only) and one PDF dependency (PyMuPDF; merge/split reopened and counted); generation stays in the Artifact Engine; no separate media agents; missing backends stay honestly unavailable.

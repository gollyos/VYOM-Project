# VYOM Reconstruction Report — 2026-08-20

Final reconstruction state: the native release, one Brain command bus,
decade-scale history retrieval, isolated concurrent tasks, durable cron/command
schedules, freshness gates, and authenticated remote-command routing are wired
and regression-tested. Physical microphone and physical phone acceptance are
deliberately not claimed here.

## A–AH required report

| Item | Status | Evidence / current truth |
| --- | --- | --- |
| A. Git/checkpoint | WORKING | Recovery branch `reconstruction-checkpoint-20260820`, checkpoint commit `8ab1fc88003d93a9574799e7fae9fdcd60827ac1`; implementation branch `reconstruction-p0-20260820`. User data was not reset. |
| B. repository size | WORKING | Before: 15.07 GiB / 31,881 files. After: 0.33 GiB / 15,127 files. Release executable and installer retained. |
| C. current architecture | WORKING | Voice/text/remote/schedule source -> `TaskRuntime` -> classification/cognitive resolution/planning -> permission -> registered capability/tool/domain engine -> whole-goal verifier -> durable task/memory/evidence/event result -> Living Core/TTS/requesting channel. |
| D. target architecture | PARTIAL | Preserve the same narrow Brain control waist; expand authenticated messaging/phone delivery, event triggers, tested skills/adapters, staged skill curation, and an optional provenance-labelled code graph at the edges. |
| E. authoritative owners | WORKING | Task: `runtime/task_runtime.py`; mission: `runtime/mission_loop.py`; events: `events/event_bus.py`; general planning: `runtime/general_planner.py`; tools: `tools/registry.py`; capabilities: `capabilities/registry.py`; actions: `execution/action_engine.py`; memory: `memory/store.py` + `memory/retrieval.py`; model health/routing: `models/`; schedules: `automation/scheduler.py`; permissions: `permissions/`; whole-goal verification: `runtime/verifier.py`; secrets: `security/secret_store.py`. |
| F. duplicate architecture | WORKING | No live source owner was deleted without evidence. Frontend-only semantic `close everything` was removed; it now enters the Brain and returns `clear_workspace`. New voice commands no longer reuse cancellation as a global task owner. |
| G. removed files | WORKING | Removed Cargo debug/release intermediates, reconstruction pytest temp trees/logs, unresolved `%SystemDrive%` test artifacts, nested Phase 5 test DB/audit output, and obsolete test-note files. See `LEGACY_CLEANUP_REPORT.md`. Production DB, backups, evidence logs, source, `vyom.exe`, PDB, and NSIS installer remain. |
| H. P0 bugs from traces | WORKING | Independent utterances cancelled prior tasks; stale terminal events could speak; STOP/noise ownership was too broad; frontend close bypassed Brain; loose website phrase extraction produced `kholo`; stale browser/task state could win; historical filters were applied after a newest-500 limit. |
| I. P0 root causes | WORKING | Acoustic revision and independent command shared one cancellation path; TTS lacked terminal event identity; frontend owned a semantic success; noun extraction accepted verbs as hosts; asynchronous UI accepted late owners; memory retrieval limited before filtering. |
| J. files changed | WORKING | Brain runtime/memory/automation/remote/schema/verification modules; frontend voice/runtime/types/experience modules; focused tests; product memory, cleanup, reference research, and this report. Exact names are available through `git diff --name-status`. |
| K. voice ownership | WORKING | Voice callback now carries `supersedesPrevious`; only a later revision of the same acoustic utterance can cancel its earlier task. Independent utterances get unique task IDs and coexist. |
| L. terminal/TTS | WORKING | TTS is keyed to terminal task event identity; superseded/stale terminal events cannot speak or steal the foreground. Background task completion uses a native notification. |
| M. STOP | WORKING | Narrow 220 ms same-utterance debounce, canonical cancel/emergency paths, noise rejection, and voice-contract regression coverage. Physical mic acceptance remains separate. |
| N. unsolicited provenance | WORKING | Task schema and metadata retain `source`, `context_id`, and `correlation_id`; remote and schedule sources create ordinary Task Runtime tasks with their provenance. |
| O. browser continuity | WORKING | Existing-browser/profile/window/tab ownership, focus, intended-window verification, and page-operator flows are regression-covered. Unsupported/live-site edge cases remain bounded and honest. |
| P. ActiveContext | WORKING | Context is keyed per desktop/remote/schedule session; referents such as “open it” resolve only inside the owning context. Remote and desktop ephemeral observations do not mix. |
| Q. WorldState | WORKING | Desktop/screen/browser tools re-observe current state and verify postconditions; cached state is not accepted as physical success. Arbitrary third-party app coverage is not universal yet. |
| R. memory/restart/correction | WORKING | SQL filters execute before limit; date/entity/client/project/source/history queries include original durable tasks; superseded facts remain historical while current retrieval excludes them by default; secrets are redacted. |
| S. whole-goal verifier | WORKING | Schedule creation has `automation_scheduled` verification with persisted read-back/ID/next-run evidence; domain verifiers feed one terminal task result. |
| T. async responsiveness | WORKING | Full suite covers async task/voice/browser behavior; desktop shell measured responsive in 0.09–0.30 s. Brain work remains out of the frontend event loop. |
| U. model calls/cost | WORKING | Date/history recall, schedule parsing, close-workspace, STOP, runtime introspection, and other deterministic routes use zero model calls. Freshness-requiring claims are routed to live evidence instead of stale model memory. |
| V. provider/circuit breaker | PARTIAL | Shared provider health/circuit behavior is wired and tested. Live cloud/provider behavior depends on credentials/network and was not re-proven in this pass. |
| W. PowerShell audit | WORKING | Production terminal execution remains registered, allow-root/policy bounded, cancellation-aware, and evidence-producing. Reconstruction destructive operations used exact resolved workspace paths only. |
| X. mock leakage | WORKING | Fixture providers stay labelled mock/disconnected; no mock result is presented as a live email, booking, market, phone, or physical desktop success. |
| Y. secret handling | WORKING | SecretStore/redaction boundary remains authoritative; history responses redact secret-like content; credentials are not written into this report or memory. |
| Z. project/mission/output/experience/skill | PARTIAL | Persistent projects/tasks, mission packs, outputs/artifacts, experience learning, SkillSpecs/tests/promotion/rollback are wired. A Hermes-style complete skill curator and broad real-world workflow pack acceptance remain expansion work. |
| AA. scheduler/commitment | WORKING | Durable SQLite schedule definitions/runs; interval, natural one-shot/weekday/daily, Hinglish `har din`, and standard five-field cron; timezone-aware next run; restart recovery and idempotency; every scheduled command re-enters Task Runtime. Consequential approval pauses safely. |
| AB. research/coding/connectors/artifacts | PARTIAL | Research, coding, browser, artifacts, delivery, CRM, and capability discovery are wired; artifacts lazy-load optional Office/UIA libraries. Live third-party connectors and universal installed-app support depend on configuration/adapters. |
| AC. targeted tests | WORKING | Continuity/voice 147 passed; isolation/distributed/voice 175 passed; cron/business/distributed/voice 222 passed; operator/natural schedule 225 passed; post-optimization artifacts/desktop 96 passed, 2 skipped. |
| AD. full suite | WORKING | Final Brain suite: 665 passed, 2 skipped, 3 warnings, 0 failures in 137.43 s. Warnings: one Starlette/httpx deprecation and two known aiosqlite test teardown thread warnings. |
| AE. frontend/Rust/Tauri build | WORKING | `npm run build` passed; `npm run desktop:build` completed Rust optimized release and NSIS bundle. Earlier Rust tests: 3 passed. |
| AF. release identity | WORKING | Executable: `C:\VYOM Project\src-tauri\target\release\vyom.exe` (11.79 MiB). Installer: `C:\VYOM Project\src-tauri\target\release\bundle\nsis\VYOM_0.2.0_x64-setup.exe` (3.01 MiB). |
| AG. active Brain identity | WORKING | Current persistent PID 8228: `C:\Users\GunjanAdmin\AppData\Local\Programs\Python\Python312\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 7788`; `/health` ok and `/readyz` ready with no reasons. Retained release executable stayed alive in the post-cleanup five-second launch probe. |
| AH. remaining limitations | PARTIAL | Physical microphone session not executed; physical phone/network E2E not executed; no public remote exposure; arbitrary Windows/app coverage cannot be guaranteed without an adapter/observable UI; a consequential scheduled run pauses for approval and may need resume; first Brain boot measured ~24 s although the desktop shell responds in <0.3 s and subsequent launches reuse the persistent Brain; installer portability beyond this source/Python-equipped PC is not proven. |

## Concurrency, memory, freshness, and scheduling changes

- Task create payloads carry context/source/correlation identity; frontend
  foreground ownership no longer means global cancellation.
- Default distributed concurrency is ten and independent completions cannot
  overwrite the newest foreground task.
- Historical task/memory search supports date ranges, entities, clients,
  projects, sources, superseded facts, and original user requests without
  scanning only the newest records.
- Queries such as “what did I tell you on 20-08-2016 about client X?” take a
  deterministic history route rather than being mistaken for arithmetic.
- Current-product questions such as new n8n nodes/features are freshness gated;
  generic requests such as “create new file” do not trigger web research.
- Schedules accept standard cron and bounded natural forms, persist read-back
  evidence, and execute their embedded command through the same permissions and
  verifier as a direct command.

## Startup optimization

Office artifact libraries and `pywinauto` now load on first use instead of
Brain import. Warm import profiling improved from 7.60 s to 3.00 s without
removing those capabilities. The actual Windows first-boot Brain listener still
measured about 24 s; the native shell itself became responsive in 0.09–0.30 s,
and the detached Brain remains alive for warm reopen.

## External operator research

The dated mapping for Hermes, Graphify, Maya-style professional work, and the
YouTube research/verification protocol is recorded in
`docs/VYOM_OPERATOR_REFERENCE_RESEARCH_2026-08-20.md`. The exact products meant
by the names `Myraa` and `HunteAI Maya` remain unverified rather than silently
matched to similarly named products.


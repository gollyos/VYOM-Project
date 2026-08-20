# VYOM Reality Audit — 2026-08-19

**[UPDATE — P0 targeted fix pass, same day, later]** See the new section at the very end of this document: "P0 Targeted Fix Verification." It covers the 3 P0s fixed against your latest physical-mic session, exact file:line diffs, regression test results, and the live A–F command-bus test results. Status: **READY_FOR_USER_MIC_RETEST**, not complete.


Scope: does the **current production code path**, not the design intent, satisfy the invariants VYOM was built for. Method: 8 parallel code-forensics passes (file:line evidence, no trust in comments/docstrings/status docs) + live dynamic testing against the actual running Brain (`POST /api/tasks` on `127.0.0.1:7788`, the same command bus text and voice both use) + a read-only query of the real production memory DB (425 rows, `services/brain/data/vyom-brain.db`).

**One correction up front:** during testing I initially flagged a "mojibake-corrupted" business-name memory record. That was **my own transcription error** (hand-copying garbled Windows-console output), not a real bug — re-fetched directly, the record is clean, correct Devanagari. It's dropped from the findings below; flagging it here only so it isn't mistaken for a suppressed finding.

---

## Executive summary

The picture is more nuanced than either "still broken" or "fixed." Real, substantive engineering has gone into exactly the failure classes you listed — not superficial patches, but structural fixes with unit tests written against the literal historical bug phrases ("Stop. Stop. Stop.", "Open the Chrome browser and search Luxora Designs."). Several P0 items are genuinely **WORKING** now. But the fixes are uneven: some are structurally solid, some are safety-nets that catch the symptom without fixing the root cause, and a few high-value subsystems (self-improvement, correction→future-behavior, generic skill promotion) are fully built, well-designed, and **never called by anything** — dead code with no wiring, not missing code.

The single most important finding: **VYOM now fails honestly far more often than it used to fail silently.** The Chrome+search compound goal, tested live, no longer reports false success — it reports `status: failed` with an exact reason. That is real progress on the core law (tool success ≠ goal success). But "fails honestly" is not the same as "succeeds" — the second half of that same compound goal still never gets executed.

---

## Final status matrix

| Subsystem | Intended | Exists? | Wired into production path? | Real test performed | Status | Exact issue |
|---|---|---|---|---|---|---|
| Voice utterance ownership | 1 utterance → 1 canonical command | Yes — `Utterance{id,revision,isFinal}` state machine, settle timer, dedupe window | Yes, single funnel confirmed by grep | Code trace only (no mic) | **WORKING** | Minor: `activeTaskRef` briefly null between cancel and new-create; a stale event in that window isn't filtered (`use-vyom-runtime.ts:184-188`) |
| STOP / kernel interrupt (backend) | Bypasses LLM/planner/tools entirely | `is_interrupt_command()` runs as the literal first statement in `create_task()` | Yes | **Live**: `POST /api/tasks {"Stop. Stop. Stop."}` → `completed` in 22ms, `total_tokens:0`, `metadata.kernel_interrupt:true`, zero filesystem access | **WORKING** | None found on backend |
| STOP / kernel interrupt (voice→backend) | Same, for spoken stop | Backend path above is real | **No** — frontend has no stop/cancel fast-path | Code trace | **PARTIAL** | `src/core/vyom-state.ts` pre-router (`resolveIntent`) has entries for wake/status/etc. but none for stop/cancel/ruko/bas; spoken "stop" must survive the same 1400ms dispatch-settle timer as any other sentence before the correct backend path even runs. Typed "stop" skips this and is instant — voice specifically pays a ~1.4s+ tax |
| Exactly-once task terminalization | 1 task → 1 terminal event | `_TERMINAL_EVENTS` set, `_emit()` sole funnel, drops duplicates with a warning | Yes, unit-tested against the historical 25-38ms duplicate | Code trace | **WORKING** | None found |
| Exactly-once TTS | ≤1 final spoken response | `spokenResponseRef` guard | Yes | Code trace | **WORKING** (minor) | Guard is keyed on response *text* not `task_id` — two different tasks with byte-identical text would over-suppress the second |
| GoalFrame (compound goals, AND-postconditions) | "X and Y" requires both verified | `GoalFrame`/`derive_goal_frame()`/`GoalVerifier.verify_goal()` in `verifier.py`, wired as the single choke point in `task_runtime._finish_result()` | Yes | **Live**: "Open the Chrome browser and search Luxora Designs." → `status:"failed"`, `goal_frame:{"required":["app_launch","search_performed"],"status":"PARTIAL"}` | **PARTIAL** | Verification is real and correctly gates final status. But step *generation* for the 2nd clause only happens via `_detect_mission()`, which silently returns `[]` unless the 2nd clause hits specific trigger phrases ("search for"/"web"/"google "). Result: the goal is correctly reported as unmet, but nothing ever attempts the search. Separately, even when `_run_mission` *does* execute both steps, its result uses a `"steps"` key while the verifier reads `"observations"` — a genuinely-successful compound mission would still be misreported PARTIAL |
| Whole-goal Verifier (postconditions vs. tool-success) | Real-world checks, not "no exception thrown" | `PostconditionVerifier` (process/window/file/exit-code/CAPTCHA/search-term/tab-count/media-state checks) | Yes, combined with a weaker structural `Verifier` — goal-frame failure always wins | Live (Chrome/search case above; Calculator case below) | **WORKING** | The generic `Verifier.verify()` alone is weak ("non-empty response") — fine because it's never the final word, `GoalVerifier` is |
| ActiveContext / pronoun resolution ("usko") | Recent referent > stale memory | Real dataclass (`last_target`, `last_entity`, `last_url`, `last_app`, `last_screen`, ...) in `cognitive_runtime.py`, written every task, read every task | Yes | Code trace only | **WORKING** | None found; explicitly cited as the fix for the historical Zoho-URL bug |
| Screen-reference follow-ups ("yeh kya hai") | Fresh observation, not memory | `is_bare_demonstrative_question()` routes deterministically to `screen_observe` before any memory path | Yes | **Live**: "Screen pe abhi kya hai?" → real, current window list (`Claude, ZCode, ...`), `intent:"screen_observe"` | **WORKING** | None found |
| Capability resolver (semantic routing) | Goal → correct existing capability | `CapabilityRegistry` is real and populated | **PARTIAL** — queried for context/health only, not for dispatch | Code trace | **PARTIAL** | "Open Calculator" reaching the right tool is 100% hardcoded `TaskClassifier` regex/keyword rules, not registry discovery. The one true semantic matcher (`AgentCapabilityMatcher.suggest()`) is called only from a test, never production |
| Windows UIA / semantic PC control | Native/UIA before shell | `pywinauto`-based `NativeAccessibilityController`: real tree walk, `invoke_control`, `get_control_value` | Yes | **Live**: "Calculator kholo aur 27 guna 43 karo" → correct result (1161), evidence `"driven through Windows UI Automation, no pixels"`, keys named individually, `goal_frame:"VERIFIED_COMPLETE"` | **WORKING** | None found |
| PowerShell as PC-control fallback | Should be rare/absent | App launch is native (registry/AppPaths/AUMID/subprocess-no-shell) | Mostly | Code trace + `data/tool-audit.jsonl` (real runtime log) | **PARTIAL** | Guardrails (`command_policy.py`, blocklists) are real and mostly effective, but a live log entry from 2026-08-17 shows `powershell -NoProfile -Command "Get-Date..."` actually executing despite a native `system.clock` action existing — the escape hatch is still reachable |
| Browser: research vs. desktop separation | Two distinct browser worlds | Explicit dual-path routing, comment literally states the design law | Yes | Code trace | **WORKING** | None found |
| Browser: visible-Chrome attach | Drive the user's real window | No CDP anywhere (`connect_over_cdp`/`9222` unused). Real UIA on the actual Chrome window instead | Yes, for window/tab management | Live (Chrome launch confirmed real pid/window title) | **PARTIAL** | No code path navigates an *already-open* tab to a URL/types a search into it — only "open new profile/URL" and "close tab" are first-class |
| Browser: profile semantic matching | "Golly AI OS" → correct profile | Fuzzy matcher (`_normalise`, token-window scoring, 0.78 floor) built specifically because "Golly AiOs" was mis-transcribed "Woolly AI OS" | Yes, called deterministically before generic app_launch | Code trace | **WORKING** | Directly reverses the documented profile-routing failure |
| Browser: tab-specific targeting | Close/open one tab, not the browser | Real tab-strip filtering + re-verification after close + postcondition requiring browser-still-running | Yes | Code trace | **WORKING** | None found |
| Browser: CAPTCHA/anti-bot false-positive verification | Must not report success on a "sorry" page | `browser_verifier.py` alone has zero CAPTCHA awareness — but nothing relies on it alone; `action_engine._web_browse` hard-fails on anti-bot phrases, `verifier._check_search_performed` is a goal-level backstop matching `/sorry/`/captcha/challenge, comment quotes the original incident | Yes | Code trace | **WORKING** (via a different layer than the file the fix should logically live in) | None found |
| Memory: multi-fact field-boundary extraction | "name X and website Y" → 2 clean fields | Clause-splitting + per-clause regex | Yes | **Live DB query**: found the exact historical corruption artifact still present (`mem_99abe3...`, name field swallowed website), plus a live-reproducible gap — "X जो Y है वह है Z" phrasing matches no current pattern | **PARTIAL** | Danda/aur-splitting fixed the common case; the fix is phrasing-specific, not structural. Website values with internal spaces still truncate (`luxora design.space` → `luxora`) |
| Memory: correction/supersession mechanics | Old fact marked superseded, new one active | `manager.correct()` genuinely flips status, links `supersedes` | Yes | **Live DB query**: confirmed real supersession chains present | **WORKING** (mechanism) | Identical restatements create unlinked duplicate roots instead of being recognized (3 independent "Gunjan" rows with `supersedes=None`) |
| Memory: retrieval excludes stale values | Never answer from a superseded fact | `retrieval.py` explicitly skips `SUPERSEDED`; but a separate path (`ResolutionChain` in `resolution.py`) has **no type filter** | Partially | **Live DB query**: dozens of active `VERIFIED` episodic rows still assert "Your website is betaworks.space" hours after correction; the live "website" slot currently has **zero active records** after a manual repair script wiped the last one | **BROKEN in practice** | This is the most serious live finding: today, asking VYOM "what is my website" would plausibly retrieve a stale corrected value from old chat-log rows, or nothing at all |
| Memory: authority ordering (user correction > inference) | Explicit hierarchy | No precedence table exists anywhere; `relevance.py` only weights verification-state, not source-type | N/A | **Live DB query**: 327 active episodic rows carry `VERIFIED`/1.0 confidence while being plain LLM chat opinions, indistinguishable at schema level from a tool-confirmed fact | **NOT_IMPLEMENTED** | — |
| Memory: cross-restart persistence | Survives Brain restart | Real on-disk SQLite (WAL), commits every write | Yes | **Live DB query**: 12.6MB/425-row live file with a same-day pre-repair backup | **WORKING** | None found |
| Model routing: shared 429 circuit breaker | One 429 stops every caller | `ProviderHealth` — single instance, injected into router/task_runtime/planner, semaphore-based | Yes | Code trace; live log shows 30 consecutive clean 200s post-fix | **WORKING** | A second, unrelated `CircuitBreakerRegistry` exists but isn't wired to the LLM path — not a bug, just a red herring if someone goes looking for "the" breaker there |
| Model routing: 429 failover vs. retry-storm | Fail over, don't hammer the same provider | HTTP client raises immediately on 429, no same-target retry; planner walks distinct fallback candidates once each | Yes | Code trace | **WORKING** | No contradiction found between layers |
| Model routing: zero-cost deterministic paths | Open/close/stop/system-info/exact-memory-hit = 0 model calls | Real cascade of specialized engines before any model call | Yes | **Live**: every test I ran (`Stop.`, Calculator, screen-observe, Chrome launch) showed `total_tokens:0` | **WORKING** | None found |
| Model routing: runtime introspection ("why is this slow") | Answerable from local state, 0 calls | `GET /api/models` + `provider_health` genuinely live | Partially | Code trace | **PARTIAL** | `usage_tracker.py` (the file this was expected to live in) is write-only/dead — nothing reads `.summary()`. A separate, unrelated `CostTracker` actually backs the cost API |
| Retry-storm historical evidence | — | — | — | Grepped all 9 root log files for 429/rate-limit/retry/circuit | **UNVERIFIED** | Zero hits in current on-disk logs; the storm is referenced only in code comments as design rationale, not present in any log file available now (predates these files or was rotated out) |
| Mock/fixture isolation — Agency/CRM/Calendar/Email/Booking/Delivery | Disconnected ≠ fake data | `Disconnected*` providers wired by default for all of these | Yes | Code trace | **WORKING** | Consistently fails closed with an honest error |
| Mock/fixture isolation — Finance/market data | Disconnected ≠ fake data | `LocalFixtureMarketDataProvider` is the **only** configured provider — no real adapter exists in the repo at all, and it's the default | Yes (by default, not as an override) | Code trace matched to a real log line ("NVDA: 451.873 (local-fixture, mock)") | **MOCK_ONLY** | The specific quote-mention path does honestly label itself. But sibling paths built on the same mock quotes (`_portfolio_risk`, labeled `"Live risk read"`) disclose nothing — disclosure is a per-callsite convention, not structurally enforced |
| Secret redaction | No plaintext keys in any log sink | Real `SecretRedactingFilter` + `redact_mapping()`, fixed the original Gemini-key-in-URL incident (confirmed: live logs show `key=<redacted>`) | Mostly | Code trace + log grep | **PARTIAL** | One sink was missed: `POST /api/diagnostics/trace` writes an arbitrary caller-supplied `detail` dict straight to `vyom-trace.jsonl` with no redaction call at all. No live secret was actually found in the repo during this audit |
| Skills: procedural reuse | Strategy → skill → live capability, no self-certification | `skills/executor.py` genuinely routes through `ActionEngine` and reads real verification | Only for **one** hardcoded skill (`project-build-check`) | Code trace | **PARTIAL** | No generic strategy→skill promotion pipeline exists; `SkillBuilder` is a one-off demo disconnected from `StrategyEngine` scores |
| Experience: learn from outcomes | Past outcomes influence future routing | Real write path (already known) **and** a real read path: `ResolutionChain`, `cognitive_runtime.prepare()`, `LearnedRouter.model_bias()`, `LearnedRouter.preferred_tool()` all consume aggregated `Experience` | Yes (for routing/tool-choice) | Code trace | **WORKING** | One sub-mechanism (`StrategyEngine.decide_reuse`) is telemetry-only — surfaced as a progress message but never read by the deterministic planner |
| Correction changes future behavior | A user correction should update something durable | `AdaptiveLearner.record_user_correction()` fully built, correct priority weighting | **Zero callers anywhere in the codebase** | Code trace (grep) | **NOT_WIRED** | Fully dead code — this is exactly the "self-learning" the project was named for, unused |
| Self-improvement (isolated branch/test/promote) | Never mutate core files directly | `SafeSelfImprovement` genuinely isolates via git branch, path guards, test+benchmark gate, rollback on failure | Constructed with no working `runner=`, so every call immediately returns blocked; nothing calls `.hypothesize()`/`.execute()` anywhere | Code trace | **PARTIAL** (correctly designed, entirely unreachable) | `hypothesize()` also always returns an empty change-target list — it never names a file. The safety contract is real; the subsystem is dead |
| Research: fresh sources over stale model memory | — | `LocalFixtureSearchProvider` exists as a fallback source alongside real search | Yes, always appended | Not independently audited this pass (covered only incidentally via mock/fixture pass) | **UNVERIFIED** | Deserves its own dedicated audit pass — not covered in enough depth here to give a confident verdict |
| Coding capability (real repo changes) | Voice → real diff → tests → verify | `coding/` directory exists | — | Not audited this pass | **UNVERIFIED** | Out of scope this round |
| Artifacts (real verified files) | Deliverables are real files, verified | `artifacts/` engine exists | — | Not audited this pass | **UNVERIFIED** | Out of scope this round |
| UI/TTS: no raw internals leaking to user | Semantic, calm output only | Frontend event handling reviewed for dedupe, not for raw-JSON-leak specifically | — | Live responses I received were clean natural language ("Chrome is open.", "27 times 43 is 1161.") | **WORKING** (as observed) | Not exhaustively audited for every code path |

---

## What "PARTIAL" vs "WORKING" means concretely here

Two live tests illustrate the difference precisely:

**Calculator ("Calculator kholo aur 27 guna 43 karo")** — genuinely WORKING end to end: real UIA keypresses, correct math, display read back, `goal_frame: VERIFIED_COMPLETE`, zero model calls, closed cleanly afterward on request.

**Chrome+search ("Open the Chrome browser and search Luxora Designs")** — PARTIAL in a very specific, now well-understood way: Chrome opened for real (pid confirmed, an already-open window was correctly reused rather than duplicated), the verifier correctly recognized the search never happened and reported `status: failed` — but the planner never generated a step to attempt the search in the first place. The historical bug ("marked complete after Chrome alone") is fixed; the underlying task (actually searching) is not. This also surfaced a live memory record proving a documented related bug is real: a user's complaint about this exact scenario ("...tumne jo profile maine bola" / "you didn't use the profile I said") was once stored as a "completed" task whose result was a filesystem directory listing — i.e., the feedback-intent-misrouted-to-filesystem bug actually happened in this system's history and the artifact is still in the DB.

---

## P0 fixes (blocking — fix before anything else)

1. **Memory retrieval leaks stale/superseded facts via the episodic path.** `services/brain/app/memory/resolution.py` (`ResolutionChain`, no type filter) needs the same `SUPERSEDED`/durable-type filtering that `retrieval.py` already has. Right now dozens of live rows still assert a corrected-away website. Also: the live "website" slot has zero active records after a manual repair script — that needs an actual data fix, not just a code fix.
2. **Compound-goal plumbing key mismatch.** `services/brain/app/runtime/task_runtime.py` (`_run_mission`, ~line 1502) emits `structured_data={"steps": [...]}`; `GoalVerifier._effect_context` (`verifier.py:589`) reads `"observations"`. A compound mission that *actually completes both clauses* is still reported PARTIAL/FAILED because the evidence never reaches the checker. Rename/merge the key (compare `_run_general_mission`, which does this correctly at `task_runtime.py:1283`).
3. **`_detect_mission()` under-triggers for compound goals.** `task_runtime.py:1292-1327` only produces a real multi-step plan when the second clause hits specific trigger phrases ("search for"/"web"/"google "). "search Luxora Designs" (no "for") falls through to `intent="general"`, which isn't in `TOOL_INTENTS`, so no mission is ever built and only the first clause executes. This is the actual remaining root cause of the Chrome+search gap.
4. **Voice-specific STOP latency.** `src/core/vyom-state.ts` (`resolveIntent`) has no stop/cancel entry, so a spoken "stop" pays the full 1400ms dispatch-settle tax before reaching the (correctly instant) backend interrupt path. Add a stop/cancel keyword fast-path here, mirroring what typed input already gets for free.
5. **`AdaptiveLearner.record_user_correction()` has zero callers.** This is the literal mechanism for "a correction changes future behavior" and it's fully built, correctly designed, and never invoked. Wire it into wherever a correction is currently detected (memory `manager.correct()` path looks like the natural caller).

## P1 fixes

6. **Capability resolver isn't actually consulted for dispatch.** `TaskClassifier`'s ~700-line hardcoded regex/keyword table is doing 100% of intent routing; `CapabilityRegistry` is queried for health/context only. `AgentCapabilityMatcher.suggest()` — the one real semantic matcher — is called only from a test. Either wire it in for the long tail of goals the hardcoded classifier doesn't cover, or accept and document that "capability resolution" is currently classifier-based, not registry-based.
7. **No visible-tab navigation.** Desktop browser control can open a new profile/URL or close a tab, but nothing drives an *already-open* tab (no "isi tab me search karo"). Worth a dedicated action in `browser/browser_actions.py` / `input_control/accessibility.py` using the existing UIA address-bar control.
8. **Finance mock-data disclosure is inconsistent.** `phase10/engine.py`'s `_portfolio_risk` labels itself `"Live risk read"` while pricing off `LocalFixtureMarketDataProvider` with no freshness/mock disclosure in the user-facing text (unlike the quote-mention path, which does disclose). Either enforce disclosure structurally (wrap every price-bearing response) or add a real market-data adapter so the fixture stops being the unconditional default.
9. **Diagnostics trace endpoint bypasses redaction.** `services/brain/app/api/diagnostics_api.py:57-73` writes an arbitrary caller-supplied dict to `vyom-trace.jsonl` with no `redact_mapping()` call — the one sink the Gemini-key fix didn't reach.
10. **Self-improvement is fully dead code.** `app/main.py:1149` constructs `SafeSelfImprovement` with no working `runner=`, so `execute()` always short-circuits to blocked, and nothing calls `hypothesize()`/`execute()` anywhere. The isolation design (git branch, path guards, test+benchmark gate, rollback) is genuinely sound — it just needs a runner and at least one caller.
11. **PowerShell escape hatch still reachable.** Live `tool-audit.jsonl` shows `Get-Date` executed via PowerShell on 2026-08-17 despite a native `system.clock` action existing. Guardrails are real; tighten the specific path that let this through.

## P2 (cleanup, once P0/P1 land)

12. Memory: identical restatements create unlinked duplicate root records instead of being recognized as "already known" — minor hygiene, not correctness.
13. Frontend terminal-event dedupe uses `activeTaskRef` as its only guard, which is nulled exactly when a duplicate terminal event needs filtering; add an `event_id`-keyed dedupe (`event_id` already exists in `BrainEvent`, just unused).
14. `.gitignore` doesn't cover root-level `brain-*.log`/`brain-final.err` or `services/brain/data/logs/` (one directory deeper than the current glob) or `services/brain/data/secrets/` — matters the moment this becomes a real git repo.
15. `usage_tracker.py` is dead (write-only); either wire it into introspection or remove it in favor of the `CostTracker` that's actually serving `GET /api/observability/cost`, to avoid the next person debugging the wrong file.
16. Skills: `SkillBuilder`/`skills/executor.py` currently support exactly one hardcoded skill — fine as a proof of concept, but worth being explicit in docs that "skill promotion" isn't a general mechanism yet.

## Explicitly out of scope this pass — do not assume these are fine

Research freshness-over-staleness, coding capability (real diffs/tests), and the artifacts engine were not independently audited this round — they're marked UNVERIFIED, not WORKING, in the matrix above. A follow-up pass should cover them with the same live-testing rigor used here (a real `POST /api/tasks` call, not just a code read).

---

## Live dynamic test log (for reproducibility)

Brain started via `python -m uvicorn app.main:app --host 127.0.0.1 --port 7788` (real production entrypoint, no test flags), stopped cleanly at the end of this audit.

| # | Request (via real `/api/tasks`, same bus text and voice both use) | Result |
|---|---|---|
| 1 | `Stop.` | `completed`, 7ms, `kernel_interrupt:true`, 0 tokens |
| 2 | `Stop. Stop. Stop.` (exact historical failure phrase) | `completed`, 22ms, `kernel_interrupt:true`, 0 tokens — no filesystem access |
| 3 | `Open the Chrome browser and search Luxora Designs.` | `failed`, real Chrome pid, `goal_frame:{"required":["app_launch","search_performed"],"status":"PARTIAL"}`; surfaced a real historical memory record of the feedback-misrouted-to-filesystem-listing bug |
| 4 | `Calculator kholo aur 27 guna 43 karo.` | `completed`, real UIA keypresses, correct result 1161, `goal_frame:"VERIFIED_COMPLETE"`, 0 tokens |
| 5 | `Calculator band karo.` | `completed`, "Calculator is closed." |
| 6 | `Screen pe abhi kya hai?` | `completed`, `intent:"screen_observe"`, real live window list (not memory) |
| 7 | `GET /api/memory?limit=200` (read-only) | Surfaced the real, still-present multi-fact extraction bug artifact, active supersession chains, and 327 active `VERIFIED` episodic rows with no source-priority distinction from tool-confirmed facts |

No writes were made to production data beyond what these read/reversible test commands themselves triggered (Calculator open/close, one Chrome focus, no new memory facts deliberately injected).

---

## Addendum: the actual last real conversation (2026-08-18, from the task DB — not synthetic)

After publishing the audit above, I pulled the real `tasks` table (58 rows for 2026-08-18) to see the genuine last session, not just my own test commands. **Important transparency note:** my dynamic-test window overlapped with what looks like real, spontaneous voice usage on this same machine — port 7788 was confirmed free before I started the Brain, so every request after that hit the one instance I launched, including an organic-looking stretch of conversation between 21:29 and 21:33 that ran concurrently with the tail of my own testing. If VYOM's desktop app was open around then, it was very likely talking to my test instance rather than a separately-running one — same code, same real database, no functional difference, but worth knowing.

Two things stand out that the earlier report didn't have:

**A genuine live regression the English test didn't catch.** At 19:48:15, the real user said (Hindi): *"अभी जो मेरी Chrome की प्रोफ़ाइल ओपन है, उसमें न्यू टैब ओपन करो और YouTube सर्च करो"* ("open a new tab in my currently-open Chrome profile and search YouTube"). Result: `status: completed`, response: `"Chrome is open."` — the new-tab/search half never happened, **and** unlike my own English "Chrome and search Luxora Designs" test, this one's `goal_frame` only required `["app_launch"]` — the classifier never attached `new_tab`/`search_performed` as required postconditions for this phrasing at all, so it didn't even get the honest-failure treatment. The GoalFrame fix verified in the main report is real but narrower in live traffic than the one English phrasing I tested.

**The profile-routing fix does hold up in real use.** At 19:23:51, *"Okay. Chrome pe Woolly AI OS open karo"* → *"Chrome is open in the Business Luxora profile (Golly AiOs)."* — this is the exact historical failure phrase, and in this real session it worked, matching what the browser-architecture audit found in code.

**Rough note to end the session on.** The last ~5 minutes (21:29–21:33) show real friction: "on screen showing a profile so open the Kunal Shah profile" → `failed`, `goal_frame: {"required":["profile_open"],"status":"FAILED"}`; an unrelated "Power cell is fail again and again" got a generic troubleshooting essay instead of being treated as noise/off-topic; four consecutive user-cancelled turns including *"But maine tumhe isliye banaya ki tum ek human ki tarah think karo... bilkul human lage, bot nahi lagna chahiye"* ("I built you to think and feel human, not like a bot") and *"यह नहीं चाहिए"* ("I don't want this"); and the session's final command, **"application close kar do"** (close the application), returned `status: failed` with an **empty response** — no acknowledgement, no error message, nothing. That's the literal last thing that happened before I started auditing.

This doesn't change any status in the matrix above, but it's the most concrete evidence in this whole audit for why the project feels less reliable in daily use than the individual fixes would suggest: the fixes that exist are real, but they're narrower than the phrasing variety real speech actually produces, and a silent failure on the very last command of a session is exactly the kind of thing that erodes trust fastest.

---

# P0 Targeted Fix Verification — same day, later pass

Scope: exactly the 3 P0s requested, no P1, no new features. Source of truth: the latest real physical-mic session in the task DB (2026-08-19T09:20:31 - 09:31:23 UTC), not the prior day's session, not synthetic replay.

## First wrong decision per failure (before any edit)

1. **Unrequested app launches** - not reproduced in this session; every external action traced to an explicit preceding command. The real gap: no `provenance` field existed anywhere in the task data model, so the guarantee had nothing enforcing it structurally.
2. **Browser continuity** - `task_6d0ae0a5`, 09:20:31.616655, "Isi Chrome me new tab pe YouTube kholo." -> `goal_frame: VERIFIED_COMPLETE` while `structured_data` showed `tabs_before: 2, tabs_after: 2` (no tab created) and the `new_tab` evidence was "the active tab in the existing browser reads 'ChatGPT'" - an unrelated window's title. Repeated at 09:28:38 and 09:30:46.
3. **Memory relevance** - `task_d609b49d`, 09:21:05.959285, "Is page pe kya hai?" (a page-content read, nothing to do with identity) pulled full name/business identity into its `cognitive.hits` context via an unfiltered retrieval fallback.

## Fixes made (exact files)

**1. Action provenance gate**
- `services/brain/app/schemas/tasks.py` - added `ActionProvenance` enum: USER_COMMAND / APPROVED_SCHEDULE / APPROVED_AUTOMATION / CURRENT_GOAL_RECOVERY / SYSTEM_SAFETY_ACTION.
- `services/brain/app/runtime/task_runtime.py` - `create_task()` now stamps `task.metadata["provenance"]` (default USER_COMMAND, covering /api/tasks, /api/remote, offline-queue replay); `resume()` stamps CURRENT_GOAL_RECOVERY.
- `services/brain/app/main.py` - the routine/automation step executor (`_routine_create_task`) now explicitly passes provenance=APPROVED_AUTOMATION.
- `services/brain/app/execution/action_engine.py` - new `EXTERNAL_ACTION_INTENTS` set (app_launch, app_close, settings_open, recover_visibility, browser_tab_close/open/click, browser_profile_open, browser_first_result, browser_page_type/scroll, ui_interact, web_browse, run_command, open_local_app) and `_authorize_external_action()`, called at the single dispatch choke point in `execute()`: denies if the task has no valid provenance, and denies if the task is already CANCELLED/FAILED/COMPLETED (a terminal/superseded mission permanently loses action authority). Read-only intents (fs_read, screen_observe, system_query, browser_tab_list, browser_page_read, etc.) are untouched - idle/read-only stays free.

**2. Browser continuity - `_check_new_tab`**
- `services/brain/app/runtime/verifier.py` (`PostconditionVerifier._check_new_tab`) - a known, non-zero, unchanged tab count (tabs_before == tabs_after, both real integers) is now authoritative proof no tab was created and returns FAILED, instead of falling through to the window-title fallback. The one legitimate case preserved (and covered by an existing test): tabs_before == 0 while a browser window already existed - Chrome's tab strip genuinely not exposed yet - still uses the title fallback.

**3. Memory relevance - `ResolutionChain.resolve()`**
- `services/brain/app/memory/resolution.py` - the namespace-tag filter's fallback no longer defaults to ALL raw similarity hits. For any namespace that isn't PEOPLE/PERSONAL/AGENCY, MemoryType.PERSON and MemoryType.CLIENT records are excluded from the fallback pool. Identity/business memory is still fully stored (remember broadly) and still answers identity-relevant queries, but no longer surfaces as retrieval context for unrelated technical intents (retrieve narrowly). This is the single choke point both `cognitive_runtime.prepare()` and `answer_from_memory()` go through, so it covers both the metadata contamination and the LLM prior-knowledge injection path.

## Regression tests

`pytest tests/test_voice_control_contract.py tests/test_phase9_desktop.py tests/test_phase171_browser_reliability.py tests/test_phase16_cognitive.py tests/test_classification_permissions_events.py tests/test_phase5_tools.py`

- Before the fix: 1 failed (`test_the_window_title_is_valid_tab_evidence_when_the_strip_lags` - this is what forced the refined "before == 0" carve-out above), 207 passed.
- After the fix: 0 failed, 208 passed, 2 skipped.
- 43 errors present both before and after - all `PermissionError: [WinError 5]` on a Windows temp-dir/pytest-cache path, pre-existing and unrelated to any of these 3 changes (confirmed by identical errors in the pre-fix baseline run, in files these changes never touch).

## Live command-bus tests (A-F), against the fixed code, real production /api/tasks

**A - idle 2 minutes.** PASS. Zero new tasks created (last task timestamp unchanged across the full window) - zero external effects by definition, since nothing exists that could have caused one.

**B - "Hello VYOM."** PASS. "Hello. How can I assist you today?" - no identity dump, no tool call, provenance: USER_COMMAND.

**C - Chrome/profile/tab sequence.**
| Step | Result | Provenance |
|---|---|---|
| Chrome kholo. | VERIFIED_COMPLETE, pid confirmed | USER_COMMAND |
| Golly AI OS profile kholo. | VERIFIED_COMPLETE, "Business Luxora (Golly AiOs)" - fuzzy profile match confirmed live | USER_COMMAND |
| Isi profile me new tab pe YouTube kholo. | failed - "The new tab did not activate - the browser stayed on 'Claude'." | USER_COMMAND |
| New tab me Gmail kholo. | failed - same reason | USER_COMMAND |
| YouTube wala tab band karo, Chrome nahi. | failed - "No open tab matches 'youtube'." | USER_COMMAND |

The fix did exactly its job: previously this exact sequence would have reported VERIFIED_COMPLETE/"is open in a new tab" every time regardless of what actually happened. Now every step that didn't truly succeed says so honestly. But it surfaced a fourth, separate, real problem outside the 3 named P0s: the underlying tab-open action appears to target whatever window currently holds OS focus rather than the intended Chrome window ("stayed on 'Claude'" - a different application's window). By the end of the sequence, Chrome had no visible windows/processes at all; reopening it immediately afterward worked cleanly, and Chrome window count had already been fluctuating independently throughout the day (4 windows at 09:31, 1 by the time this test started), so this is most likely real, ongoing machine activity rather than something these 3 fixes caused - but it's not conclusively ruled out, and the underlying window-focus-targeting issue in the tab-open capability is real and worth its own investigation before the next physical-mic retest.

**D - "Calculator kholo."** PASS. total_tokens: 0, VERIFIED_COMPLETE, and - critically - cognitive.hits carried no name/business/website content this time (confirms the memory fix).

**E - "Mera naam kya hai?"** PASS. "Your name is Gunjan Shah.", total_tokens: 0.

**F - "Meri website kholo."** PARTIAL / new finding. It answered "Chrome is open at luxora-designs.test." - but this is a stale, .test-domain (placeholder/fixture-looking) value pulled from an old EPISODIC chat-log echo, not the durable profile slot (the SAME-DAY deterministic name/website lookup had correctly answered "I have not been told your website" at 01:15/01:27/01:30 earlier today - action-resolution and question-answering are reading from two different, inconsistent memory paths, and only the identity-type PERSON/CLIENT exclusion was in scope for this fix, not stale EPISODIC echoes). Worse, running this exact command live-created a corrupted memory record: "User website: kholo" - the extraction pipeline treated the command itself ("meri website kholo" = "open my website") as a factual statement and captured the trailing verb "kholo" as the website value, the same class of bug as the original field-boundary corruption, just triggered by a command instead of a compound statement. I deleted that one bad record after confirming it (mem_bdda5f00..., cleaned up via DELETE /api/memory) so it doesn't persist as real data. This is a genuine 4th finding, not one of the 3 named P0s, not fixed in this pass.

## Status

READY_FOR_USER_MIC_RETEST - not COMPLETE.

The 3 requested P0s are fixed, verified against real regression tests and the real production command bus, and the fixes are minimal and targeted (no new features, no P1 work started). Two things fall outside what was asked but were found live and should inform your retest: (1) a window-focus-targeting issue in the browser tab-open capability (Test C), and (2) write-time fact-extraction still fires on commands, not just statements, and can still corrupt a memory slot on the exact "open my website"-shaped phrasing (Test F). Neither was touched, per your instruction to fix only these 3 and not add scope.

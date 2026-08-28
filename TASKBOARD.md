# TASKBOARD — Multi-Agent Work Board

> Rules: lane lena hai to is file me edit karke claim karo. Ek lane = ek agent = ek time.
> Status: `open` / `in-progress (agent, HH:MM)` / `done (commit-hash)` / `blocked (reason)`

## Board

| # | Task | Lane | Status |
|---|---|---|---|
| 1 | LIVE E2E: "Chrome kholo + YouTube lofi play" real window me VERIFIED_COMPLETE | VERIFY | done (2dee063) |
| 2 | Desktop release build (`npm run desktop:build`) + installed app me voice auto-on check | FRONTEND + VERIFY | done (4017163) |
| 3 | Morning briefing live: real failed/paused tasks briefing me bole | BRAIN + VERIFY | in-progress (Codex/root, 11:34) |
| 4 | Paper-trade ek real setup end-to-end (data → thesis → risk PASS → paper order) | SUBSYSTEMS | in-progress (Codex/root, 13:06) |
| 5 | WS replay live test: task chalate time disconnect karke events wapas aaye | VERIFY | open |
| 6 | /api/quota budget chip real app me dikhe (15% pe amber) | FRONTEND | open |
| 7 | Meta-learning / multi-agent orchestrator ke liye live smoke test | SUBSYSTEMS | in-progress (Claude, 13:05) — orchestrator wired; sub-agent exec blocked on free-tier quota |
| 12 | Hallucination fix: non-actionable Q&A reasoning-path pe jaaye (tool-mission planner ka title/sediment leak band); degenerate-answer verifier gate | BRAIN | done (151af9d) |
| 13 | Multi-agent wiring: 10 role agents + CEO/SEO/security registry me, scoped tools, orchestrator ko command path se call | SUBSYSTEMS + BRAIN | done (pending-commit) — layer wired + 1257 tests; live exec needs 2nd model key |
| 8 | Exact owner media command routes to `play_media`, not generic Chrome launch | BRAIN | done (2dee063) |
| 9 | Isolate external-capability tests from tracked production config | BRAIN + VERIFY | done (ecf47e2) |
| 11 | Add weather/currency/crypto/trivia builtin tools (no-key free APIs) | BRAIN | done (4f6a768) |
| 14 | Native JARVIS tools (WikipediaTool, NewsTool, WhatsAppTool, System battery/volume/lock) + multilingual language mirroring | BRAIN + SUBSYSTEMS | done (4d56a62) |
| 15 | Universal 335+ Tools Catalog + JIT DynamicToolMatcher across 10 functional domains | BRAIN + SUBSYSTEMS | done (a4eb020) |
| 16 | HumanTypewriter Anti-Ban Keyboard Simulator with Gaussian timing jitter & micro-pauses | BRAIN | done (70ca35c) |
| 17 | Social Media Interceptor & Stylized Auto-Responder with Focus Mode quiet rule | BRAIN + SUBSYSTEMS | done (c3edf85) |
| 18 | Teachable MacroEngine for custom voice/event/schedule user workflows | SUBSYSTEMS | done (cd44e99) |
| 19 | Smart Professional Email Composer with customized tones and contextual drafts | SUBSYSTEMS | done (d6efb6d) |
| 20 | Phone-to-PC Remote Controller Bridge via Telegram Gateway (/status, /lock, tasks) | BRAIN | done (040e284) |
| 21 | Multilingual TranslationFormatterService for Hindi-to-English voice dictation and dispatch | BRAIN + SUBSYSTEMS | done (22fefb1) |
| 22 | 24/7 VPS HeadlessDaemon & Autonomous Cron Engine for background cloud automation | BRAIN + SUBSYSTEMS | done (ef45eca) |
| 23 | TaskClassifier Intent Rules for Translation & Remote Voice Routing | BRAIN | done (9692f8a) |
| 24 | Mobile Android Companion Remote Brain URL Support in Frontend | FRONTEND | done (95b715e) |
| 25 | Reliability & Crash Resistance: multi-model Gemini fallbacks, React error boundary, safe PCM decoding & optional chaining in WS stream | FRONTEND + BRAIN | done (0b51236) |
| 26 | JARVIS 2050: Holographic Infinite Memory, Autonomous Agency Pipeline, Cognitive Scaffolder (free-model supercharger), Dynamic Tool Synthesizer, agency+synthesize_tool intent routing | BRAIN + SUBSYSTEMS | done (9b487d5) |
| 27 | Brain Keepalive Heartbeat, Hinglish Conversational Mirroring, & STT Noise Vocabulary Expansion | BRAIN + FRONTEND | done (verified) |
| 28 | Universal Multilingual Communication (All Indian & International Languages), STT Script Regex, Multi-language Neural Edge-TTS & Fresh Desktop Setup Bundle | BRAIN + FRONTEND + VERIFY | done (verified) |
| 29 | Desktop Execution Hardening: Window Stability, Indian Female Voice (Aoede), No-Cutoff Speech Delivery & Resilient App Launch Fallbacks | BRAIN + FRONTEND + VERIFY | done (verified) |
| 30 | Brain-disconnect root cause repair: py3.11 f-string crash fix + Tauri supervisor + spawn log + frontend health re-poll + stale remote-URL clear | BRAIN + FRONTEND + VERIFY | done (this session, live: 4 restarts, boot ~4s) |
| 31 | Fast boot: MCP connect deferred post-serve (19.2s → 0s pre-serve) + boot instrumentation | BRAIN | done (this session, live measured) |
| 32 | Deterministic weather path (classifier intent + Open-Meteo + tool_evidence verification) | BRAIN | done (live E2E: Delhi 28.2°C answered) |
| 33 | Media correctness: relevance gate + active-tab preference + shorts-safe first result + autoplay recovery | BRAIN | done (live E2E: lofi VERIFIED playing) |
| 34 | Voice honesty rules + STT noise gate + Boss/SHARE-FEELINGS persona + learned-router bias no-op fix + pending-work 3-day cap | BRAIN + FRONTEND | done (1337 tests) |
| 35 | Dead-model 404 fix: gemini-2.5/2.0/1.5-flash → gemini-3.6-flash (sab general tasks fail ho rahe the) | BRAIN | done (2c3b605, live verified) |
| 36 | Volume/Brightness hardware control (deterministic intents, absolute %, WMI brightness) | BRAIN | done (2c3b605, live: 100% + 30%→70%) |
| 37 | Media intelligence: 'X ka song'→'X songs' search, audible-tab switching, keyboard-k autoplay recovery, verifier before-state fix | BRAIN | done (2c3b605, live: lofi→Emraan switch) |
| 38 | Voice command truncation fix: settle 1400→2000ms | FRONTEND | done (2c3b605) |

## Maya-transcript backlog (28-Aug analysis; priority order)

| # | Task | Lane | Why | Status |
|---|---|---|---|---|
| M1 | **Favorite-preference recall**: play_media/media queries pehle preference memory check kare | BRAIN | Memory recall | done (f91c8b6) |
| M2 | **Telegram gateway**: bot token + pairing, text/voice command → task → reply, files ≤20MB | BRAIN | Phone control | done (f91c8b6) |
| M3 | **Gmail SMTP/IMAP app-password provider** (email service me naya provider) | SUBSYSTEMS | Easy setup | done (c9de046) |
| M4 | **Browser agent: user ke REAL Chrome pe** (Chrome extension bridge ya CDP) + URL guardrail + **OTP-wait pattern** | SUBSYSTEMS | Logged-in sites | done (90ae067) |
| M5 | **Per-role model config**: browser-agent / quick-code / sub-agents ke liye alag model defaults | BRAIN | Free-tier trick | done (009d647) |
| M6 | **Voice enrollment (speaker ID)**: 1-min sample, threshold, owner/family/guest roles | BRAIN | Owner security | done (46c9e68) |
| M7 | **Echo guard tuning**: barge-in sensitivity + echo-tail (speaker band hone ke baad mic 2.5s off) | FRONTEND | Self-loop fix | done (500b466) |
| M8 | **SerpAPI search provider** (fast Google) | BRAIN | Research speed | done (554c3e4) |
| M9 | **Persona config**: naam/gender/voice/style + multi-persona (Maya & JARVIS) | FRONTEND + BRAIN | Dual personas | done (98dab6f) |
| M10 | **Photo edit skill**: rembg + PIL (background change, color variants, crop, resize) | SUBSYSTEMS | Local photo edit | done (e4876db) |
| M11 | **Whiteboard/diagram canvas** (voice se samjhao + draw; interactive canvas) | FRONTEND | Teaching UX | done (554c940) |
| M12 | **Ghost Editor**: raw clips → auto-edit (subtitles/transitions) → reels → render → YouTube upload | SUBSYSTEMS | Video editor | open |

## Completed (recent)

| Task | Commit | Verified |
|---|---|---|
| Native app discovery (PowerShell exit) | c7489d4 | 126 apps live, 0 subprocess |
| Quota budgeter + model spreading + response cache | 2392bf1 | 705 tests |
| Permanent memory (tombstone, history, FTS5, vault) | b59898e | 715 tests, 2016-record recall |
| LLM triage + honest labels + LLM research synthesis | e260131 | 727 tests |
| Voice auto-on + honest briefing + neuron pulses + brand mark | 97fb47a | build + 1182 tests |
| WS replay cursor + quota chip | 54dc441 | build |
| Parallel-session work preserved | a9cfa8f | boot + 55 tests |

## Notes

- Do agents same file pe mat likho. Lane ke bahar problem dikhi? TASKBOARD me
  naya row daalo "proposed" status ke saath — owner approve karega.
- Adhura kaam chhodna pada? "in-progress" commit + is board pe line.

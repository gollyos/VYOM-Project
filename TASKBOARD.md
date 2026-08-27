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
| 10 | Telegram gateway fail-closed owner auth, scoped files, remote provenance | BRAIN + VERIFY | done (f91c8b6) |
| 11 | Add weather/currency/crypto/trivia builtin tools (no-key free APIs) | BRAIN | done (4f6a768) |

## Maya-transcript backlog (28-Aug analysis; priority order)

| # | Task | Lane | Why |
|---|---|---|---|
| M1 | **Favorite-preference recall**: play_media/media queries pehle preference memory check kare ("mujhe X pasand hai" → "favorite song chala do" → X) | BRAIN | done (f91c8b6) |
| M2 | **Telegram gateway**: bot token + pairing, text/voice command → task → reply, files ≤20MB dono taraf | BRAIN | Phone control bina Android app ke |
| M3 | **Gmail SMTP/IMAP app-password provider** (email service me naya provider) | SUBSYSTEMS | OAuth ki jagah easy setup, Maya-style |
| M4 | **Browser agent: user ke REAL Chrome pe** (Chrome extension bridge ya CDP) + URL guardrail + **OTP-wait pattern** (login flow me user OTP dale, agent wait kare) | SUBSYSTEMS | Logged-in sites (Flipkart etc.) ab Playwright me nahi chalte |
| M5 | **Per-role model config**: browser-agent / quick-code / sub-agents ke liye alag model defaults (free OpenRouter/NVIDIA options) | BRAIN | Maya ka free-tier trick; VYOM registry me sirf role-override chahiye |
| M6 | **Voice enrollment (speaker ID)**: 1-min sample, threshold, owner/family/guest roles; "sirf meri command" guarantee | BRAIN | Owner-only security |
| M7 | **Echo guard tuning**: barge-in sensitivity + echo-tail (speaker band hone ke baad mic 2.5s off) | FRONTEND | Self-loop / duplicate reply bug |
| M8 | **SerpAPI search provider** (fast Google) | BRAIN | Research speed |
| M9 | **Persona config**: naam/gender/voice/style + multi-persona | FRONTEND | Maya/Friday/Venom jaisa |
| M10 | **Photo edit skill**: rembg + PIL (background change, color variants) | SUBSYSTEMS | Maya demo feature |
| M11 | **Whiteboard/diagram canvas** (voice se samjhao + draw; mermaid se aage) | FRONTEND | Teaching UX |
| M12 | **Ghost Editor**: raw clips → auto-edit (subtitles/transitions) → reels → render → YouTube upload | SUBSYSTEMS | Bada project, last priority |

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

# TASKBOARD — Multi-Agent Work Board

> Rules: lane lena hai to is file me edit karke claim karo. Ek lane = ek agent = ek time.
> Status: `open` / `in-progress (agent, HH:MM)` / `done (commit-hash)` / `blocked (reason)`

## Board

| # | Task | Lane | Status |
|---|---|---|---|
| 1 | LIVE E2E: "Chrome kholo + YouTube lofi play" real window me VERIFIED_COMPLETE | VERIFY | open |
| 2 | Desktop release build (`npm run desktop:build`) + installed app me voice auto-on check | VERIFY | open |
| 3 | Morning briefing live: real failed/paused tasks briefing me bole | BRAIN | open |
| 4 | Paper-trade ek real setup end-to-end (data → thesis → risk PASS → paper order) | SUBSYSTEMS | open |
| 5 | WS replay live test: task chalate time disconnect karke events wapas aaye | VERIFY | open |
| 6 | /api/quota budget chip real app me dikhe (15% pe amber) | FRONTEND | open |
| 7 | Meta-learning / multi-agent orchestrator ke liye live smoke test | SUBSYSTEMS | open |

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

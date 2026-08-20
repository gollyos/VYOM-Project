# VYOM Cognitive Runtime (Phase 16)

Modules: `runtime/cognitive_runtime.py`, `runtime/mission_loop.py`,
`adaptive/learned_router.py`, `workbench/media.py`; extensions to
`runtime/task_runtime.py`, `routing/model_router.py`,
`memory/resolution.py`, `workbench/engine.py`.

## Cognitive runtime (live wiring)

Every meaningful task now begins with the resolution chain INSIDE the
real Task Runtime — not a demo helper:

```
Goal -> CognitiveRuntime.prepare()
     -> Memory -> Experience -> Knowledge -> Skill -> Tool
     -> (external research only if still needed)
     -> compact ExperienceContext -> Planner -> Execution
```

The result lands on `task.metadata["cognitive"]` (namespace,
resolution source, hits, reuse decision, similar experiences, relevant
failures) and streams operational events ("Using memory before
planning…", "Reusing previous verified solution…"). Failures in
cognitive resolution are logged and never block execution.

**Memory before questions**: `answer_from_memory()` answers factual
questions from verified memory/entities/experiences BEFORE asking the
user — and requires the hit to actually be about the asked subject
(asking stays legitimate when memory is missing, low-confidence, or
about something else).

**Follow-up understanding**: `resolve_reference()` resolves
"that"/"it"/"fix it"/"continue/yesterday" against the ActiveContext
(current project/client/mission/artifact/research; domain-tagged so
personal context never leaks into client work).

## Learned router (evidence, not replacement)

`adaptive/learned_router.py` adds historical Phase 14 evidence to the
EXISTING routers:

- **Tool routing**: `preferred_tool()` picks the known-good tool per
  condition (Defuddle on static pages; Playwright after Defuddle
  failures on JS-heavy pages). Minimum 2 samples per condition — one
  lucky run never decides. Thin evidence defers to the default order.
- **Model routing**: `model_bias()` feeds context-specific (per-domain)
  success evidence into `ModelRouter.route()` scoring — never one
  global best-model. The Model Router stays authoritative.
- **Strategy selection**: `strategy_check()` delegates to the Phase 14
  StrategyEngine's REUSE/ADAPT/REPLAN with current conditions.

## Mission loop

`runtime/mission_loop.py` — the bounded autonomous working loop:

```
Goal -> resolve context -> plan (goal-derived deterministic
        decomposition; no model call) -> execute step -> observe ->
verify -> on failure: inspect + retrieve experience + adapt + bounded
retry -> continue -> final verification -> learn -> report
```

Bounds (`MissionLimits`): max steps, retries/step, runtime, model
calls, tool calls, budget — exceeded means an honest pause/fail, never
an endless loop. Cancellation interrupts the RUNNING step (execution
races the cancel event) and persists a checkpoint through the EXISTING
CheckpointStore; `resume()` continues from the checkpoint instead of
restarting. L2/L3 steps pause only that step (`needs_approval`) and
resume after approval. Every mission outcome feeds the Phase 14
learner (`task_type="mission"` experiences).

## Media completion (Universal Workbench)

One `workbench/media.py` — no separate media agents:

- **FFmpegAdapter** (ffmpeg 9.0): audio inspect/trim/convert/normalize/
  extract/merge; video inspect/trim/convert/transcode/resize/extract-
  frames/extract-audio/replace-audio. Every output is VERIFIED via
  ffprobe (file exists, duration readable, dimensions match) — exit
  code 0 alone is never completion.
- **PdfAdapter** (PyMuPDF, the one PDF dependency): inspect/text/page
  count/render/merge/split with reopened-and-counted verification.
  Generation stays in the Artifact Engine.
- Honest unavailability remains: if ffmpeg/PyMuPDF are missing on a
  machine, the Workbench reports those kinds unavailable — never faked.

## Dependency additions (minimal)

ffmpeg 9.0 executable (winget) and PyMuPDF (pip). No media frameworks,
no new services, no new databases, no new agents.

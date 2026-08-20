# VYOM Operator Reference Research — 2026-08-20

This note turns external product research into VYOM-specific engineering
requirements. It is not authority by itself; `VYOM_PROJECT_MEMORY.md`, the
Permission Engine, verified repository behavior, and user corrections remain
authoritative.

## Confirmed references

### Hermes Agent

Primary reference: https://github.com/NousResearch/hermes-agent/blob/main/AGENTS.md

Useful patterns:

- One agent core serves desktop, CLI, TUI, messaging gateways, schedules, and
  delegated workers. VYOM adopts the same single-core principle through its one
  Task Runtime; phone, voice, text, and cron are clients/sources, not Brains.
- Keep the core a narrow control waist. Capability should grow through
  registries, adapters, skills, and plugins at the edges instead of adding a
  new command path for every feature.
- Background workers need isolated contexts, bounded concurrency/depth,
  durable result delivery, and clear parent ownership.
- Skills are procedural memory. They need provenance, tests, usage metrics,
  staging/approval, rollback, pin/archive behavior, and must never silently
  overwrite a trusted working procedure.
- Cron work needs persistence, catch-up/grace rules, duplicate-tick exclusion,
  bounded runtime, isolated sessions, and explicit delivery destinations.

Current VYOM mapping:

- Same Brain command bus, scoped task/context identities, ten-task budget,
  durable cron/automation records, approvals, memory, SkillSpecs, bounded
  agents, checkpoints, verification, and remote-session security are wired.
- Messaging gateway delivery, physical phone E2E, durable background-result
  delivery across a Brain crash, cron context chaining/delivery destinations,
  and the complete skill curator lifecycle remain expansion work.

### Graphify

Primary reference: https://graphify.com/concepts

Useful patterns:

- A graph is supporting infrastructure, not the intelligence or command owner.
- Code entities and relationships should be parsed deterministically where
  possible; inferred relationships must be labeled separately.
- Every edge needs provenance such as `EXTRACTED`, `INFERRED`, or `AMBIGUOUS`.
- Graph traversal answers relationship/impact questions; embeddings remain the
  right tool for fuzzy prose retrieval. Neither replaces durable task, memory,
  permission, or evidence stores.
- Incremental refresh is preferable to rebuilding or re-reading the full repo
  for every coding task.

Current VYOM mapping:

- VYOM already treats graphs as a bounded retrieval aid and has a restricted
  codebase-memory adapter/fallback. A live Graphify installation/index is not
  configured or verified, so it must not be represented as active.
- Before any Graphify adoption, route it through the existing external
  capability intake: license/security review, registered-root restriction,
  local benchmark, provenance preservation, dry-run, user approval, and
  measured benefit over the current code retrieval path.

### Maya-style AI employee workflows

Confirmed reference reviewed: https://bymaya.ai/about-maya/

The exact `HunteAI/Maya` product named by the user could not be identified
reliably from public search on 2026-08-20; do not pretend the similarly named
site is necessarily the same product.

Useful patterns from the confirmed Maya reference:

- Express professional work as objective -> sub-objectives -> instructions ->
  tools -> verified outcome, not as a single conversational response.
- Support direct commands, schedules, and event triggers such as a new message,
  document, CRM update, meeting completion, or marketing request.
- Treat feedback as a versioned instruction/reference correction and use
  automated tests plus feedback loops to keep a workflow on its objective.
- Professional roles are reusable workflow packs over one operator; they are
  not separate identities competing for user ownership.

Current VYOM mapping:

- Mission packs, the bounded mission loop, capabilities, schedules, approvals,
  evidence, verification, experience learning, CRM, research, artifacts, and
  professional delivery cover the base architecture.
- Broad event-trigger coverage, more live business integrations, physical
  gateway delivery, and real end-to-end professional workflow acceptance tests
  remain incomplete.

## YouTube and video research rule

Recent demos are useful for discovering interaction patterns and real failure
modes, but a video or summary is not implementation proof. For each candidate:

1. Record title, channel, URL, upload date, product/version, and transcript.
2. Extract the full demonstrated workflow, including permissions, corrections,
   background behavior, failure handling, and evidence—not only the highlight.
3. Cross-check claims against official docs/source and current release notes.
4. Map each useful pattern to an existing VYOM owner before adding code.
5. Add a capability only through the registry/skill/adapter boundary and verify
   it with a repeatable task-level acceptance test.

Initial video indexes reviewed:

- Hermes learning/masterclass index:
  https://getcoai.com/video/hermes-agent-master-class/
- Hermes run-your-day video summary (video id retained for transcript review):
  https://www.youtube.com/watch?v=drXe7cfvKEk
- Graphify official video/article index:
  https://graphify.com/blog

### HunteAI Maya 6.0 / Android transcript set and stock-research short

User-supplied transcript sources reviewed on 2026-08-20:

- `32eb9a45-d7a6-400e-a763-9858dcd726fc/pasted-text.txt`
- `9ab87745-56b3-40d4-ae3c-c6a89fbce743/pasted-text.txt`
- `d1b4e7ab-831b-4f63-b826-37db2db4eae9/pasted-text.txt`
- The Hunter AI short, uploaded 2026-08-19:
  https://www.youtube.com/shorts/Na0AWCkM4aY
  (`Maya Ko Stock Market Research Agent Banane Ko Bola…`; duration 38 s).

The short had no exposed YouTube transcript in the reviewed session. Its title,
description, duration, channel and upload date were checked against the live
page, then cross-matched to the user-supplied transcripts. Demonstrated product
claims remain reference evidence, not independent proof that the product can
reliably perform them.

Useful patterns:

- Raw conversation/history is kept separately from filtered durable knowledge,
  with provenance visible as layers/branches rather than flattening everything
  into the current identity.
- A spoken objective can create a named worker, schedule it, run it now, show
  mission status, save an artifact and deliver it through another channel.
- A restricted worker requests privileged delivery from the owner agent rather
  than receiving unrestricted WhatsApp/PC access directly. This maps cleanly to
  VYOM's central capability broker and Permission Engine.
- Teachable macros record a sequence, accept corrections while recording, and
  identify values that must be requested at execution time. VYOM should map
  that to versioned SkillSpecs with typed runtime input slots, validation and
  outcome verification—not blind coordinate replay.
- Direct APIs/CLI are faster and more reliable than visual screen automation;
  visual automation belongs at the end of the fallback order and needs progress,
  timeout, take-over and postcondition evidence.
- Phone/text/voice are useful command transports, while the durable task,
  permission, memory and evidence owners remain in the one Brain.

Patterns explicitly rejected for VYOM:

- Disabling Windows Defender, SmartScreen, Play Protect or other OS security to
  install unsigned automation software.
- Granting unrestricted PC/phone/accessibility authority to a delegated worker.
- Installing a plugin/MCP/capability directly from a URL without controlled
  intake, pinning, sandboxing, benchmark, permission review and approval.
- Showing or persisting private chain-of-thought. VYOM exposes operational
  actions, observations, errors, corrections and evidence only.
- Treating a large tool count as intelligence. VYOM measures verified task-level
  completion, latency, retries, cost and safe reuse.
- Copying romantic/dependency-forming persona behavior. VYOM may be warm and
  natural without pretending emotional dependence or weakening user autonomy.

## VYOM priority order derived from this research

1. Preserve one durable Brain and one command/task/evidence path.
2. Finish a real authenticated phone/messaging gateway and durable result
   delivery without cloning memory or authority.
3. Expand Windows/app work through adapters, UIA, browser semantics, and a
   controlled fallback, with take-over/cancel and postcondition verification.
4. Add a staged skill curator that turns verified repeated workflows into
   reusable, testable procedures without forgetting prior working versions.
5. Add durable event triggers and richer cron delivery/catch-up semantics.
6. Benchmark an on-device code knowledge graph behind the existing cognitive
   resolution chain; keep edge provenance and an honest fallback.
7. Build professional end-to-end acceptance packs (research, coding, agency,
   documents, meetings, CRM, n8n) that measure whole-goal completion.
8. Turn the currently separate task/memory/goal/project/commitment/artifact/
   experience/skill/evidence stores into one provenance-labelled, traversable
   operating graph without replacing any authoritative owner.

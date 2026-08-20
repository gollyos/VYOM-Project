# VYOM Memory Architecture

## Purpose and boundaries

Phase 6 adds persistent operational intelligence without turning VYOM into one undifferentiated vector store. The local Brain owns memory; the React/Tauri frontend only receives selected summaries and contextual graph objects. Hidden reasoning, partial tokens, animation events, passwords, API keys, and private chain-of-thought are never memory records.

## Memory model

`MemoryEntry` supports working, episodic, semantic, procedural, project, client, person, preference, decision, failure, lesson, tool-performance, model-performance, and agent-performance records. Every durable record carries a type, title, content, summary, entities, tags, provenance, timestamps, importance, confidence, sensitivity, verification state, optional project/client/task/agent scope, expiry, supersession, and metadata.

Verification states are `unverified`, `inferred`, `verified`, and `superseded`. Provenance types are user statement, verified tool result, task result, external source, generated summary, agent observation, and manual import. Provenance may reference a task, event, URL, file, evidence identifier, and timestamp.

## Storage and retrieval

SQLite stores structured JSON plus indexed columns. Retrieval is hybrid:

1. Apply type, project, client, agent, sensitivity, verification, and expiry filters.
2. Score keyword overlap and provider-independent semantic similarity.
3. Add bounded recency, importance, confidence, verification, and relationship signals.
4. Exclude superseded records and return a small ranked set with human-readable ranking reasons.

The default semantic provider is a deterministic local hash embedding. `EmbeddingProvider` can later host a local model or remote adapter. With embeddings disabled, structured and keyword retrieval continues to work.

## Consolidation and correction

The runtime consolidates verified, important task outcomes into operational summaries; it does not save every event. Explicit user preferences and verified project facts are stored directly. A correction marks the old fact `superseded`, lowers its confidence, and links the replacement through `supersedes`. `forget` hard-deletes the memory and cascading relationships; its event contains only the deleted identifier.

## Privacy

Sensitivity is `normal`, `sensitive`, or `highly_sensitive`. Retrieval callers choose a maximum sensitivity. Ordinary memory validation rejects obvious secret material; credentials remain in native/backend-safe secret configuration. Future model routing must limit external context using both task privacy and retrieved-memory sensitivity.

## Knowledge relationships and visuals

The local relationship table supports `WORKS_ON`, `BELONGS_TO`, `DEPENDS_ON`, `CREATED_BY`, `USES`, `KNOWS`, `RELATED_TO`, `BLOCKED_BY`, `PRODUCED`, `PREFERS`, and `LEARNED_FROM`. The graph API performs bounded traversal to depth three. The Composer renders only relevant summoned clusters, never a permanent memory dashboard.

## Phase 11 personal data

Personal-life data (routines, habits, productivity patterns, personal
commitments) defaults to `sensitive` (`config/personal.yaml`). Structured,
gradually-learned personal facts live in `PersonalProfile`
(`services/brain/app/personal/schemas.py`) — a lighter-weight sibling to
`MemoryEntry` purpose-built for typed fields (timezone, working hours,
quiet hours, energy preference) that each carry their own
`last_confirmed`/`confidence`/`expires_at` and supersede cleanly on
correction, the same provenance discipline as `MemoryEntry`. Narrative
preference statements ("Remember that I want to avoid working after
midnight") still go through the normal `MemoryEntry`/`MemoryType.PREFERENCE`
path described above; `IntelligenceEngine` additionally extracts a
structured field from recognized statements so the Chief-of-Staff layer
can reason about them, not just recall them in prose. Personal data is
never sent in full to an external model — only the minimum relevant
fields route through the privacy-aware Model Router.

## User operations

Local APIs provide create/search/inspect/update/forget/graph operations. Deterministic commands cover preference remember/recall/forget/provenance/correction, verified project-memory capture, project build recall, and related-memory visualization. All modifications emit observable Brain events.

## Phase 14

Typed memory now works alongside the adaptive Experience store
(`app/adaptive/`): memories carry knowledge with provenance and
confidence; Experiences carry operational outcomes with fingerprints
and conditions. Retrieval is combined in the compact planner context,
user corrections are the highest-priority source, and old experience
confidence decays when environments change.

## Phase 15

Memory is organized into eleven cognitive namespaces routed through the
existing typed store (namespace tag + natural type mapping). The
ResolutionChain answers from memory -> experience -> knowledge -> skill
-> tool before any external research or user question. Intelligence is
never persisted as loose .md/.txt files.

## Phase 16

The ResolutionChain now runs inside the live Task Runtime for every
meaningful task; memory-before-question answers require the hit to be
about the asked subject; follow-up references resolve through the
domain-tagged ActiveContext.

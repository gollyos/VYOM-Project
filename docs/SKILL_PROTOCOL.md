# VYOM Skill Protocol

## Definition

A skill is a reusable, declarative procedure—not a large prompt. `SkillSpec` contains identity/version, inputs/outputs, capability/tool/permission requirements, dependency-aware steps, verification checks, failure policy, bounded cost/runtime/calls, provenance, status, and measured performance.

Generated skills are stored under `data/skills/<skill-id>/` as `skill.yaml`, `instructions.md`, `tests/manifest.yaml`, `CHANGELOG.md`, and archived `.versions` snapshots.

## Lifecycle

Statuses are draft, testing, approved, active, deprecated, disabled, and failed. Creation follows:

```text
goal -> equivalent-skill search -> capability check -> SkillSpec
     -> restricted sandbox policy tests -> evaluation -> promotion or failure
```

L0/L1 skills may become active only when every deterministic sandbox check passes. L2/L3 skills remain testing until explicit approval. A failed candidate remains failed and cannot execute. The production executor accepts only approved/active registered skills and routes every action through the existing Action Engine, Tool Registry, permission checks, audit evidence, and verifier.

## Matching and duplicate control

Matching ranks active skills using relevance, success rate, and recency. Creation performs normalized semantic/token matching first, preventing equivalent names such as build-check, check-build, and project-build-validator. Phase 6 implements one real generated procedure, `project-build-check`, as the safe vertical slice.

## Sandbox and budgets

The sandbox verifies registered capabilities/tools, allowed permissions, bounded runtime/model/tool calls, step count, and evidence-based verification. It grants no new authority. The build skill runs within approved project roots and uses an isolated Vite verification output when the active desktop output is locked.

## Evaluation and versioning

Metrics track executions, successes, failures, verification score, average runtime/cost, common failure reason, success rate, and last use. Updates require an increasing semantic version; the previous spec is archived and can be rolled back. Working skills are never silently overwritten.

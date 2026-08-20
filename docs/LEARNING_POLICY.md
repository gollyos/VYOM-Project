# VYOM Learning and Self-Improvement Policy

## Principle

Learning is event-driven and evidence-bound. VYOM does not run an uncontrolled continuous thinking loop and never represents an unverified failure as success.

VYOM may autonomously improve:

- structured memory and confidence;
- reusable L0/L1 skill instructions after sandbox tests;
- skill routing and workflow ordering;
- declarative agent configurations within inherited authority;
- model/tool/skill/agent preference scores from verified outcomes.

VYOM may not autonomously modify:

- security boundaries or the permission engine;
- approval requirements or secret handling;
- production bootstrap/runtime safety;
- arbitrary production-core source code;
- install arbitrary code, enable L2/L3 authority, or spend unbounded cost.

## Failure learning

The Failure Analyzer recognizes a small controlled set of operational patterns such as missing dependencies, missing environment variables, unavailable commands, permission problems, and unreachable local servers. A lesson is stored only when evidence exists and confidence meets policy. The failure is a verified record; the generalized lesson is explicitly `inferred` and linked with `LEARNED_FROM`.

Unknown or vague errors do not become permanent rules. Relevant lessons may be retrieved before a similar workflow and emit `learning_applied`. User corrections supersede contradicted facts rather than preserving both as equally true.

## Promotion rules

Safe skill auto-promotion requires all deterministic sandbox checks and evidence. Consequential skills require explicit approval. Agent readiness requires capability/tool/skill availability, permission inheritance, scoped memory, bounded budgets, defined verification, and a passing sample mission. Versioned rollback remains available.

All loops have explicit model/tool/runtime/cost limits. Core architectural changes require user/developer approval and normal code review/testing.

## Phase 14 additions

Learning is now also outcome-driven through the adaptive layer
(docs/ADAPTIVE_INTELLIGENCE.md): experiences, failure signatures,
context-aware strategies, and routing preferences learn from real
verified outcomes. All Phase 6 boundaries are unchanged: no
self-modification of security/permission/core code, and the new
AdaptivePolicyEnngine additionally enforces that risk hard limits can
never be autonomously increased.

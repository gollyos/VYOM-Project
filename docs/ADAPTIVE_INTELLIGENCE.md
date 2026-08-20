# VYOM Adaptive Intelligence (Phase 14)

Modules: `services/brain/app/adaptive/` — schemas, experience_store,
learner (+ AdaptiveLearningBridge), policy_engine, strategy_engine,
evaluator, context. Config: `config/adaptive.yaml`. Deliberately
compact: no new database (three tables added to the existing one via
migration v2), no new services, no new dependencies.

## Experience model

Every meaningful task can produce an `Experience`: fingerprints
(goal/context tokens), domain, environment, models/agents/skills/tools
used, strategy, plan summary, result, success, verification score,
latency/cost/retries, normalized failure signature, user correction,
conditions (regime, site type, data quality...), lessons, confidence.
Operational summaries and evidence only — hidden chain-of-thought is
never stored.

## Learning loop (event-driven, bounded)

`AdaptiveLearningBridge` subscribes to the existing event bus and
records experiences after `task_completed` / `task_failed` /
automation outcomes. Learning itself is deterministic — no LLM call
ever runs inside it, and there is no continuous self-thinking loop.
`SelfEvaluator` runs lightweight operational post-checks only for
meaningful tasks (failed, retried, corrected, expensive); clean
verified successes skip evaluation.

## Retrieval (fingerprint similarity, small ranked sets)

Before non-trivial planning, `AdaptiveContextService` builds a compact
`ExperienceContext`: ≤3 similar experiences, ≤3 relevant failures, a
reuse decision, routing hints, cautions — ranked by goal/context
similarity + environment match + outcome relevance + verification +
recency decay. Irrelevant experiences are rejected (score floor).
Memory-before-question: verified entities (projects/clients) are
answered from experience/memory instead of asking the user again.

## Reuse vs adapt vs replan

`StrategyEngine.decide_reuse()` distinguishes:
- **REUSE** — proven strategy with matching conditions and no
  environment change.
- **ADAPT** — relevant experience but environment changed or
  conditions only partially match ("framework upgraded", "site layout
  changed").
- **REPLAN** — no proven strategy or under-sampled evidence.

Old strategies are never blindly replayed.

## Strategies (generic, context-aware)

A `StrategyRecord` is a reusable approach for a class of tasks (coding
bug fix, research, browser recovery, meeting prep, trading). It knows
WHEN it works: performance is stored per condition/regime, decayed by
recency (half-life configurable), and shrunk toward neutral until the
minimum sample is reached. A strategy with zero outcomes under current
conditions is discounted — a perfect aggregate record cannot outrank a
strategy actually proven in this regime. Status lifecycle:
active → watch → degraded → paused → retired (degradation pauses PAPER
usage rather than running a broken strategy forever).

## Trading adaptation

Regime-specific evaluation (trending/range/high-volatility...) drives
PAPER strategy selection; risk hard limits (max risk per trade, daily
loss, drawdown, leverage) can never be autonomously increased — the
policy engine rejects any risk-increasing application outright
(`ProtectedPolicyError`); decreases are allowed. Strategy evolution is
versioned and evidence-gated: degradation → proposal → backtest →
out-of-sample validation → paper comparison → `promotable` only when
the evidence beats the current version; working strategies are never
overwritten, promotion still requires the user, and nothing ever
auto-promotes to live trading.

## Confidence & anti-overfitting

Confidence derives from sample size, verification, recency, condition
similarity, and consistency — one success never establishes a strong
rule. Trading requires a larger minimum sample (`config/adaptive.yaml`)
and separates development/validation/paper evaluation through the
existing Phase 10 backtester.

## User corrections (highest learning weight)

Explicit corrections are stored as `source=user_instruction` with
confidence 1.0 and supersede inferred knowledge: priority is
user instruction > tool evidence > repeated success > model inference
(`AdaptivePolicyEngine.resolve_conflict`). Corrections persist across
restarts; the user never repeats them.

## Routing learning

`model_performance()` aggregates the existing `model_performance`
rows per model × domain (context-aware, never one global score);
`tool_performance()` / `preferred_tool()` route tools by recorded
conditions (e.g. Defuddle for static sites, Playwright for JS-heavy)
and never conclude from a single run.

## Protected policies

Learning may adjust: model/tool/strategy/skill preferences, rankings,
workflow ordering, memory confidence, strategy status. It may never
touch: security boundaries, the Permission Engine, L2/L3 requirements,
the SecretStore, authentication, risk hard limits, system safety, or
production bootstrap (`AdaptivePolicyEngine`).

## Unknown tasks & experimentation

Unknown work yields a REPLAN decision and routes to the existing
capability search / research / discovery engines instead of failing.
Bounded exploration (`ExperimentationBudget`) may try alternatives on
low-risk choices only, capped per day — never on consequential L3
actions.

## Continuity & world state

`AdaptiveContextService` aggregates references from existing stores
(active tasks, goals, devices) for "what is happening right now",
resolves references ("make a presentation from that" → latest verified
research), and reconstructs cross-session continuation (unfinished
work + last verified step) — continuation itself always runs through
the normal permission path.

## Phase 16

The LearnedRouter feeds Phase 14 evidence into the existing Model
Router (context-specific bias) and tool selection (per-condition
preference, minimum two samples); mission outcomes are recorded as
`mission`-type experiences.

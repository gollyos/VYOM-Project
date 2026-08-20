# VYOM Proactive Intelligence Engine

## The gate

`ProactiveEngine.evaluate()` (`services/brain/app/proactive/engine.py`)
is the concrete enforcement of rule 31 — every check below must pass
before a suggestion actually surfaces:

```text
ProactiveSuggestion
  -> RelevanceChecker: important enough for the current level? actionable?
     auto-handleable by VYOM itself (then don't interrupt)?
  -> TimingEvaluator: is now a good time (quiet hours / focus session /
     explicit quiet-mode window)?
  -> SuppressionEngine: has an equivalent suggestion already surfaced
     recently? within the daily low-priority limit?
  -> surfaced (recorded) | suppressed (with a concrete reason)
```

`critical` urgency always bypasses quiet hours, focus mode, and explicit
quiet-mode windows (rule 33) — nothing else does, and this is enforced in
`TimingEvaluator`/`RelevanceChecker`, not left to a prompt instruction.

## Proactive levels

`ProactiveLevel`: `quiet` (importance ≥ 0.9 only), `balanced` (≥ 0.55,
the default), `proactive` (≥ 0.3) — `config/notifications.yaml:
proactive.default_level`. The level maps to a minimum-importance
threshold in `ProactiveRules.min_importance_for()`.

## Suppression

`SuppressionEngine`/`ProactiveSuggestionStore`
(`services/brain/app/proactive/suppression.py`) persist every surfaced
suggestion keyed by a content-derived `dedupe_key`. A duplicate within
`duplicate_window_hours` (default 24) is suppressed; low/informational
suggestions are additionally capped at `max_low_priority_per_day`
(default 3) — `important`/`urgent`/`critical` items are never subject to
that daily cap (rule 35/36).

## Feedback

`FeedbackTracker` (`services/brain/app/proactive/feedback.py`) records
`surfaced`/`dismissed`/`opened`/`acted_on`/`snoozed` outcomes to improve
future timing/relevance. This tuning is advisory only — past dismissals
never suppress a genuinely `critical` notification; that exception is
hard-coded in the timing/relevance checks, not learned (rule 36).

## Quiet mode

`QuietModeState` (`services/brain/app/notifications/quiet_hours.py`)
implements *"don't disturb me for 2 hours unless it's critical"*: a
time-bounded window that automatically ends — the user never has to
remember to turn it back off. Only `critical` bypasses it.

## What "good" proactive behavior looks like

Rule 64's example — *"Finora's deadline is tomorrow and the Developer
Agent is waiting on your approval. You have 40 minutes free now.
Reviewing it would unblock the delivery."* — passes every gate: it's
important (deadline + blocked delivery), actionable (a concrete 40-minute
window exists), well-timed, not already surfaced, not something VYOM can
resolve itself, and the interruption cost is clearly below the benefit.
Rule 65's counterexample — repeating *"you haven't completed your
morning routine"* every morning — fails the duplicate-suppression check
after the first occurrence and is never sent again within the window.

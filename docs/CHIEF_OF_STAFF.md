# VYOM Chief of Staff

## Principle

`ChiefOfStaffOrchestrator` (`services/brain/app/chief_of_staff/orchestrator.py`)
answers: what needs attention, what can VYOM handle itself, what requires
the user, what is at risk, what might be forgotten, what can be
delegated, and what should happen next. This layer consumes existing
VYOM systems (goals, habits, commitments, workload, tasks, CRM) through an
explicit `ChiefOfStaffContext` bundle the caller assembles from real data
— it never bypasses the Permission Engine, Risk Engine, or any tool
boundary underneath those systems (rule 26).

## Priority Engine

`PriorityEngine` (`services/brain/app/chief_of_staff/priority_engine.py`)
combines urgency, importance, goal alignment, client impact, financial
impact, dependency, risk, and a bounded user-preference bonus into a
score — but every `PriorityScore` also carries `reasons`, the top
contributing factors in plain language. There is no bare opaque
AI-generated number (rule 27).

## Risk and opportunity detection

`RiskDetector` surfaces risk only from real computed signals: an
overloaded `WorkloadAssessment`, overdue commitments, neglected goals,
and a high pending-approval count. `OpportunityDetector` identifies free
time paired with delegatable agent work, and flags a repeated manual
action only once it has actually recurred at least
`repeated_action_threshold` times (default 3) — never after a single
instance (rule 66/67).

## Recommendation Engine

`RecommendationEngine` prefers one primary recommendation plus at most
two alternatives (rule 69) — never a long list unless the user explicitly
asks for more. `"What should I work on right now?"` returns exactly this
shape: one action, one reason, an optional time estimate.

## Follow-up tracking

`FollowUpEngine` aggregates unresolved items VYOM already has visibility
into: overdue commitments, drafts awaiting send, agents waiting on
approval, blocked tasks. This module only assembles candidates from real
records — whether/when to actually interrupt the user with one is decided
separately by the Proactive Intelligence Engine's relevance gate
(`docs/PROACTIVE_INTELLIGENCE.md`).

## Commitment summary

`CommitmentSummaryBuilder`
(`services/brain/app/chief_of_staff/commitment_tracker.py`) groups open
`Commitment` records (`services/brain/app/personal/commitments.py`) by
urgency — overdue, due within 48 hours, other open — so *"what have I
promised people?"* answers from real records with deadlines and sources,
never a guess (rule 25/62).

## Agents

Two declarative agents (`config/agents.yaml`) register this layer's
capabilities in the Capability Registry: `personal-operations-agent`
(goals/habits/routines/focus/reviews, limited permissions) and
`chief-of-staff-agent` (cross-domain prioritization/planning/delegation
suggestions). Neither bypasses tool permissions — they coordinate the
existing runtime and agents (rule 44).

## Life + work unification, with boundaries

Chief of Staff sees relationships across personal and work context (a
late client meeting conflicting with a workout, rule 52) but never
exposes personal details — habits, private goals, portfolio data, other
clients — inside a client- or business-facing output. See
`strip_personal_for_client_context()`
(`services/brain/app/personal/context_builder.py`) and rule 53.

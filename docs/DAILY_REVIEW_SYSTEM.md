# VYOM Daily Review System

## Morning Briefing 2.0

`MorningBriefingService` (`services/brain/app/daily_review/morning.py`)
takes a `MorningBriefingInput` bundle — calendar, email, CRM, clients,
projects, agents, automations, goals, habits, personal commitments,
market alerts, approvals — where every field is real, already-fetched
data (rule 37). It prioritizes rather than reading every source: at most
`max_highlights` (default 6) items are surfaced, ordered by pending
approvals, meetings, important email, client risk, active agent work,
goal/habit reminders, and market alerts, then asks whether to prepare
today's plan. No dashboard, no 30-metric wall (rule 38).

## Evening review

`EveningReviewService` (`services/brain/app/daily_review/evening.py`)
assembles *"how did today go?"* only from real recorded events — completed
tasks, verified work, meetings held, completed/open commitments,
goal-progress notes, focus-session minutes, and the best observed focus
window. An empty day honestly reports "No recorded activity for today
yet." rather than fabricating an accomplishment (rule 39/40).

## Weekly review

`WeeklyReviewService` (`services/brain/app/daily_review/weekly.py`) groups
wins, unfinished commitments, goal progress, client status, habit/focus
trends, model/agent performance, risks, and next-week priorities into
named sections — a section with no supplied data is simply omitted, never
padded (rule 41).

## Monthly review

`MonthlyReviewService` (`services/brain/app/daily_review/monthly.py`)
focuses on longer-term trends: business growth, client acquisition,
project progress, habit consistency, learning, personal goals, AI spend,
agent productivity, and Phase 10 paper-trading analytics when actually in
use. Bounded sections, not a metrics dump (rule 42).

## Command flow

```text
"How did today go?"        -> Phase11Engine._evening_review
"Give me my weekly review." -> Phase11Engine._weekly_review
```

Both route through the Task Runtime's deterministic Phase 11 delegation
(`docs/PERSONAL_OS.md`) — no paid model call is required to assemble a
review; a model may be used later to polish prose, but the underlying
facts and structure come from real records.

## Scheduling

Daily/weekly review generation reuses the existing Automation Runtime
(`docs/AUTOMATION_ENGINE.md`) the same way routines do
(`docs/GOALS_AND_ROUTINES.md`) — there is no second scheduler. A
scheduled review automation is never auto-enabled; it requires the same
explicit user action as any other automation (rule 51).

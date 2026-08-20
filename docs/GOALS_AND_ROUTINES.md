# VYOM Goals and Routines

## Goal vs. task

A goal is a durable outcome ("Grow the agency to 10 clients"); a task is a
concrete unit of work toward it ("research leads", "improve outreach").
`Goal` (`services/brain/app/goals/schemas.py`) never embeds a task list —
it carries a single `next_action` and references `related_projects`; full
task tracking stays in the existing Task Runtime/CRM/skills systems.

## Categories and states

`GoalCategory`: `business`, `career`, `health`, `learning`, `finance`,
`personal`, `relationship`, `project`, `other` — meaning is never assumed
from the category alone. `GoalStatus`: `idea` -> `active` ->
(`paused` | `blocked` | `completed` | `abandoned`), with `abandoned` able
to return to `idea`. Invalid transitions raise
`InvalidGoalTransitionError` (`services/brain/app/goals/manager.py`).

## Planning

`GoalPlanner` (`services/brain/app/goals/planner.py`) is a deterministic,
category-templated scaffold — no model call. It produces a small, bounded
set of milestones (`config/goals.yaml:
planning.max_initial_milestones`, default 4) and next-action candidates,
never hundreds of tasks at once (rule 5).

## Evidence-based progress

`GoalProgressEvaluator` (`services/brain/app/goals/progress.py`) never
lets a percentage appear without a defined basis (rule 6). Milestone
completion is always available as real local evidence once milestones
exist; `GoalEvidence` (CRM signal, habit consistency, task completion
ratio) refines the number only when the caller actually supplies a real
signal — a goal with no milestones and no evidence returns
`progress=None`, not a guessed number.

## Milestones

`Milestone`: `goal_id`, `title`, `target`, `deadline`, `status`
(`pending` | `in_progress` | `done`), `evidence`.
`MilestoneService.mark_done()` requires at least one evidence string —
"I'm calling this done" without evidence is rejected.

## Neglect detection

`GoalEvaluator` (`services/brain/app/goals/evaluator.py`) flags a goal as
neglected when it has been deferred `deferred_threshold` times
(default 3) or has no recorded progress for `stale_days_threshold` days
(default 21) — both from real recorded signals, never a guess. The
recommendation is always practical ("protected focus time or
delegation"), never a judgment of the user.

## Routines

`Routine` (`services/brain/app/routines/schemas.py`): `trigger`, `steps`
(`reminder`, `open_application`, `show_briefing`, `start_focus_mode`,
`run_automation`, `prepare_workspace`, `create_task`), `schedule`,
`enabled` (defaults `False` — never auto-enabled, rule 51), `adaptive`.

## Routine execution

`RoutineStepExecutor` (`services/brain/app/routines/completion.py`)
dispatches each step to a real handler bound to an already
permission-gated service (app launcher, focus session service, Task
Runtime, briefing service) — routines never call the OS directly. A step
type with no registered handler is honestly reported `unavailable`, never
faked as completed (matching the integration-honesty pattern used
throughout the codebase).

## Scheduling

`RoutineScheduler` (`services/brain/app/routines/scheduler.py`) reuses the
existing Automation Runtime (`docs/AUTOMATION_ENGINE.md`) rather than
building a second scheduler — a routine's `schedule` only takes effect
once explicitly enabled by the user.

## Adaptation

`RoutineAdaptationService` (`services/brain/app/routines/adaptation.py`)
proposes an adjustment only after `failure_streak_threshold` (default 3)
consecutive missed/failed runs — a routine that fails once is not
"adapted"; a routine that fails repeatedly is analyzed, not repeated
forever unchanged (rule 50).

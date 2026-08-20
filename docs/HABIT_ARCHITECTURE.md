# VYOM Habit Architecture

## Tracking boundary

Habit tracking uses explicit check-ins plus existing task/calendar/system
events plus user-approved integrations — nothing else. `HabitEvent.source`
is one of `manual`, `calendar`, `task_runtime`, `desktop_activity`,
`connected_service`, `automation` (`config/habits.yaml:
tracking.allowed_sources`). `habits/events.py:build_event()` rejects any
event whose source isn't in the approved list with
`UnapprovedEventSourceError` — this is the concrete enforcement of "no
invasive tracking" (rule 10), not just a policy statement. VYOM never
continuously records microphone, webcam, or screen content, never
keylogs, and never inspects private messages to infer a habit event.

## Habit model

`Habit` (`services/brain/app/habits/schemas.py`): `name`, `category`,
`desired_direction` (`build` | `reduce` | `maintain` | `avoid`),
`frequency`, `target`, `measurement_type` (`boolean` | `count` |
`duration_minutes`), `status`, `reminder_policy`, `linked_goal`.

## Pattern analysis

`HabitPatternAnalyzer` (`services/brain/app/habits/pattern_analyzer.py`)
computes time-of-day and day-of-week distributions and can correlate a
habit against caller-supplied context days (e.g. days flagged as having
an unfinished work session) — the direct mechanism behind the rule 11/59
example: *"Late-night social media use occurred on 4 of the last 6
weekdays. It appears most common after unfinished work sessions."* Every
returned `PatternInsight` carries `sample_size` and `confidence`; nothing
is returned below `config/habits.yaml`'s
`minimum_sample_size`/`minimum_confidence` — a weak correlation is never
presented as a fact (rule 13).

## Streaks

`StreakCalculator` (`services/brain/app/habits/streaks.py`) reports
`current_streak_days`, `longest_streak_days`, and
`consistency_trend_pct` (rolling window completion rate). A broken
streak never resets the consistency trend to zero, and streak
preservation is never the framing VYOM leads with (rule 14) — the
consistency trend is the primary signal.

## Interventions

`InterventionEngine` (`services/brain/app/habits/interventions.py`)
suggests one of `reminder`, `environment_preparation`,
`schedule_adjustment`, `focus_block`, `task_delegation`,
`reduce_notification_noise`, `shutdown_routine`
(`config/habits.yaml: interventions.allowed_types`), always phrased as an
offer grounded in a `PatternInsight`, never a command or a judgment.
Example: *"Would you like VYOM to move unfinished planning earlier and
add an end-of-day shutdown routine?"* No shaming, no manipulative
pressure, no diagnosis language (rule 45/49/77) — it says "pattern
detected", never "you have a disorder".

## Insufficient data

`HabitInsightService.report()`/`bad_habit_analysis()`
(`services/brain/app/habits/insights.py`) explicitly return
`sufficient_data=False` with an honest message when there isn't enough
recorded evidence — VYOM never invents a psychological cause (rule 59).

## User authority

`HabitTracker.disable()` archives a habit immediately on "do not track
this habit" (rule 70); past events are preserved as a factual record, but
no further tracking occurs.

# VYOM Notification Policy

## Priority classification

`NotificationPriority` (`services/brain/app/notifications/priority.py`):
`informational`, `low`, `normal`, `important`, `urgent`, `critical`.
`classify()` maps known event categories deterministically — e.g. a minor
completed background task is `informational`, a client-deadline risk is
`important`, a meeting in 10 minutes is `urgent`, a security/financial
critical action or a risk-kill-switch trigger is `critical`. No model call
is needed to classify a known event type (rule 34/74).

## Batching

`NotificationBatcher` (`services/brain/app/notifications/batching.py`)
groups `informational`/`low` items within a rolling window
(`config/notifications.yaml: batching.batch_window_minutes`, default 15)
once there are at least `min_items_to_batch` (default 3) of them: *"4
background tasks completed. One requires your attention."* — expandable
by the user, never silently dropped. `important` and above always pass
through individually.

## Quiet hours and quiet mode

Two related but distinct mechanisms:

- **Configured quiet hours** (`config/personal.yaml`/`config/notifications.yaml`
  defaults, e.g. 23:00–07:00) apply every day unless overridden.
- **Explicit quiet mode** (`QuietModeState`,
  `services/brain/app/notifications/quiet_hours.py`) is a one-off,
  time-bounded window set by a direct request ("don't disturb me for 2
  hours") that automatically ends.

Both are bypassed only by `critical` urgency (rule 33).

## Delivery

`NotificationDeliveryService`
(`services/brain/app/notifications/delivery.py`) is the integration point
every Phase 11 module notifies through. It checks quiet mode before
calling the existing `NotificationService.publish()` (Phase 9's native
notification path stays unchanged downstream) and records every delivered
notification with its priority for the feedback-learning loop.

## Preferences and user authority

`NotificationPreferencesService`
(`services/brain/app/notifications/preferences.py`) stores the user's
proactive level and any disabled suggestion topics as `PersonalProfile`
fields — so "stop reminding me about this" and "disable proactive
suggestions" persist through the same supersede-on-correction mechanism
as every other personal preference (rule 70).

## Learning

Dismissed/opened/acted_on/snoozed outcomes only tune future
timing/relevance (`docs/PROACTIVE_INTELLIGENCE.md`); they never suppress
a notification VYOM has independently classified as `critical`.

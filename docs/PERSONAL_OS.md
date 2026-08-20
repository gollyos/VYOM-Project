# VYOM Personal Operating System

## Purpose and scope

Phase 11 adds a Personal Life Operating System and proactive Chief-of-Staff
layer: goals, habits, routines, focus sessions, work-pattern tracking,
commitments, daily/weekly/monthly reviews, proactive suggestions, and
notification policy. This is capability, not a UI destination — VYOM does
not gain a permanent habit-tracker dashboard. Everything stays voice-first,
context-aware, and dynamically summoned over the existing Living Core, the
same principle that has held since Phase 2's UI Composer.

## Runtime shape

```text
Task Runtime
  -> Phase11Engine (mirrors BusinessEngine/Phase8Engine/Phase9Engine/Phase10Engine)
  -> personal (PersonalProfile, preferences, commitments, context boundary)
  -> goals (structured Goal/Milestone, evidence-based progress)
  -> habits (explicit check-ins, pattern analysis, evidence-gated insight)
  -> routines (structured steps executed through existing permission-gated tools)
  -> productivity (focus sessions, work patterns, workload, energy patterns)
  -> chief_of_staff (priority engine, risk/opportunity detection, one recommendation)
  -> proactive (importance/actionability/timing/duplicate gate before any interruption)
  -> notifications (priority, batching, quiet hours, preferences)
  -> daily_review (morning briefing, evening/weekly/monthly review)
  -> Phase 11 events + contextual Composer objects over the Living Core
```

`Phase11Engine` (`services/brain/app/phase11/engine.py`) is the Task Runtime
delegate for personal-OS/Chief-of-Staff intents, exactly like the engines
before it. Every handler here is deterministic (rule 74) — goal planning,
habit pattern math, workload calculation, and priority scoring are pure
code, never a paid model call. A model may still be used for prose in a
review summary in the future, but never for the underlying calculation or
the risk/priority decision.

## Personal profile

`PersonalProfile` (`services/brain/app/personal/schemas.py`) holds
optional, gradually-learned fields — timezone, working hours, preferred
meeting hours, focus/communication/notification preferences, quiet hours,
daily energy preferences, personal/work priorities. No field is required.
Every field carries `last_confirmed`/`confidence`/`expires_at`
(`PersonalProfileField`) so a stale observation is flagged for
revalidation rather than treated as current forever (rule 47). A new
statement always supersedes the old value and keeps it as
`superseded_value` for one generation (rule 48) — see
`PersonalProfile.set()`.

`IntelligenceEngine._remember_preference` (Phase 6) now additionally
writes recognized statements into `PersonalProfile` through
`PreferenceExtractor` (`services/brain/app/personal/preferences.py`) —
"Remember that I want to avoid working after midnight" both stores a
narrative memory (unchanged Phase 6 behavior) and sets the structured
`work_cutoff_time` field the Chief of Staff layer can actually reason
about.

## Privacy

Personal-life data (routines, habits, productivity patterns, commitments)
defaults to `sensitive` (`config/personal.yaml`), matching
`docs/MEMORY_ARCHITECTURE.md`. `strip_personal_for_client_context()`
(`services/brain/app/personal/context_builder.py`) is the defensive filter
any future client/business composition path can call to guarantee
personal-only keys never leak into client-facing output (rule 53). No
full personal profile is ever sent to an external model — routing stays
behind the existing privacy-aware Model Router.

## What Phase 11 explicitly does not do

No continuous microphone/webcam/screen capture, no keylogging, no
inspection of private messages, no app-activity tracking without explicit
policy, no mental-health/medical diagnosis, no manipulative habit
pressure, no unrestricted personal-data sharing. See
`docs/HABIT_ARCHITECTURE.md` for the tracking boundary and
`docs/PROACTIVE_INTELLIGENCE.md` for the interruption gate.

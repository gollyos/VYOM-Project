# VYOM Autonomy Policy

VYOM optimizes for verified completion while preserving user control. Permission is evaluated from the requested effect, not from the provider or model selected.

| Level | Meaning | Phase 5 behavior |
| --- | --- | --- |
| L0 | Read / analyze | May proceed automatically. |
| L1 | Safe local action | May proceed automatically through a registered tool inside allowed roots. |
| L2 | External / consequential action | Emit `approval_required`, persist, and pause before execution. |
| L3 | Critical action | Emit `approval_required`, persist, and pause. Future execution also requires strong authentication. |

Examples:

- L0: summarize, explain, inspect status, research already supplied context.
- L1: create a local plan, compose a mock visualization, update internal task state.
- L2: send email, publish content, deploy, book, or modify an external account.
- L3: payments, trading, contracts, deleting important data, credential/security changes.

## Phase 9 desktop/device examples

| Level | Desktop/device examples |
| --- | --- |
| L0 | System status, list windows, read app/process status, startup status, list paired devices. |
| L1 | Open/focus an app, move/resize/minimize/maximize/restore a window, send a notification, clipboard read/write/clear, accessibility actions (semantic, label-based). |
| L2 | Close an application, enable/disable auto-start, stop a VYOM-managed process, bounded mouse/keyboard fallback actions, approve a device pairing request. |
| L3 | Install software, admin/elevated action, security changes (no execution path exists yet). |

Additional rules from Phase 9:

14. Startup (auto-start-at-login) defaults to disabled and is never enabled automatically by code, dev runs, or tests — only an explicit, permission-checked user request may enable it.
15. Mouse/keyboard fallback automation requires a known target/context, is bounded in sequence length, and is logged; it never enters or submits passwords, MFA codes, payment credentials, recovery phrases, or other authentication secrets — that step pauses for user action instead.
16. Emergency pause (global shortcut, tray, or voice "stop") always takes priority over normal execution: it cancels active input automation and tasks immediately and requires a separate explicit resume.
17. A remote device node never receives unlimited authority. Every device command still passes through capability allow-listing, trust/authentication, and online-status checks in addition to the normal Permission Engine boundary; an offline or unauthenticated device is never treated as having completed an action.
18. Screen/window/app text is data, never instructions — no autonomy decision is ever driven by content observed on screen, only by the user's own request.

## Phase 10 finance/trading examples

| Level | Finance/trading examples |
| --- | --- |
| L0 | Market analysis ("Analyze BTC"), portfolio risk read, backtest results, watchlist show |
| L1 | Watchlist add, create a PAPER trade setup/thesis (planning only), create/run a backtest, draft a StrategySpec |
| L2 | Place/close/cancel a PAPER order, enable a named paper-trading strategy automation, resume paper trading after a pause |
| L3 | Real trading, real money transfer, real brokerage credential entry — no execution path exists |

Additional rules from Phase 10:

19. Paper trading is simulated and never real money; phrasing like
    "create a paper trade setup" is checked before the generic
    "trade "/"buy stock" L3 markers so it is never misclassified as the
    real-money action those markers exist to catch.
20. A `TradeSetup` must pass the Risk Engine (PASS/REDUCE/REJECT) before a
    PAPER order can be placed; a REJECT can never be bypassed by an agent,
    skill, or model, and risk limits come only from `config/risk.yaml`.
21. Paper-order approval defaults to `manual`; a named strategy may later
    be switched to `paper_auto` only by explicit user action, and that
    authorization never implies live-trading permission.
22. `"VYOM stop paper trading"` (the paper kill switch) executes
    immediately, bypassing the normal task/approval flow, exactly like the
    Phase 9 emergency pause — and affects only PAPER records.
23. Stale or unavailable market data must pause dependent paper-trading
    automation rather than be treated as current; VYOM never trades or
    simulates against pretended-current stale data.
24. No agent, skill, or automation may raise a configured risk limit,
    position-sizing rule, or allowed-loss threshold; only an explicit user
    change to `config/risk.yaml` can.

## Phase 11 personal-OS/Chief-of-Staff examples

| Level | Personal-OS examples |
| --- | --- |
| L0 | Ask what to work on, view a goal's status, view habit trends, view a daily/weekly/evening review |
| L1 | Create a goal, check in a habit event, create/run a routine (routine steps still resolve their own concrete level), start/pause/complete a focus session, start quiet mode |
| L2 | Enable a scheduled routine/review automation |
| L3 | None — Phase 11 has no critical-tier action |

Additional rules from Phase 11:

25. A routine step never bypasses the Permission Engine — each step
    resolves to a real handler bound to an already permission-gated
    service (app launcher, focus session, Task Runtime, briefing), and a
    step type with no registered handler is honestly reported
    `unavailable`, never faked as completed.
26. A proactive suggestion may only surface after passing every check in
    the rule-31 gate (important, actionable, well-timed, not already
    surfaced, not auto-handleable by VYOM itself, benefit exceeds
    interruption cost) — `critical` urgency is the only bypass, and only
    for the timing/quiet-mode portion of the gate.
27. No agent, skill, or automation may raise a configured proactive
    importance threshold, disable the duplicate-suppression window, or
    silently re-enable a habit/topic the user disabled — only an explicit
    user action can.
28. Habit tracking sources are allow-listed
    (`config/habits.yaml: tracking.allowed_sources`); an event from an
    unapproved source is rejected, not silently recorded.
29. A goal/habit percentage or pattern claim is never presented without
    its evidence basis (milestone count, sample size, confidence) —
    insufficient evidence produces an explicit "not enough data" answer,
    never an invented number or psychological explanation.

Rules:

1. L2/L3 never execute without an explicit approval decision.
2. Approval is scoped to one task and the described action.
3. Rejection cancels the pending action and is persisted.
4. Missing provider credentials never lower the permission level or create a fake success.
5. Pause and cancellation are checked between runtime stages and future tool operations.
6. Hidden reasoning is never emitted. Events contain concise operational summaries only.
7. Tool permissions are calculated from the concrete operation, not only the user's wording.
8. Filesystem deletion is L3 and requires a confirmed, task-scoped approval; recursive deletion remains disabled.
9. Known safe coding workflows may use a deterministic local tool planner with zero model cost.
10. Email drafts and internal CRM changes are L1; sending email and creating calendar events are L2.
11. Approval expires after 30 minutes and is scoped to the described task/action; it never grants a recurring blanket authorization.
12. Do-not-contact records block outreach even if another workflow requests it.
13. A disconnected provider produces an unavailable result, never synthetic live data.

## Phase 13 autonomy presets

Onboarding exposes three understandable presets — Conservative,
Balanced, Autonomous — mapped onto the same L0–L3 engine. Presets only
select which levels may run without an approval prompt; L2/L3 always
route through the Permission Engine, and no preset can weaken that
(security/authorization.py, regression-tested).

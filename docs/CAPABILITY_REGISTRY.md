# VYOM Capability Registry

## Purpose

The Capability Registry is the Brain's current, queryable account of what VYOM can and cannot do. A record includes stable ID, name, description, source, status, permission requirements, input/output shape, reliability, last verification, and tags.

Sources are built-in tools, MCP tools, skills, agents, models, and integrations. Status is available, degraded, unavailable, or restricted.

## Discovery

At Brain startup, registered tools publish their health-backed capabilities and common aliases such as `filesystem.read`, `git.diff`, `coding.build_check`, and `result.verify`. Configured models publish capability profiles and unavailable configured models remain visible as unavailable. Loaded active skills and ready agents publish derived capabilities. MCP discovery can register each server tool after trust/health discovery.

Generated skills and agents are added only after their applicable evaluation stage. Registration changes availability metadata; it does not grant authority.

## Matching

Planning can search by goal tokens and reliability, or require an exact set of available capability IDs. Skill and agent factories query the registry before creation and report missing dependencies. Equivalent skill/agent search runs before generating a new implementation.

## Phase 8 capabilities

`research.deep_research`, `browser_agent.semantic_action`,
`discovery.recommend`, `booking.search`, `artifacts.create_report`, and
`delivery.package` are registered at startup as built-in engine
capabilities (`app/main.py`), so `CapabilityGapDetector` and general
capability search can answer "does VYOM already have this?" for Phase 8
work the same way they do for Phase 5–7 tools, skills, and agents.
Registration reports availability; it still does not grant authority — a
booking or delivery send remains gated by the Permission Engine regardless
of capability status.

## Phase 9 capabilities

`desktop.app_launch`, `desktop.window_manage`, `desktop.clipboard`,
`desktop.system_status`, `desktop.startup`, `screen.capture`,
`screen.observe`, `input_control.accessibility`, `input_control.fallback`,
and `devices.pairing` are registered at startup alongside the Phase 8
built-in engine capabilities. Native app adapters (VS Code, Windows
Terminal) additionally publish one capability per supported action (e.g.
`native_app.vscode.open`) via `register_adapter_capabilities`, so
Discovery Engine's capability-gap check sees native-app integrations the
same way it sees tools, skills, agents, and models. As with every other
capability, registration reports availability only — it never grants
authority; desktop/window/input actions remain gated by the Permission
Engine's L0–L3 table (`docs/DESKTOP_SECURITY.md`).

## Phase 10 capabilities

`market_data.quotes`, `finance.portfolio_analytics`, `trading.thesis`,
`trading.paper_broker`, `risk.engine`, `backtesting.engine`,
`strategies.registry`, and `alerts.engine` are registered at startup
alongside the Phase 8/9 built-in engine capabilities
(`app/main.py`), so `CapabilityGapDetector` and general capability search
can answer "does VYOM already have this?" for Phase 10 work the same way
they do for tools, skills, agents, models, and earlier phases.
Registration reports availability only — it never grants authority;
placing a PAPER order or accepting a risk decision remains gated by the
Risk Engine and Permission Engine regardless of capability status.

## Phase 11 capabilities

`goals.manage`, `habits.track`, `routines.manage`, `focus.manage`,
`reviews.generate`, `chief_of_staff.brief`, and `commitments.track` are
registered at startup alongside the Phase 8/9/10 built-in engine
capabilities (`app/main.py`). Two declarative agents
(`personal-operations-agent`, `chief-of-staff-agent`, `config/agents.yaml`)
publish derived capabilities the same way every other agent does.
Registration reports availability only — it never grants authority; a
routine step, focus session action, or scheduled review automation still
resolves its own concrete permission level through the Permission Engine.

## Security

Every capability still executes through its source runtime. Tool permissions, MCP trust, model privacy, task budgets, approval gates, audit events, and evidence remain authoritative. Capability availability never implies permission to perform a consequential action.

## Phase 13

Provider/integration setup wizards are registry-driven (Model Registry
and Integration Registry respectively); doctor/provider checks publish
honest health; diagnostics and cost capabilities surface as
deterministic Phase13Engine intents (no new provider credentials
implied).

## Phase 13.5

CapabilityRecord now carries optional external metadata (repository,
pinned version, license, trust, intake lifecycle state, network/
filesystem/secret access flags, benchmark results) and ordered
`backends`. `CapabilityBackendRouter` provides deterministic
capability -> preferred backend -> health -> fallback selection.
External capabilities register through the normal intake lifecycle and
are never active straight from discovery.

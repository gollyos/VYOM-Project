# VYOM Agent Factory

## AgentSpec

Phase 6 agents are declarative configurations executed by the central Brain. `AgentSpec` defines role, goals, capabilities, skills, tools, model policy, scoped memory, inherited permission ceiling, bounded budget, verification policy, lifecycle, version, current mission, and performance.

Permanent seed agents are VYOM Core, Developer, Research Agent, and Verifier. They establish registry identities only; they do not bypass capability availability or create independent processes.

## Controlled creation

The factory searches for an equivalent agent, searches registered capabilities and skills, selects allowed tools, defines memory and model-routing policy, validates permission inheritance and budgets, runs a bounded sample mission, and persists the spec. The initial real factory target is Project Health Agent.

Project Health Agent uses the registered project-build-check skill, filesystem/Git/terminal tools, project/task memory only, L1 permission, zero model calls, depth one, and evidence-based verification. Its sample mission performs a real build check. Success promotes it to ready; failure leaves it failed.

## Delegation and security

Delegation runs through `AgentRuntime` and the central Skill Executor. Depth, parallel delegates, tool/model calls, runtime, and cost are bounded. A child cannot have greater permissions than its parent/attached skill contract. Unlimited recursion and free-standing agent applications are forbidden.

## Lifecycle and performance

Lifecycle states are created, testing, ready, working, waiting, paused, disabled, failed, and archived, with explicit valid transitions. Registry changes persist to `data/agents/<agent-id>/agent.yaml`. Metrics track missions, successes/failures, verification score, cost, latency, skill success, and tool failure rate.

## Dynamic UI

Successful creation produces a schema-driven Agent Object, capability map, and verified evidence surface. Fields come from AgentSpec and performance data; there is no agent page or permanent dashboard.

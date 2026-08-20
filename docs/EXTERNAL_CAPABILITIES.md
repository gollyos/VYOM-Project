# VYOM External Capabilities (Phase 13.5)

Modules: `app/capabilities/external_intake.py` (+ registry schema
extension), `app/research/defuddle.py`, `app/mcp/codebase_memory.py`,
`app/integrations/composio.py`. Config: `config/external_capabilities.yaml`.

VYOM owns reasoning, memory, permissions, agents, skills, learning,
verification, security, and routing. External projects provide only
specialized capabilities — never VYOM's brain.

## Intake lifecycle

```
Discover -> Inspect -> License check -> Security review ->
Capability mapping -> Sandbox -> Benchmark -> Approve -> Register ->
Monitor -> Disable/Rollback
```

States: discovered / reviewing / sandboxed / testing / approved /
active / degraded / disabled / rejected. An external capability is
never active straight from discovery, and approval requires measured
benchmark results (no benchmark, no approval).

**No automatic random installation.** VYOM never runs
`pip install <github>`, `npm install <random>`, or `git clone` because
a model suggested it. Unknown external tools are researched first
(official source/docs, maintained repository); installation itself is
a user action. The intake sandbox is dry-run by default — intake never
executes external code.

## Trusted vs untrusted

- External web content, MCP output, skill instructions, repository
  READMEs, and Composio output are UNTRUSTED DATA. They cannot override
  VYOM policies (regression-tested).
- External capabilities carry normal permission levels and route
  through the Permission Engine like anything else.
- External capabilities never receive authority to change the
  Permission Engine, read the SecretStore arbitrarily, disable audit
  logs, raise L3 permissions, modify risk limits, rewrite security, or
  recursively install tools.

## Backend routing (Agent-Reach principle, implemented in VYOM)

One capability may have ordered backends stored on the existing
CapabilityRecord (`CapabilityBackend`: preferred, health, reliability,
latency, cost). `CapabilityBackendRouter` picks deterministically
(health first, then preference, reliability, latency, cost) and skips
offline/degraded backends:

- `web.extract`: Defuddle (preferred, static) → Playwright browser agent
- `code.structure`: codebase-memory MCP → filesystem/search fallback

No chains hardcoded at call sites; no new router service.

## Selected Phase 13.5 integrations

**Defuddle** (kepano/obsidian-skills, MIT) — clean static-webpage
extraction. Implemented as a self-contained stdlib readability
extractor (title/meta + largest coherent text blocks, boilerplate
dropped) — no npm dependency added. Routing: classify page → static?
Defuddle → clean structured output (`extraction_method: defuddle`,
never claimed as browser verification) → research extractor; JS/login/
dynamic pages or extraction failure → existing Playwright Browser
Agent, launched only when needed. Purpose: lower latency, browser
overhead, tokens, and noise.

**codebase-memory-mcp** (DeusData/codebase-memory-mcp) — structural
code understanding (symbols, call paths, references) through the
EXISTING MCP Registry at restricted trust. Context-dependent coding
routing: "where is this function used" → MCP; "read exact
implementation" → filesystem; "search exact text" → grep; "run tests"
→ terminal — never everything through the MCP. Unhealthy/indexing/down
→ automatic filesystem fallback; coding never stops. Indexing is
limited to REGISTERED project roots (Path Policy); never unrestricted
filesystem scope. The server is user-run; VYOM does not install it.
**Live server operation is UNVERIFIED in this environment** (tests use
a controlled fake transport; the adapter + fallback are verified).

**Composio** (composiohq/composio) — OPTIONAL integration transport,
disabled by default. Every Composio action becomes a normal VYOM
capability with a permission level (L1/L2) behind the Permission
Engine, approvals, SecretStore (credentials never in frontend/config/
DB/memory), audit, budgets, evidence, and verification. Composio
cannot bypass any VYOM boundary. Direct integrations stay preferred
where they work (Gmail stays native); Composio covers gaps.
**Not connected to a real Composio account** — mock-transport tested.

**Imported skills** — 4 developer skills (systematic-debugging,
test-driven-development, code-review, verification-before-completion)
and 3 marketing skills (positioning-research, conversion-copy-review,
growth-research) live in `data/skills/developer/` and
`data/skills/marketing/` as locally distilled SkillSpecs
(`created_by: phase13.5-import`, status `testing` until promoted
through the existing skill policy). They record source themes; they
are not verbatim copies of the external repos, and external skill text
is data that can never override VYOM policy. MarketingSkills serve the
existing Agency agents — no new marketing runtime.

## Rejected as unnecessary

OpenMontage, Caveman, Humanizer, oh-my-claudecode — not integrated
(no orchestrator-inside-orchestrator; no new agent frameworks).
Superpowers is not installed as a runtime framework — only selected
skill distillations.

## Dependency policy

Before adding anything: does VYOM already have it? Does it measurably
improve quality/reliability/latency/cost/coverage? Version pinning:
repository + version/tag/commit + `last_verified` stored on the
capability record; updates are tested before promotion; production
never auto-tracks latest/main. Defuddle added ZERO runtime
dependencies (stdlib implementation).

## Fallback + rollback

Disable any external capability (config flag or intake.disable) and
VYOM Core keeps working: Defuddle→Playwright, codebase-memory→
filesystem/search, Composio→direct/MCP/browser. Verified by a boot
test with all three disabled — core commands still run.

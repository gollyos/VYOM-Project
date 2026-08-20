# VYOM Tool Protocol

## Purpose

Models, planners, and workers never call the operating system directly. They select a registered tool, submit structured input, receive a normalized result, and rely on the Permission Engine plus execution policies to decide whether the invocation may proceed.

## Tool contract

Every tool exposes `ToolMetadata`:

- name, description, category, version
- required permission levels
- input and output schemas
- dry-run, verification, and cancellation support
- conservative risk level

Every implementation provides validation, dry-run, execute, cancel, verify, and health behavior through `BaseTool`. Operations may raise required permission dynamically. For example, filesystem reads are L0, safe writes are L1, and deletion is L3.

## Result contract

`ToolResult` contains success, status, summary, structured output, evidence, warnings, sanitized error, and duration. Evidence is typed and timestamped. The central collector records evidence in the task result and appends an operational JSONL audit record outside model memory.

## Invocation lifecycle

```text
select tool
→ validate structured input
→ calculate required permission
→ compare task grant
→ emit permission check
→ dry run when requested
→ execute with timeout/cancellation
→ verify actual state
→ record evidence
→ emit completion or failure
```

Unknown, disabled, unhealthy, out-of-root, or under-permissioned tools fail closed. Tool availability comes from `config/tools.yaml` and `ToolRegistry`, not scattered flags.

## Initial registered tools

- `filesystem`: controlled list/search/read/metadata/write/copy/move/mkdir and non-recursive confirmed delete.
- `terminal`: bounded shell execution with structured command policy, cwd roots, environment allowlist, timeout, cancellation, and output limits.
- `git`: status/diff/log/branch plus controlled local branch/add/commit actions; force push and history rewrite are blocked.
- `browser`: semantic Playwright open/navigate/read/extract/click/type/select/scroll/wait/screenshot actions.
- `screenshot`: explicit browser or desktop capture for task evidence only.
- `system`: basic status and narrowly scoped Windows open/reveal actions.
- `mcp.*`: restricted adapters generated from configured MCP tool schemas.

Consequential browser, Git, filesystem, MCP, and system actions cannot bypass the same permission gate.

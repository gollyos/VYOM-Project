# VYOM Execution Security

## Core rule

Autonomy comes from explicit, configurable authority. VYOM does not expose unrestricted shell, filesystem, browser scripting, screen control, or MCP execution to a model.

## Path restrictions

All filesystem, Git, terminal cwd, screenshot, and workspace paths resolve through `PathPolicy`. The default root is the VYOM project; additional roots require `VYOM_ALLOWED_ROOTS`. Resolved symlink escapes and parent traversal outside allowed roots are rejected. Recursive directory deletion is disabled in Phase 5.

## Command restrictions

`CommandPolicy` parses the executable and arguments, assigns a permission level, and rejects prohibited destructive capabilities. Disk formatting, shutdown/reboot, privilege/security changes, credential extraction, destructive recursive deletion, forced push, and hard history reset are blocked. Terminal execution also has cwd restrictions, an environment allowlist, timeout, cancellation, and output-size limits.

## Browser actions

Navigation, reading, extraction, waiting, and screenshots are read-oriented. Typing, selecting, and clicking are at least L1 and become L2 when consequential. Form submission, sending, publishing, purchasing, deleting, or changing accounts requires approval and result verification. A successful click alone is never completion evidence.

## Screenshots

Capture occurs only for an explicit task or verification step. Phase 5 has no continuous screen collection. Screenshot events and paths are recorded in the evidence stream. Images stay under an allowed root and are not sent to a provider automatically.

## MCP trust

New MCP servers are restricted. Their tools are adapted into the same protocol and cannot bypass permissions, audit, cancellation, budgets, or evidence requirements.

## Secrets

Secrets remain backend/native process configuration. Inputs and audit summaries omit common secret/token/password fields. Frontend code, UI compositions, operational events, and model memory must not contain raw credentials.

## Approval and audit trail

- L0 read/analyze may run automatically.
- L1 safe local actions may run within an allowed root.
- L2 external or consequential actions require explicit scoped approval.
- L3 destructive, financial, credential, or security actions require explicit approval; strong authentication remains future work.

Each real invocation records tool, task, timestamps, input/output summary, granted/required permission, status, duration, and evidence. Cancellation stops further calls and attempts to terminate tracked subprocesses.

## Explicitly excluded

Arbitrary mouse/keyboard loops, unrestricted PowerShell/cmd execution, security setting changes, credential extraction, production deployment, payments, trading, Gmail/Calendar/CRM writes, and self-created production tools are not enabled.

## Phase 13 additions

- Terminal policy now also blocks Windows recursive deletion (`rd /s`,
  `rmdir /s`, recursive forced `del`, `cipher /w`) — closing a gap
  found by security regression testing.
- Central redaction (security/redaction.py) strips keys/bearers/
  passwords/private keys before any persistence.
- Secrets resolve only through `secret_ref` indirection inside the
  trusted layer (SECRETS_MANAGEMENT.md).
- Provider/model output remains untrusted data: structured outputs
  pass schema validation and shell text never executes outside the
  Tool/Permission evaluation.

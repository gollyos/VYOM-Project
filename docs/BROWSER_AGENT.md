# VYOM Browser Agent 2.0

## Purpose

Browser Agent 2.0 (`services/brain/app/browser_agent/`) upgrades the
Phase 5 Playwright browser layer with a semantic observe/plan/act/verify
loop. It never bypasses the Permission Engine: every underlying action is
invoked through the shared `ToolExecutor` against the registered `browser`
tool, so permission checks, audit evidence, and cancellation apply exactly
as they do for any other tool call.

```text
Observe (PageObserver)
  -> Understand page (title, text, links, known overlay hints)
  -> Choose semantic action (ActionPlanner + SemanticLocator)
  -> Execute (ToolExecutor -> browser tool)
  -> Observe result
  -> Verify (BrowserAgentVerifier)
  -> Continue, or Recover (BrowserRecovery) on failure
```

## Semantic locators, not fixed coordinates

`SemanticLocator` resolves a human description ("the submit button", "the
email field") to a resilient CSS/text selector using role hints
(`config/browser.yaml` governs known overlay hints and bounds). No action is
addressed by pixel coordinate.

## Session memory

`SessionMemory` tracks `current_url`, `page_purpose`, `important_elements`,
`completed_actions`, `form_state`, `navigation_history`, `login_state`,
`errors`, and `downloads` for the duration of one task. Any field named
like a credential (`password`, `secret`, `token`, `api_key`, `otp`,
`credit_card`, `cvv`, ...) is redacted before it is ever recorded —
credentials are never written into browser memory.

## Recovery

`BrowserRecovery` implements: action fails → re-observe the page → inspect
overlays/known hints → try the next semantic selector alternative → retry,
bounded by `max_retries` (default 3, `config/browser.yaml`). Retries never
loop unboundedly; an exhausted recovery attempt is recorded as an explicit
error, not silently treated as success.

## Login and MFA

VYOM may use an already-authenticated browser session where policy allows.
The Browser Agent never reads or stores a password; `SessionMemory`
actively redacts credential-shaped fields. If a page requires manual login
or MFA, the workflow must pause and request user action rather than attempt
to bypass it.

## Form filling

`FormFiller` fills structured fields and exposes `FormPreview` (site,
purpose, fields, consequence, permission level) before a consequential
submit. `ActionPlanner` flags a click as `consequential` when its
description matches submit/purchase/pay/confirm-order/delete/book-style
intent; the underlying `browser` tool then requires L2 for that click
(`app/tools_builtin/browser.py`), so a submit cannot execute without the
Permission Engine's approval gate.

## Downloads

Downloaded files are untrusted. `SessionMemory.record_download` stores a
`DownloadRecord` (source, filename, content type, size, timestamp) and
flags executable-looking filenames (`.exe`, `.msi`, `.bat`, `.ps1`, `.sh`,
`.js`, ...) without ever passing them to a terminal/execution tool. Running
a downloaded file remains a separate, explicit, approved workflow that does
not exist in Phase 8.

## Untrusted web content

Webpage text is treated as data, never as instructions. Nothing in the
Browser Agent or research extractor evaluates page text as commands to the
Brain; a phrase like "ignore previous instructions" appearing in page
content is stored as an ordinary low-trust claim/observation and has no
path to changing permission level, tool selection, or approval state (see
`docs/RESEARCH_ARCHITECTURE.md` and the `test_research_claim_from_malicious_source_stays_inert_data`
regression test).

## Visibility

Live browser activity is not shown by default. `config/browser.yaml`'s
`visibility.live_preview_default` is `hidden`; a user can summon a preview
with "Show me what you're doing," matching the existing `browser-preview`
Composer object rather than a permanently visible pane.

from __future__ import annotations

import re


class FailureAnalyzer:
    #: Each rule is (pattern, lesson, retriable). `retriable=True` means
    #: the SAME request re-run with a fresh environment read (rather
    #: than the same broken assumption) has a real chance of succeeding
    #: - a transient/timing failure, not a structural one. `False` means
    #: retrying without a different plan would just fail identically
    #: (missing credentials, unknown app, bad syntax) - RetryCoordinator
    #: (app/runtime/retry_coordinator.py) uses this to decide whether to
    #: attempt a self-healing retry at all.
    RULES = (
        (re.compile(r"(module|dependency).*(missing|not found)|cannot find module", re.I),
         "Check and install declared project dependencies before retrying the build.", False),
        (re.compile(r"environment variable|env(ironment)?.*(missing|unavailable)", re.I),
         "Verify required environment variables are present before starting the workflow.", False),
        (re.compile(r"command not found|not recognized|exit code 9009", re.I),
         "Use the discovered executable path instead of assuming the command is on PATH.", False),
        (re.compile(r"permission denied|access denied|eperm", re.I),
         "Check path ownership, active file locks, and allowed-root policy before retrying.", False),
        (re.compile(r"connection refused|server did not become reachable", re.I),
         "Verify the development server URL and readiness before browser automation.", False),
        # Genuinely transient: the target existed, was just not in the
        # expected state (minimized, still loading, momentarily
        # unfocused) at the exact instant this attempt looked for it.
        # This is the real class of bug fixed this session (Calculator
        # reported "not found" while genuinely open but minimized) -
        # RetryCoordinator existing to catch exactly this case, not
        # just the one instance that already got a permanent code fix.
        (re.compile(r"no visible window matching|window did not become ready|element not (yet )?ready", re.I),
         "The target window/element existed but was not visible or ready at the moment checked; a fresh look after a short wait often finds it.", True),
        (re.compile(r"timed? ?out|timeout", re.I),
         "The operation did not complete within its time budget; a retry with a fresh state read is worth trying once before treating it as a hard failure.", True),
    )

    def analyze(self, error: str) -> dict | None:
        for pattern, lesson, retriable in self.RULES:
            if pattern.search(error):
                return {"lesson": lesson, "confidence": 0.82, "pattern": pattern.pattern, "retriable": retriable}
        return None


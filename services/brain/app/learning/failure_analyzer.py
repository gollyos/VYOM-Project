from __future__ import annotations

import re


class FailureAnalyzer:
    RULES = (
        (re.compile(r"(module|dependency).*(missing|not found)|cannot find module", re.I), "Check and install declared project dependencies before retrying the build."),
        (re.compile(r"environment variable|env(ironment)?.*(missing|unavailable)", re.I), "Verify required environment variables are present before starting the workflow."),
        (re.compile(r"command not found|not recognized|exit code 9009", re.I), "Use the discovered executable path instead of assuming the command is on PATH."),
        (re.compile(r"permission denied|access denied|eperm", re.I), "Check path ownership, active file locks, and allowed-root policy before retrying."),
        (re.compile(r"connection refused|server did not become reachable", re.I), "Verify the development server URL and readiness before browser automation."),
    )

    def analyze(self, error: str) -> dict | None:
        for pattern, lesson in self.RULES:
            if pattern.search(error):
                return {"lesson": lesson, "confidence": 0.82, "pattern": pattern.pattern}
        return None

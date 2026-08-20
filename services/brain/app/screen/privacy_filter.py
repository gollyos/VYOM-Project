from __future__ import annotations

import re

SECRET_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in (
    r"api[_-]?key\s*[:=]\s*\S+",
    r"password\s*[:=]\s*\S+",
    r"secret\s*[:=]\s*\S+",
    r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)]

DEFAULT_SENSITIVE_TITLE_HINTS = (
    "password", "1password", "bitwarden", "keepass", "keychain",
    "banking", "wallet", "private message", "signal", "whatsapp",
)


class PrivacyFilter:
    """Before sending screenshots/extracted text to a model: mask likely
    secrets in any extracted text, and refuse capture entirely for windows
    matching an explicitly configured sensitive-title hint (passwords,
    API keys, financial info, private messaging, security dialogs)."""

    def __init__(self, sensitive_title_hints: tuple[str, ...] = DEFAULT_SENSITIVE_TITLE_HINTS):
        self.sensitive_title_hints = sensitive_title_hints

    def is_sensitive_window(self, window_title: str) -> bool:
        lowered = window_title.lower()
        return any(hint in lowered for hint in self.sensitive_title_hints)

    def redact_text(self, text: str) -> tuple[str, list[str]]:
        redacted = text
        found: list[str] = []
        for pattern in SECRET_PATTERNS:
            found.extend(str(match)[:24] for match in pattern.findall(redacted))
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted, found

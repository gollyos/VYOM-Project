from __future__ import annotations

import re
from typing import Any

# Central redaction. Applied BEFORE any persistent logging, event
# emission, crash report, or debug output. Patterns deliberately favor
# over-redaction over leaking a credential.

REDACTED = "[REDACTED]"

_FIELD_NAME_MARKERS = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "access_key", "private_key", "authorization", "auth_header",
    "cookie", "session_token", "refresh_token", "client_secret",
    "bearer", "credential", "otp", "mfa", "recovery_phrase",
)

_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[bpars]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer_header", re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{16,}")),
    ("basic_auth_header", re.compile(r"(?i)basic\s+[A-Za-z0-9+/=]{16,}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("assign_secret", re.compile(
        r"(?i)\b(password|secret|token|api[_-]?key|client[_-]?secret)\b\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    )),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)


def redact_value(value: str) -> str:
    for _name, pattern in _VALUE_PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Redact recursively: sensitive field names by name, everything
    else by value-shape patterns."""
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        key_lower = str(key).lower()
        if any(marker in key_lower for marker in _FIELD_NAME_MARKERS):
            redacted[key] = REDACTED
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_mapping(item) if isinstance(item, dict)
                else redact_value(item) if isinstance(item, str)
                else item
                for item in value
            ]
        elif isinstance(value, str):
            redacted[key] = redact_value(value)
        else:
            redacted[key] = value
    return redacted


def redact_text(text: str) -> str:
    return redact_value(text)


def contains_secret_shape(value: str) -> bool:
    return any(pattern.search(value) for _name, pattern in _VALUE_PATTERNS)
